"""STT backend registry, creation, and lightweight readiness checks."""

from __future__ import annotations

import os
import sys
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
from dictate.stt.parakeet_backend import ParakeetSpeechToText, parakeet_available
from dictate.stt.whisperx_backend import WhisperXSpeechToText, whisperx_available
from dictate.stt.xai_backend import XAISpeechToText, xai_api_key_available

DEFAULT_MODELS: dict[SttBackend, str] = {
    "faster-whisper": "turbo",
    "parakeet": "parakeet-tdt-0.6b-v2",
    "whisperx": "large-v3",
    "openai": "gpt-4o-mini-transcribe",
    "xai": "grok-speech-to-text",
    "gemini": "gemini-3-flash-preview",
}
FASTER_WHISPER_MODELS: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "turbo",
    "large-v3-turbo",
)
PARAKEET_MODELS: tuple[str, ...] = ("parakeet-tdt-0.6b-v2",)
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
    "parakeet": BackendSpec(
        backend="parakeet",
        default_model=DEFAULT_MODELS["parakeet"],
        model_examples=PARAKEET_MODELS,
        description="NVIDIA Parakeet-TDT English ASR via ONNX (fast, accurate on CPU).",
        capabilities=ParakeetSpeechToText.capabilities,
        builder=lambda model, device, compute_type: ParakeetSpeechToText(
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


# faster-whisper turbo (int8) needs ~1.5 GB resident; 8 GB total RAM is the
# documented minimum, so gate turbo on ~7.5 GB + a reasonably wide CPU. Weaker
# boxes fall back to "small" so a fresh CPU config never OOMs/swaps.
_TURBO_MIN_RAM_BYTES = int(7.5 * 1024**3)
_TURBO_MIN_CPU_COUNT = 8


def _cuda_available_for_faster_whisper() -> bool:
    """True when CTranslate2 reports at least one usable CUDA device."""
    try:
        import ctranslate2
    except Exception:  # noqa: BLE001
        return False
    try:
        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:  # noqa: BLE001
        return False


def _total_system_ram_bytes() -> int | None:
    """Best-effort cross-platform total physical RAM in bytes (no third-party deps).

    Returns ``None`` when detection is not possible, so callers can fall back to a
    conservative heuristic rather than guessing high and OOM-ing a weak machine.
    """
    # Linux and macOS expose physical pages via sysconf.
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        if page_size > 0 and phys_pages > 0:
            return int(page_size) * int(phys_pages)
    except (ValueError, OSError, AttributeError):
        pass
    # Linux fallback: parse /proc/meminfo MemTotal (kB).
    try:
        with open("/proc/meminfo", encoding="utf-8") as meminfo:
            for line in meminfo:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    # Windows: GlobalMemoryStatusEx via ctypes.
    if sys.platform.startswith("win"):
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys)
        except Exception:  # noqa: BLE001
            pass
    # macOS fallback (if sysconf was unavailable): sysctl hw.memsize.
    if sys.platform == "darwin":
        try:
            import subprocess

            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"])  # noqa: S603,S607
            return int(out.strip())
        except Exception:  # noqa: BLE001
            pass
    return None


def resolve_default_local_model(device: ComputeDevice = "auto") -> str:
    """Single hardware-aware default for the local (faster-whisper) model.

    This is the one place that decides turbo-vs-small so startup, tray reset,
    doctor, and the UI all agree. It is SEPARATE from ``resolve_model_name`` (the
    aspirational registry default) — an explicit saved config model still wins at
    the call sites, which pass ``model`` to ``resolve_model_name`` instead.
    """
    override = os.environ.get("DICTATE_FORCE_LOCAL_MODEL")
    if override:
        return override
    if device == "cuda":
        return "turbo"
    if device == "auto" and _cuda_available_for_faster_whisper():
        return "turbo"
    # device == "cpu", or "auto" with no CUDA: gate turbo on machine capability.
    cpu_count = os.cpu_count() or 0
    ram_bytes = _total_system_ram_bytes()
    if ram_bytes is None:
        # RAM unknown: fall back to a cpu-count-only heuristic; if that is also
        # unknown, stay conservative.
        return "turbo" if cpu_count >= _TURBO_MIN_CPU_COUNT else "small"
    if ram_bytes >= _TURBO_MIN_RAM_BYTES and cpu_count >= _TURBO_MIN_CPU_COUNT:
        return "turbo"
    return "small"


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

    if backend == "parakeet":
        if parakeet_available():
            report.notes.append("Parakeet (onnx-asr) importable.")
        else:
            report.errors.append(
                'Parakeet backend selected but onnx-asr is not importable. '
                'Install with: uv pip install "onnx-asr[cpu,hub]"'
            )

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
