"""NVIDIA Parakeet-TDT backend (ONNX, CPU-friendly) via onnx-asr.

Parakeet-TDT-0.6b is an English transducer ASR model that, on CPU, is both
faster and more accurate than Whisper `small.en` (~6% WER vs ~8.5%, ~15-18x
real-time vs ~1x). It emits punctuation and casing directly and — being a
transducer — outputs a blank on silence instead of hallucinating filler like
"thanks for watching", which Whisper is prone to.

It runs through ``onnx-asr`` on top of ``onnxruntime`` (no NeMo/torch). Two
packaging quirks are handled here:

- **onnxruntime version**: the model uses ONNX external-data files; some
  onnxruntime releases (e.g. 1.24.1, and 1.27's strict external-data path check)
  fail to load HuggingFace's symlinked cache. We load from a **flat** model
  directory (real files, no symlinks) which avoids the check.
- **English only**: v2 is English-only; the factory keeps Whisper as the
  multilingual fallback.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dictate.platform_paths import user_data_dir
from dictate.stt.base import (
    ONNX_AMD_PROVIDERS,
    ComputeDevice,
    ComputeType,
    SpeechToText,
    SttCapabilities,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

PARAKEET_MODEL_PATH_ENV = "DICTATE_PARAKEET_MODEL_PATH"

@dataclass(frozen=True, slots=True)
class _ParakeetModelSpec:
    onnx_asr_name: str
    hf_repo: str
    model_dirname: str


_MODEL_SPECS: dict[str, _ParakeetModelSpec] = {
    "parakeet-tdt-0.6b-v2": _ParakeetModelSpec(
        onnx_asr_name="nemo-parakeet-tdt-0.6b-v2",
        hf_repo="istupakov/parakeet-tdt-0.6b-v2-onnx",
        model_dirname="parakeet-tdt-0.6b-v2-onnx",
    ),
    "parakeet-tdt-0.6b-v3": _ParakeetModelSpec(
        onnx_asr_name="nemo-parakeet-tdt-0.6b-v3",
        hf_repo="istupakov/parakeet-tdt-0.6b-v3-onnx",
        model_dirname="parakeet-tdt-0.6b-v3-onnx",
    ),
}


def parakeet_available() -> bool:
    """True if the onnx-asr runtime is importable."""
    try:
        import onnx_asr  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _model_dir(spec: _ParakeetModelSpec) -> Path:
    return user_data_dir() / "models" / spec.model_dirname


def _bundled_model_root() -> Path | None:
    raw_path = os.environ.get(PARAKEET_MODEL_PATH_ENV)
    if not raw_path:
        return None
    return Path(raw_path).expanduser()


# The exact ONNX files onnx-asr needs, per quantization. Downloaded individually
# (not via snapshot's symlinked cache) so onnxruntime can resolve them and so a
# stalled multi-file snapshot can't wedge the whole download.
_INT8_FILES = (
    "encoder-model.int8.onnx",
    "decoder_joint-model.int8.onnx",
    "nemo128.onnx",
    "config.json",
    "vocab.txt",
)
_FP32_FILES = (
    "encoder-model.onnx",
    "encoder-model.onnx.data",
    "decoder_joint-model.onnx",
    "nemo128.onnx",
    "config.json",
    "vocab.txt",
)


def _ensure_model(model_name: str, quantization: str | None) -> Path:
    """Return a flat directory holding the Parakeet ONNX files, downloading once.

    Fetches each required file directly into a flat directory (real files, no
    symlinks) so onnxruntime can resolve the external weights regardless of its
    version's path checks. Idempotent: files already present are not re-fetched.
    """
    spec = _MODEL_SPECS[model_name]
    files = _INT8_FILES if quantization == "int8" else _FP32_FILES
    if model_name == "parakeet-tdt-0.6b-v2" and quantization == "int8":
        bundled_root = _bundled_model_root()
        if bundled_root and _model_files_present(bundled_root, files):
            return bundled_root

    target = _model_dir(spec)
    target.mkdir(parents=True, exist_ok=True)
    if _model_files_present(target, files):
        return target

    _download_model_files(target, spec, files)
    return target


def _available_onnx_providers() -> tuple[str, ...]:
    import onnxruntime as ort

    return tuple(str(provider) for provider in ort.get_available_providers())


def _preload_cuda_dlls() -> None:
    import onnxruntime as ort

    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        preload()


def _providers_for_device(device: ComputeDevice) -> list[str] | None:
    if device == "auto":
        return None
    if device == "cpu":
        return ["CPUExecutionProvider"]

    if device == "cuda":
        _preload_cuda_dlls()
    available = _available_onnx_providers()
    if device == "cuda":
        if "CUDAExecutionProvider" not in available:
            raise RuntimeError(
                "Parakeet CUDA requested but ONNX Runtime does not expose CUDAExecutionProvider."
            )
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    if device == "amd":
        provider = next((name for name in ONNX_AMD_PROVIDERS if name in available), None)
        if provider is None:
            raise RuntimeError(
                "Parakeet AMD requested but ONNX Runtime does not expose an AMD-capable "
                f"execution provider. Expected one of: {', '.join(ONNX_AMD_PROVIDERS)}."
            )
        return [provider, "CPUExecutionProvider"]

    raise RuntimeError(f"Unsupported Parakeet device '{device}'.")


def _quantization_for_compute_type(compute_type: ComputeType) -> str | None:
    # onnx-asr accepts None for the plain fp32 files and "int8" for the int8
    # files. Passing "float16" makes it look for encoder-model?float16.onnx,
    # which the Parakeet ONNX repos do not publish.
    if compute_type == "float32":
        return None
    return "int8"


def _model_files_present(root: Path, files: tuple[str, ...]) -> bool:
    return all((root / name).is_file() and (root / name).stat().st_size > 0 for name in files)


def _download_model_files(target: Path, spec: _ParakeetModelSpec, files: tuple[str, ...]) -> None:
    from huggingface_hub import hf_hub_download

    for name in files:
        dest = target / name
        if dest.exists() and dest.stat().st_size > 0:
            continue
        hf_hub_download(
            spec.hf_repo,
            filename=name,
            local_dir=str(target),
            local_dir_use_symlinks=False,
        )


def prepare_parakeet_v2_int8_model(output: str | Path) -> Path:
    """Stage the bundled Parakeet v2 int8 runtime files into a flat directory."""
    target = Path(output).expanduser().resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    _download_model_files(target, _MODEL_SPECS["parakeet-tdt-0.6b-v2"], _INT8_FILES)
    return target


class ParakeetSpeechToText(SpeechToText):
    """English CPU transcription via NVIDIA Parakeet-TDT (onnx-asr)."""

    backend_name = "parakeet"
    capabilities = SttCapabilities(
        supports_hotwords=False,
        supports_prompt_bias=False,
        supports_language_hint=False,
        supports_word_timestamps=True,
        # Parakeet has no prompt input to carry context across chunks, so chunked
        # streaming mangles word boundaries. It's fast enough (~13x realtime) to
        # decode the whole utterance in one pass instead — higher quality, low tail.
        supports_streaming_chunks=False,
    )

    def __init__(
        self,
        model_name: str = "parakeet-tdt-0.6b-v2",
        device: ComputeDevice = "auto",
        compute_type: ComputeType = "int8",
    ):
        if model_name not in _MODEL_SPECS:
            raise ValueError(
                f"Parakeet model '{model_name}' is not wired in this runtime yet. "
                f"Supported today: {', '.join(_MODEL_SPECS)}."
            )
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.quantization = _quantization_for_compute_type(compute_type)
        self._model: Any | None = None

    @property
    def model(self) -> Any:
        if self._model is None:
            import onnx_asr

            spec = _MODEL_SPECS[self.model_name]
            model_dir = _ensure_model(self.model_name, self.quantization)
            providers = _providers_for_device(self.device)
            logger.info(
                "Loading Parakeet %s (%s) from %s on %s",
                self.model_name,
                self.quantization or "fp32",
                model_dir,
                self.device,
            )
            self._model = onnx_asr.load_model(
                spec.onnx_asr_name,
                str(model_dir),
                quantization=self.quantization,
                providers=providers,
            )
            logger.info("Parakeet model loaded")
        return self._model

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
        *,
        initial_prompt: str | None = None,
        long_form: bool = False,
    ) -> str:
        # Parakeet is English-only and takes no language/prompt/hotwords; lexicon
        # hotwords are applied as post-corrections by the engine layer.
        del language, hotwords, prompt_context, initial_prompt, long_form
        if audio.size == 0:
            return ""
        text = self.model.recognize(np.asarray(audio, dtype=np.float32))
        return (text or "").strip()

    def transcribe_segments(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
        *,
        initial_prompt: str | None = None,
        long_form: bool = False,
    ) -> list[TranscriptSegment]:
        del language, hotwords, prompt_context, initial_prompt, long_form
        if audio.size == 0:
            return []
        result = _recognize_timestamped(self.model, np.asarray(audio, dtype=np.float32))
        text = _timestamped_text(result)
        if not text:
            return []
        t_start, t_end = _timestamp_bounds(result, len(audio) / 16000.0)
        return [TranscriptSegment(text=text, t_start=t_start, t_end=t_end)]

    def release(self) -> None:
        self._model = None


def _recognize_timestamped(model: Any, audio: np.ndarray) -> Any:
    with_timestamps = getattr(model, "with_timestamps", None)
    if callable(with_timestamps):
        timestamped_model = with_timestamps()
        recognize = getattr(timestamped_model, "recognize", None)
        if callable(recognize):
            return recognize(audio)
    return model.recognize(audio)


def _timestamped_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text.strip()
    if isinstance(result, dict):
        value = result.get("text")
        if isinstance(value, str):
            return value.strip()
    return str(result or "").strip()


def _timestamp_bounds(result: Any, duration_s: float) -> tuple[float | None, float | None]:
    start = _optional_float(getattr(result, "start", None))
    end = _optional_float(getattr(result, "end", None))
    if isinstance(result, dict):
        start = _optional_float(result.get("start", result.get("t_start"))) if start is None else start
        end = _optional_float(result.get("end", result.get("t_end"))) if end is None else end
    timestamps = getattr(result, "timestamps", None)
    if timestamps is None and isinstance(result, dict):
        timestamps = result.get("timestamps")
    if start is None and isinstance(timestamps, list) and timestamps:
        start = _optional_float(timestamps[0])
    if end is None and isinstance(timestamps, list) and timestamps:
        end = _optional_float(timestamps[-1])
    if start is None:
        start = 0.0
    if end is None:
        end = duration_s
    return start, max(end, start)


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
