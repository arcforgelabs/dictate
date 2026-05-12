"""STT backend registry, creation, and lightweight readiness checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from dictate.stt.base import (
    ComputeDevice,
    ComputeType,
    SpeechToText,
    SttBackend,
    SttCapabilities,
)
from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText
from dictate.stt.nemo_canary_backend import NeMoCanarySpeechToText
from dictate.stt.whisper_cpp_backend import (
    WhisperCppSpeechToText,
    resolve_whisper_cpp_server,
    resolve_whisper_cpp_model,
)

DEFAULT_MODELS: dict[SttBackend, str] = {
    "faster-whisper": "base",
    "nemo-canary": "nvidia/canary-1b-flash",
    "whisper-cpp": "large-v3-turbo-q5_0",
}
FASTER_WHISPER_MODELS: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "turbo",
    "large-v3-turbo",
)
NEMO_CANARY_MODELS: tuple[str, ...] = (
    "nvidia/canary-1b",
    "nvidia/canary-1b-flash",
    "nvidia/canary-1b-v2",
)
WHISPER_CPP_MODELS: tuple[str, ...] = (
    "base",
    "small",
    "turbo",
    "large-v3-turbo",
    "large-v3-turbo-q5_0",
    "large-v3-turbo-q8_0",
)


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
    "nemo-canary": BackendSpec(
        backend="nemo-canary",
        default_model=DEFAULT_MODELS["nemo-canary"],
        model_examples=NEMO_CANARY_MODELS,
        description="NVIDIA NeMo Canary multilingual ASR.",
        capabilities=NeMoCanarySpeechToText.capabilities,
        builder=lambda model, device, _compute_type: NeMoCanarySpeechToText(
            model_name=model,
            device=device,
        ),
    ),
    "whisper-cpp": BackendSpec(
        backend="whisper-cpp",
        default_model=DEFAULT_MODELS["whisper-cpp"],
        model_examples=WHISPER_CPP_MODELS,
        description="Local whisper.cpp CLI inference.",
        capabilities=WhisperCppSpeechToText.capabilities,
        builder=lambda model, device, _compute_type: WhisperCppSpeechToText(
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

    if backend == "nemo-canary":
        try:
            from nemo.collections import asr  # noqa: F401
        except Exception:  # noqa: BLE001
            report.errors.append(
                "NeMo backend selected but nemo_toolkit[asr] is missing. "
                "Install with: uv pip install -e \".[nemo]\""
            )
        if not model_name.startswith("nvidia/canary-"):
            report.warnings.append(
                "NeMo backend is tuned for Canary models; non-Canary model name may fail."
            )
        if device in {"cuda", "auto"}:
            _check_cuda_with_torch(report, requested_device=device)

    if backend == "faster-whisper":
        try:
            import faster_whisper  # noqa: F401
        except Exception:  # noqa: BLE001
            report.errors.append("faster-whisper package is not importable.")
        if device in {"cuda", "auto"}:
            _check_cuda_with_ctranslate2(report, requested_device=device)

    if backend == "whisper-cpp":
        _check_whisper_cpp(report, model_name=model_name)

    if device == "cpu" and backend == "nemo-canary":
        report.warnings.append(
            "NeMo Canary on CPU is likely too slow for push-to-talk dictation."
        )

    return report


def _check_whisper_cpp(report: BackendReadiness, *, model_name: str) -> None:
    server_path = resolve_whisper_cpp_server()
    model_path = resolve_whisper_cpp_model(model_name)
    if server_path.is_file():
        report.notes.append(f"whisper.cpp server: {server_path}")
    else:
        report.errors.append(f"whisper.cpp server executable not found: {server_path}")
    if model_path.is_file():
        report.notes.append(f"whisper.cpp model: {model_path}")
    else:
        report.errors.append(f"whisper.cpp model not found: {model_path}")


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


def _check_cuda_with_ctranslate2(report: BackendReadiness, *, requested_device: ComputeDevice) -> None:
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
