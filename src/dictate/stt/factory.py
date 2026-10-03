"""STT backend registry, creation, and lightweight readiness checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from dictate.stt.base import (
    COMPUTE_TYPES,
    ComputeType,
    SpeechToText,
    SttBackend,
    SttCapabilities,
)
from dictate.stt.parakeet_backend import ParakeetSpeechToText, parakeet_available


DEFAULT_MODELS: dict[SttBackend, str] = {
    "parakeet": "parakeet-tdt-0.6b-v2",
}
PARAKEET_MODELS: tuple[str, ...] = ("parakeet-tdt-0.6b-v2", "parakeet-tdt-0.6b-v3")


@dataclass(frozen=True, slots=True)
class BackendSpec:
    backend: SttBackend
    default_model: str
    model_examples: tuple[str, ...]
    description: str
    capabilities: SttCapabilities
    builder: Callable[[str, ComputeType], SpeechToText]


BACKEND_REGISTRY: dict[SttBackend, BackendSpec] = {
    "parakeet": BackendSpec(
        backend="parakeet",
        default_model=DEFAULT_MODELS["parakeet"],
        model_examples=PARAKEET_MODELS,
        description="NVIDIA Parakeet-TDT English ASR via ONNX (fast, accurate on CPU).",
        capabilities=ParakeetSpeechToText.capabilities,
        builder=lambda model, compute_type: ParakeetSpeechToText(
            model_name=model,
            compute_type=compute_type,
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


def resolve_default_local_backend() -> tuple[SttBackend, str]:
    """The default (backend, model) for a fresh local config.

    Parakeet on CPU is the only dictation backend. A saved config selection
    always wins over this default.
    """
    return "parakeet", DEFAULT_MODELS["parakeet"]


def saved_stt_selection(
    backend: str | None,
    model: str | None,
    *,
    default_backend: SttBackend = "parakeet",
) -> tuple[SttBackend | None, str | None]:
    """Validate a dictation backend/model pair read from config.yaml.

    Configs written before the Whisper backends were removed can still say
    ``faster-whisper`` or ``whisperx`` with a Whisper model such as ``turbo``
    (an unset backend used to mean faster-whisper too). Anything that is not a
    registered backend is treated as unset, and its model is dropped with it so
    a Whisper model name is never handed to Parakeet.

    The one exception is an unset backend with a Parakeet model, such as the
    ``stt_model: parakeet-tdt-0.6b-v3`` line ``config/default-config.yaml``
    offers for multilingual dictation. That model is kept, on
    ``default_backend``.
    """
    if backend in BACKEND_REGISTRY:
        return backend, model  # type: ignore[return-value]
    if not backend and model in PARAKEET_MODELS:
        return default_backend, model
    return None, None


def saved_compute_type(value: str | None) -> ComputeType:
    """The compute type from config.yaml, falling back to int8.

    ``load_config`` already moved a GPU-era ``float16`` to int8 on disk. This
    guards against anything else that is not a CPU compute type, such as a
    hand-edited typo, which also loads as int8.
    """
    if value in COMPUTE_TYPES:
        return value  # type: ignore[return-value]
    return "int8"


def create_speech_to_text(
    *,
    backend: SttBackend = "parakeet",
    model: str | None = None,
    compute_type: ComputeType = "int8",
) -> SpeechToText:
    spec = BACKEND_REGISTRY[backend]
    model_name = resolve_model_name(backend, model)
    return spec.builder(model_name, compute_type)


def check_backend_readiness(
    *,
    backend: SttBackend,
    model: str | None,
) -> BackendReadiness:
    report = BackendReadiness()
    model_name = resolve_model_name(backend, model)
    report.notes.append(f"STT backend: {backend}")
    report.notes.append(f"STT model: {model_name}")

    if backend == "parakeet":
        if model_name not in PARAKEET_MODELS:
            report.errors.append(
                f"Parakeet model '{model_name}' is not one of the wired models: "
                f"{', '.join(PARAKEET_MODELS)}."
            )
        if parakeet_available():
            report.notes.append("Parakeet (onnx-asr) importable.")
        else:
            report.errors.append(
                'Parakeet backend selected but onnx-asr is not importable. '
                'Install with: uv pip install "onnx-asr[cpu,hub]"'
            )

    return report
