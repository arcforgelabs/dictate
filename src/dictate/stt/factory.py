"""STT backend registry, creation, and lightweight readiness checks."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from dictate.api_keys import API_BACKEND_LABELS, api_key_status
from dictate.stt.base import (
    ComputeDevice,
    ComputeType,
    SpeechToText,
    SttBackend,
    SttCapabilities,
)
from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText
from dictate.stt.gemini_backend import GeminiSpeechToText, gemini_api_key_available
from dictate.stt.openai_backend import OpenAISpeechToText, openai_api_key_available
from dictate.stt.whisperx_backend import WhisperXSpeechToText, whisperx_available
from dictate.stt.xai_backend import XAISpeechToText, xai_api_key_available

DEFAULT_MODELS: dict[SttBackend, str] = {
    "faster-whisper": "turbo",
    "whisperx": "large-v3",
    "openai": "gpt-4o-mini-transcribe",
    "xai": "grok-speech-to-text",
    "gemini": "gemini-3-flash-preview",
}
FASTER_WHISPER_MODELS: tuple[str, ...] = (
    "turbo",
)
WHISPERX_MODELS: tuple[str, ...] = ("large-v3", "large-v3-turbo", "turbo")
OPENAI_MODELS: tuple[str, ...] = (
    "gpt-4o-mini-transcribe",
    "gpt-4o-transcribe",
    "whisper-1",
)
XAI_MODELS: tuple[str, ...] = ("grok-speech-to-text",)
GEMINI_MODELS: tuple[str, ...] = ("gemini-3-flash-preview",)


@dataclass(frozen=True, slots=True)
class BackendSpec:
    backend: SttBackend
    default_model: str
    model_examples: tuple[str, ...]
    description: str
    capabilities: SttCapabilities
    builder: Callable[[str, ComputeDevice, ComputeType], SpeechToText]


BACKEND_REGISTRY: dict[SttBackend, BackendSpec] = {
    "faster-whisper": BackendSpec(
        backend="faster-whisper",
        default_model=DEFAULT_MODELS["faster-whisper"],
        model_examples=FASTER_WHISPER_MODELS,
        description="CTranslate2-optimized Whisper inference.",
        capabilities=FasterWhisperSpeechToText.capabilities,
        builder=lambda model, device, compute_type: FasterWhisperSpeechToText(
            model_name=model,
            device=device,
            compute_type=compute_type,
        ),
    ),
    "whisperx": BackendSpec(
        backend="whisperx",
        default_model=DEFAULT_MODELS["whisperx"],
        model_examples=WHISPERX_MODELS,
        description="Local WhisperX transcription, alignment, and pyannote diarization.",
        capabilities=WhisperXSpeechToText.capabilities,
        builder=lambda model, device, compute_type: WhisperXSpeechToText(
            model_name=model,
            device=device,
            compute_type=compute_type,
        ),
    ),
    "openai": BackendSpec(
        backend="openai",
        default_model=DEFAULT_MODELS["openai"],
        model_examples=OPENAI_MODELS,
        description="Hosted OpenAI Audio Transcriptions API.",
        capabilities=OpenAISpeechToText.capabilities,
        builder=lambda model, device, _compute_type: OpenAISpeechToText(
            model_name=model,
            device=device,
        ),
    ),
    "xai": BackendSpec(
        backend="xai",
        default_model=DEFAULT_MODELS["xai"],
        model_examples=XAI_MODELS,
        description="Hosted xAI Speech to Text API.",
        capabilities=XAISpeechToText.capabilities,
        builder=lambda model, device, _compute_type: XAISpeechToText(
            model_name=model,
            device=device,
        ),
    ),
    "gemini": BackendSpec(
        backend="gemini",
        default_model=DEFAULT_MODELS["gemini"],
        model_examples=GEMINI_MODELS,
        description="Hosted Gemini audio understanding transcription.",
        capabilities=GeminiSpeechToText.capabilities,
        builder=lambda model, device, _compute_type: GeminiSpeechToText(
            model_name=model,
            device=device,
        ),
    ),
}
STT_BACKENDS: tuple[SttBackend, ...] = tuple(BACKEND_REGISTRY.keys())


@dataclass(slots=True)
class BackendReadiness:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def resolve_model_name(backend: SttBackend, model: str | None = None) -> str:
    return model or BACKEND_REGISTRY[backend].default_model


def create_speech_to_text(
    *,
    backend: SttBackend = "faster-whisper",
    model: str | None = None,
    device: ComputeDevice = "auto",
    compute_type: ComputeType = "int8",
) -> SpeechToText:
    spec = BACKEND_REGISTRY[backend]
    model_name = resolve_model_name(backend, model)
    return spec.builder(model_name, device, compute_type)


def check_backend_readiness(
    *,
    backend: SttBackend,
    model: str | None,
    device: ComputeDevice,
) -> BackendReadiness:
    report = BackendReadiness()
    model_name = resolve_model_name(backend, model)
    report.notes.append(f"STT backend: {backend}")
    report.notes.append(f"STT model: {model_name}")

    if backend == "faster-whisper":
        try:
            import faster_whisper  # noqa: F401
        except Exception:  # noqa: BLE001
            report.errors.append("faster-whisper package is not importable.")
        if device in {"cuda", "auto"}:
            _check_cuda_with_ctranslate2(report, requested_device=device)

    if backend == "whisperx":
        _check_whisperx(report, model_name=model_name, device=device)

    if backend == "openai":
        _check_openai(report, model_name=model_name)

    if backend == "xai":
        _check_xai(report, model_name=model_name)

    if backend == "gemini":
        _check_gemini(report, model_name=model_name)

    return report


def _check_openai(report: BackendReadiness, *, model_name: str) -> None:
    if model_name not in OPENAI_MODELS:
        report.warnings.append(
            f"OpenAI STT model '{model_name}' is not one of the built-in examples."
        )
    status = api_key_status("openai", validate_remote=True)
    if status.ready:
        report.notes.append("OpenAI API key ready.")
    elif not openai_api_key_available():
        report.errors.append(
            "OpenAI backend selected but no API key is configured. "
            "Set DICTATE_OPENAI_API_KEY, OPENAI_API_KEY, or DICTATE_OPENAI_API_KEY_COMMAND."
        )
    else:
        report.errors.append(f"OpenAI API key status: {status.status}.")


def _check_whisperx(
    report: BackendReadiness,
    *,
    model_name: str,
    device: ComputeDevice,
) -> None:
    if model_name not in WHISPERX_MODELS:
        report.warnings.append(
            f"WhisperX model '{model_name}' is not one of the built-in examples."
        )
    if whisperx_available():
        report.notes.append("WhisperX package importable.")
    else:
        report.errors.append(
            'WhisperX package is not importable. Install with: uv pip install -e ".[whisperx]"'
        )
    if not any(
        os.environ.get(name)
        for name in ("DICTATE_HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "HF_TOKEN")
    ):
        report.warnings.append(
            "WhisperX diarization requires a Hugging Face token for pyannote models."
        )
    _check_cuda_with_torch(report, requested_device=device)


def _check_xai(report: BackendReadiness, *, model_name: str) -> None:
    if model_name not in XAI_MODELS:
        report.warnings.append(f"xAI STT model '{model_name}' is not one of the built-in examples.")
    status = api_key_status("xai", validate_remote=True)
    if status.ready:
        report.notes.append("xAI API key ready.")
    elif not xai_api_key_available():
        report.errors.append(
            "xAI backend selected but no API key is configured. "
            "Set DICTATE_XAI_API_KEY, XAI_API_KEY, or DICTATE_XAI_API_KEY_COMMAND."
        )
    else:
        report.errors.append(f"xAI API key status: {status.status}.")


def _check_gemini(report: BackendReadiness, *, model_name: str) -> None:
    if model_name not in GEMINI_MODELS:
        report.warnings.append(
            f"Gemini STT model '{model_name}' is not one of the built-in examples."
        )
    status = api_key_status("gemini", validate_remote=True)
    if status.ready:
        report.notes.append("Gemini API key ready.")
    elif not gemini_api_key_available():
        report.errors.append(
            "Gemini backend selected but no API key is configured. "
            "Set DICTATE_GEMINI_API_KEY, GEMINI_API_KEY, GOOGLE_API_KEY, "
            "or DICTATE_GEMINI_API_KEY_COMMAND."
        )
    else:
        label = API_BACKEND_LABELS["gemini"]
        report.errors.append(f"{label} API key status: {status.status}.")


def _check_cuda_with_torch(report: BackendReadiness, *, requested_device: ComputeDevice) -> None:
    try:
        import torch
    except Exception:  # noqa: BLE001
        report.warnings.append("PyTorch is not importable; skipping CUDA capability check.")
        return

    cuda_available = bool(torch.cuda.is_available())
    if requested_device == "cuda" and not cuda_available:
        report.errors.append("CUDA device requested but torch.cuda.is_available() is False.")
        return
    if requested_device == "auto" and not cuda_available:
        report.warnings.append(
            "CUDA is not available; backend will run on CPU if it supports CPU execution."
        )
        return

    if cuda_available:
        device_name = torch.cuda.get_device_name(0)
        report.notes.append(f"CUDA detected: {device_name}")


def _check_cuda_with_ctranslate2(
    report: BackendReadiness,
    *,
    requested_device: ComputeDevice,
) -> None:
    try:
        import ctranslate2
    except Exception:  # noqa: BLE001
        if requested_device == "cuda":
            report.errors.append("CUDA was requested but ctranslate2 is not importable.")
        return

    cuda_count = int(ctranslate2.get_cuda_device_count())
    if requested_device == "cuda" and cuda_count <= 0:
        report.errors.append("CUDA device requested but CTranslate2 reports zero CUDA devices.")
    elif requested_device == "auto" and cuda_count <= 0:
        report.warnings.append(
            "No CUDA devices detected by CTranslate2; faster-whisper will run on CPU."
        )
    elif cuda_count > 0:
        report.notes.append(f"CTranslate2 CUDA devices detected: {cuda_count}")
