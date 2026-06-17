"""NeMo Canary backend adapter."""

from __future__ import annotations

import atexit
import gc
import inspect
import logging
import os
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np

from dictate.stt.base import ComputeDevice, SpeechToText, SttCapabilities

logger = logging.getLogger(__name__)


class NeMoCanarySpeechToText(SpeechToText):
    """NVIDIA NeMo Canary backend."""

    backend_name = "nemo-canary"
    capabilities = SttCapabilities(
        supports_hotwords=False,
        supports_prompt_bias=True,
        supports_language_hint=True,
        supports_streaming_chunks=True,
    )

    def __init__(
        self,
        model_name: str = "nvidia/canary-1b-flash",
        device: ComputeDevice = "auto",
    ):
        self.model_name = model_name
        self.device = device
        self._model: Any | None = None
        self._temp_wav_path: str | None = None
        self._io_lock = threading.Lock()
        self._warned_context_unsupported = False

    @property
    def model(self) -> Any:
        if self._model is None:
            self._model = self._load_model()
        return self._model

    def _load_model(self) -> Any:
        logger.info("Loading NeMo model: %s", self.model_name)
        # Work around observed hangs in hf_xet on large Canary artifacts.
        # Users can override by exporting HF_HUB_DISABLE_XET=0 before launch.
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        self._cleanup_hf_partial_downloads(self.model_name)
        try:
            from nemo.collections.asr.models import ASRModel
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                'NeMo backend requires nemo_toolkit[asr]. Install with: uv pip install -e ".[nemo]"'
            ) from exc

        loader_errors: list[str] = []
        model: Any | None = None

        for loader_name in ("ASRModel", "EncDecMultiTaskModel"):
            loader = self._resolve_loader(loader_name, ASRModel)
            if loader is None:
                continue
            try:
                model = self._load_with_fallback(loader)
                break
            except Exception as exc:  # noqa: BLE001
                loader_errors.append(f"{loader_name}: {exc}")

        if model is None:
            joined_errors = "; ".join(loader_errors) if loader_errors else "unknown loader failure"
            raise RuntimeError(
                f"Failed to load NeMo model '{self.model_name}': {joined_errors}"
            )

        if self.device == "cpu" and hasattr(model, "cpu"):
            model = model.cpu()
        if self.device == "cuda" and hasattr(model, "cuda"):
            model = model.cuda()
        if hasattr(model, "eval"):
            model.eval()

        logger.info("Model loaded")
        return model

    @staticmethod
    def _cleanup_hf_partial_downloads(model_name: str) -> None:
        # Remove stale partials/locks from interrupted xet downloads so standard hub fetch can proceed.
        try:
            repo_dir_name = f"models--{model_name.replace('/', '--')}"
            hub_root = Path.home() / ".cache" / "huggingface" / "hub"

            blobs_dir = hub_root / repo_dir_name / "blobs"
            if blobs_dir.is_dir():
                for partial in blobs_dir.glob("*.incomplete"):
                    partial.unlink(missing_ok=True)

            locks_dir = hub_root / ".locks" / repo_dir_name
            if locks_dir.is_dir():
                for lock_file in locks_dir.glob("*.lock"):
                    lock_file.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            # Best-effort cleanup only; never block model loading on cache hygiene.
            return

    @staticmethod
    def _resolve_loader(loader_name: str, asr_model_cls: Any) -> Any | None:
        if loader_name == "ASRModel":
            return asr_model_cls.from_pretrained
        if loader_name == "EncDecMultiTaskModel":
            try:
                from nemo.collections.asr.models import EncDecMultiTaskModel
            except Exception:  # noqa: BLE001
                return None
            return EncDecMultiTaskModel.from_pretrained
        return None

    def _load_with_fallback(self, loader: Any) -> Any:
        if self.device == "cpu":
            try:
                return loader(self.model_name, map_location="cpu")
            except TypeError:
                return loader(self.model_name)
        return loader(self.model_name)

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
    ) -> str:
        del hotwords
        with self._io_lock:
            wav_path = self._get_temp_wav_path()
            _write_wav_file(wav_path, audio)
            outputs = self._transcribe_path(
                wav_path,
                language=language,
                prompt_context=prompt_context,
            )
        return self._extract_text(outputs).strip()

    def _get_temp_wav_path(self) -> str:
        if self._temp_wav_path is not None:
            return self._temp_wav_path
        temp = tempfile.NamedTemporaryFile(prefix="dictate-", suffix=".wav", delete=False)
        temp.close()
        self._temp_wav_path = temp.name
        atexit.register(self._cleanup_temp_wav)
        return self._temp_wav_path

    def _cleanup_temp_wav(self) -> None:
        if not self._temp_wav_path:
            return
        try:
            os.unlink(self._temp_wav_path)
        except OSError:
            pass

    def _transcribe_path(
        self,
        wav_path: str,
        *,
        language: str | None,
        prompt_context: str | None,
    ) -> Any:
        transcribe_fn = self.model.transcribe
        params = inspect.signature(transcribe_fn).parameters
        kwargs: dict[str, Any] = {}

        if "batch_size" in params:
            kwargs["batch_size"] = 1
        if "pnc" in params:
            kwargs["pnc"] = "yes"
        if "source_lang" in params:
            kwargs["source_lang"] = language or "en"
        if "target_lang" in params:
            kwargs["target_lang"] = language or "en"
        if prompt_context:
            kwargs["context"] = prompt_context

        try:
            return transcribe_fn([wav_path], **kwargs)
        except Exception as exc:  # noqa: BLE001
            if prompt_context and self._is_context_unsupported_error(exc):
                kwargs.pop("context", None)
                if not self._warned_context_unsupported:
                    logger.warning(
                        "Canary model '%s' does not support prompt context; continuing without it.",
                        self.model_name,
                    )
                    self._warned_context_unsupported = True
                return transcribe_fn([wav_path], **kwargs)
            raise

    @classmethod
    def _extract_text(cls, outputs: Any) -> str:
        if outputs is None:
            return ""
        if isinstance(outputs, str):
            return outputs
        if isinstance(outputs, dict):
            for key in ("text", "pred_text"):
                if key in outputs:
                    return str(outputs[key])
            return str(outputs)
        if isinstance(outputs, list):
            texts = [cls._extract_text(item).strip() for item in outputs]
            return " ".join(text for text in texts if text)
        if hasattr(outputs, "text"):
            return str(outputs.text)
        return str(outputs)

    @staticmethod
    def _is_context_unsupported_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "context feature is not supported" in message

    def release(self) -> None:
        self._model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:  # noqa: BLE001
            return


def _write_wav_file(path: str, audio: np.ndarray, sample_rate: int = 16000) -> None:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
