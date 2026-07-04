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
from pathlib import Path
from dataclasses import dataclass
from typing import Any

import numpy as np

from dictate.platform_paths import user_data_dir
from dictate.stt.base import (
    ONNX_AMD_PROVIDERS,
    ComputeDevice,
    ComputeType,
    SpeechToText,
    SttCapabilities,
)

logger = logging.getLogger(__name__)

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


def _ensure_model(model_name: str, quantization: str) -> Path:
    """Return a flat directory holding the Parakeet ONNX files, downloading once.

    Fetches each required file directly into a flat directory (real files, no
    symlinks) so onnxruntime can resolve the external weights regardless of its
    version's path checks. Idempotent: files already present are not re-fetched.
    """
    from huggingface_hub import hf_hub_download

    spec = _MODEL_SPECS[model_name]
    target = _model_dir(spec)
    target.mkdir(parents=True, exist_ok=True)
    files = _INT8_FILES if quantization == "int8" else _FP32_FILES
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


class ParakeetSpeechToText(SpeechToText):
    """English CPU transcription via NVIDIA Parakeet-TDT (onnx-asr)."""

    backend_name = "parakeet"
    capabilities = SttCapabilities(
        supports_hotwords=False,
        supports_prompt_bias=False,
        supports_language_hint=False,
        supports_word_timestamps=False,
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
        # Parakeet ONNX ships fp32 and int8; anything other than int8 loads fp32.
        self.compute_type = "int8" if compute_type == "int8" else "fp32"
        self._model: Any | None = None

    @property
    def model(self) -> Any:
        if self._model is None:
            import onnx_asr

            spec = _MODEL_SPECS[self.model_name]
            model_dir = _ensure_model(self.model_name, self.compute_type)
            providers = _providers_for_device(self.device)
            logger.info(
                "Loading Parakeet %s (%s) from %s on %s",
                self.model_name,
                self.compute_type,
                model_dir,
                self.device,
            )
            self._model = onnx_asr.load_model(
                spec.onnx_asr_name,
                str(model_dir),
                quantization=self.compute_type,
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

    def release(self) -> None:
        self._model = None
