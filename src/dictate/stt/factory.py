"""STT backend registry, creation, and lightweight readiness checks."""

from __future__ import annotations

import os
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
from dictate.stt.parakeet_pyannote_backend import (
    PYANNOTE_COMMUNITY_MODEL,
    ParakeetPyannoteSpeechToText,
    pyannote_available,
    pyannote_model_source,
    pyannote_token,
)
from dictate.stt.parakeet_speaker_backend import (
    DIARIZEN_MODEL,
    SORTFORMER_MODEL,
    ParakeetDiariZenSpeechToText,
    ParakeetSortformerSpeechToText,
    diarizen_available,
    diarizen_model_source,
    sortformer_available,
    sortformer_model_source,
)


DEFAULT_MODELS: dict[SttBackend, str] = {
    "parakeet": "parakeet-tdt-0.6b-v2",
    "parakeet-pyannote": "parakeet-tdt-0.6b-v2",
    "parakeet-diarizen": "parakeet-tdt-0.6b-v2",
    "parakeet-sortformer": "parakeet-tdt-0.6b-v2",
}
PARAKEET_MODELS: tuple[str, ...] = ("parakeet-tdt-0.6b-v2", "parakeet-tdt-0.6b-v3")
PARAKEET_PYANNOTE_MODELS: tuple[str, ...] = PARAKEET_MODELS
PARAKEET_DIARIZEN_MODELS: tuple[str, ...] = PARAKEET_MODELS
PARAKEET_SORTFORMER_MODELS: tuple[str, ...] = PARAKEET_MODELS
DEFAULT_MEETING_BACKEND: SttBackend = "parakeet-pyannote"


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
    "parakeet-pyannote": BackendSpec(
        backend="parakeet-pyannote",
        default_model=DEFAULT_MODELS["parakeet-pyannote"],
        model_examples=PARAKEET_PYANNOTE_MODELS,
        description="Local Meeting backend: Parakeet ASR with pyannote Community-1 speakers.",
        capabilities=ParakeetPyannoteSpeechToText.capabilities,
        builder=lambda model, compute_type: ParakeetPyannoteSpeechToText(
            model_name=model,
            compute_type=compute_type,
        ),
    ),
    "parakeet-diarizen": BackendSpec(
        backend="parakeet-diarizen",
        default_model=DEFAULT_MODELS["parakeet-diarizen"],
        model_examples=PARAKEET_DIARIZEN_MODELS,
        description="Local Meeting backend: Parakeet ASR with DiariZen speaker attribution.",
        capabilities=ParakeetDiariZenSpeechToText.capabilities,
        builder=lambda model, compute_type: ParakeetDiariZenSpeechToText(
            model_name=model,
            compute_type=compute_type,
        ),
    ),
    "parakeet-sortformer": BackendSpec(
        backend="parakeet-sortformer",
        default_model=DEFAULT_MODELS["parakeet-sortformer"],
        model_examples=PARAKEET_SORTFORMER_MODELS,
        description="Local Meeting backend: Parakeet ASR with NVIDIA Sortformer speaker attribution.",
        capabilities=ParakeetSortformerSpeechToText.capabilities,
        builder=lambda model, compute_type: ParakeetSortformerSpeechToText(
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

    Configs written while GPU lanes existed can say ``float16``, which only
    meant something on a GPU (Parakeet already loaded int8 for it). Anything
    that is not a CPU compute type loads as int8.
    """
    if value in COMPUTE_TYPES:
        return value  # type: ignore[return-value]
    return "int8"


def saved_meeting_selection(backend: str | None, model: str | None) -> tuple[SttBackend, str]:
    """The Meeting backend/model from config.yaml, falling back to parakeet-pyannote."""
    saved_backend, saved_model = saved_stt_selection(
        backend, model, default_backend=DEFAULT_MEETING_BACKEND
    )
    if saved_backend is None:
        saved_backend = DEFAULT_MEETING_BACKEND
    return saved_backend, resolve_model_name(saved_backend, saved_model)


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

    if backend == "parakeet-pyannote":
        _check_parakeet_pyannote(report, model_name=model_name)

    if backend == "parakeet-diarizen":
        _check_parakeet_diarizen(report, model_name=model_name)

    if backend == "parakeet-sortformer":
        _check_parakeet_sortformer(report, model_name=model_name)

    return report


def _check_parakeet_pyannote(
    report: BackendReadiness,
    *,
    model_name: str,
) -> None:
    if model_name not in PARAKEET_PYANNOTE_MODELS:
        report.errors.append(
            f"Parakeet+pyannote model '{model_name}' is not one of the wired ASR models: "
            f"{', '.join(PARAKEET_PYANNOTE_MODELS)}."
        )
    if parakeet_available():
        report.notes.append("Parakeet (onnx-asr) importable.")
    else:
        report.errors.append(
            'Parakeet backend selected but onnx-asr is not importable. '
            'Install with: uv pip install "onnx-asr[cpu,hub]"'
        )
    if pyannote_available():
        report.notes.append("pyannote.audio importable.")
    else:
        report.errors.append(
            'pyannote.audio is not importable. Install with: uv pip install -e ".[meeting]"'
        )
    model_source = pyannote_model_source()
    if os.path.exists(os.path.expanduser(model_source)):
        report.notes.append(f"pyannote model path: {model_source}")
    elif not pyannote_token():
        report.errors.append(
            f"{PYANNOTE_COMMUNITY_MODEL} is gated. Accept the Hugging Face model terms, "
            "then set DICTATE_HF_TOKEN, HUGGINGFACE_HUB_TOKEN, or HF_TOKEN. For offline "
            "use, set DICTATE_PYANNOTE_MODEL_PATH to a local model checkout."
        )


def _check_parakeet_diarizen(
    report: BackendReadiness,
    *,
    model_name: str,
) -> None:
    _check_parakeet_speaker_foundation(report, model_name=model_name, models=PARAKEET_DIARIZEN_MODELS)
    if diarizen_available():
        report.notes.append("DiariZen runtime importable.")
    else:
        report.errors.append(
            "DiariZen Meeting backend selected but the diarizen runtime is not importable. "
            "Install DiariZen or set DICTATE_DIARIZEN_MODEL_PATH to a supported local checkout."
        )
    source = diarizen_model_source()
    if os.path.exists(os.path.expanduser(source)):
        report.notes.append(f"DiariZen model path: {source}")
    else:
        report.notes.append(f"DiariZen model: {source or DIARIZEN_MODEL}")


def _check_parakeet_sortformer(
    report: BackendReadiness,
    *,
    model_name: str,
) -> None:
    _check_parakeet_speaker_foundation(report, model_name=model_name, models=PARAKEET_SORTFORMER_MODELS)
    if sortformer_available():
        report.notes.append("NVIDIA NeMo ASR runtime importable.")
    else:
        report.errors.append(
            "NVIDIA Sortformer Meeting backend selected but NeMo ASR is not importable. "
            'Install the NeMo ASR runtime before selecting parakeet-sortformer.'
        )
    source = sortformer_model_source()
    if os.path.exists(os.path.expanduser(source)):
        report.notes.append(f"Sortformer model path: {source}")
    else:
        report.notes.append(f"Sortformer model: {source or SORTFORMER_MODEL}")


def _check_parakeet_speaker_foundation(
    report: BackendReadiness,
    *,
    model_name: str,
    models: tuple[str, ...],
) -> None:
    if model_name not in models:
        report.errors.append(
            f"Parakeet speaker-attribution ASR model '{model_name}' is not one of the wired models: "
            f"{', '.join(models)}."
        )
    if parakeet_available():
        report.notes.append("Parakeet (onnx-asr) importable.")
    else:
        report.errors.append(
            'Parakeet backend selected but onnx-asr is not importable. '
            'Install with: uv pip install "onnx-asr[cpu,hub]"'
        )
