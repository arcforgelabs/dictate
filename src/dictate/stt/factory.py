"""STT backend registry, creation, and lightweight readiness checks."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Callable

from dictate.stt.base import (
    ONNX_AMD_PROVIDERS,
    ComputeDevice,
    ComputeType,
    SpeechToText,
    SttBackend,
    SttCapabilities,
)
from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText
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
from dictate.stt.whisperx_backend import WhisperXSpeechToText, whisperx_available

def passthrough_blocks_cuda(pci_text: str) -> bool:
    """True when every NVIDIA display GPU is bound to vfio for a VM.

    An RTX 4090 handed to the Windows VM is not a free dictation device.
    Another NVIDIA GPU that is still on the nvidia driver stays usable.
    """
    blocks = [
        block
        for block in pci_text.split("\n\n")
        if "NVIDIA" in block and ("VGA" in block or "3D" in block)
    ]
    if not blocks:
        return False
    return all("vfio-pci" in block for block in blocks)


def device_for_host(device: str, pci_text: str) -> str:
    if device not in {"auto", "cuda"}:
        return device
    if passthrough_blocks_cuda(pci_text):
        return "cpu"
    return device


DEFAULT_MODELS: dict[SttBackend, str] = {
    "faster-whisper": "turbo",
    "parakeet": "parakeet-tdt-0.6b-v2",
    "parakeet-pyannote": "parakeet-tdt-0.6b-v2",
    "parakeet-diarizen": "parakeet-tdt-0.6b-v2",
    "parakeet-sortformer": "parakeet-tdt-0.6b-v2",
    "whisperx": "large-v3",
}
FASTER_WHISPER_MODELS: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "turbo",
    "large-v3-turbo",
    # English-only distil model: ~1 WER point better than turbo at the same speed.
    "distil-large-v3.5",
)
PARAKEET_MODELS: tuple[str, ...] = ("parakeet-tdt-0.6b-v2", "parakeet-tdt-0.6b-v3")
PARAKEET_PYANNOTE_MODELS: tuple[str, ...] = PARAKEET_MODELS
PARAKEET_DIARIZEN_MODELS: tuple[str, ...] = PARAKEET_MODELS
PARAKEET_SORTFORMER_MODELS: tuple[str, ...] = PARAKEET_MODELS
WHISPERX_MODELS: tuple[str, ...] = ("large-v3", "large-v3-turbo", "turbo")
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
    "parakeet-pyannote": BackendSpec(
        backend="parakeet-pyannote",
        default_model=DEFAULT_MODELS["parakeet-pyannote"],
        model_examples=PARAKEET_PYANNOTE_MODELS,
        description="Local Meeting backend: Parakeet ASR with pyannote Community-1 speakers.",
        capabilities=ParakeetPyannoteSpeechToText.capabilities,
        builder=lambda model, device, compute_type: ParakeetPyannoteSpeechToText(
            model_name=model,
            device=device,
            compute_type=compute_type,
        ),
    ),
    "parakeet-diarizen": BackendSpec(
        backend="parakeet-diarizen",
        default_model=DEFAULT_MODELS["parakeet-diarizen"],
        model_examples=PARAKEET_DIARIZEN_MODELS,
        description="Local Meeting backend: Parakeet ASR with DiariZen speaker attribution.",
        capabilities=ParakeetDiariZenSpeechToText.capabilities,
        builder=lambda model, device, compute_type: ParakeetDiariZenSpeechToText(
            model_name=model,
            device=device,
            compute_type=compute_type,
        ),
    ),
    "parakeet-sortformer": BackendSpec(
        backend="parakeet-sortformer",
        default_model=DEFAULT_MODELS["parakeet-sortformer"],
        model_examples=PARAKEET_SORTFORMER_MODELS,
        description="Local Meeting backend: Parakeet ASR with NVIDIA Sortformer speaker attribution.",
        capabilities=ParakeetSortformerSpeechToText.capabilities,
        builder=lambda model, device, compute_type: ParakeetSortformerSpeechToText(
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
    # device == "cpu"/"amd", or "auto" with no CUDA: gate turbo on machine capability.
    # faster-whisper does not have an AMD GPU runtime here; readiness blocks an
    # explicit AMD request before model load.
    cpu_count = os.cpu_count() or 0
    ram_bytes = _total_system_ram_bytes()
    if ram_bytes is None:
        # RAM unknown: fall back to a cpu-count-only heuristic; if that is also
        # unknown, stay conservative.
        return "turbo" if cpu_count >= _TURBO_MIN_CPU_COUNT else "small"
    if ram_bytes >= _TURBO_MIN_RAM_BYTES and cpu_count >= _TURBO_MIN_CPU_COUNT:
        return "turbo"
    return "small"


def resolve_default_local_backend(device: ComputeDevice = "auto") -> tuple[SttBackend, str]:
    """The default (backend, model) for a fresh local config on this machine.

    English-first: on CPU we default to Parakeet, which is both faster and more
    accurate than Whisper for English. CUDA and AMD also default to Parakeet
    when the runtime is importable; readiness/doctor then verifies that the
    requested accelerator provider actually exists instead of silently accepting
    CPU fallback. A saved config selection always wins over this default.
    """
    override = os.environ.get("DICTATE_FORCE_LOCAL_BACKEND")
    if override in {"parakeet", "faster-whisper"}:
        backend: SttBackend = override  # type: ignore[assignment]
        return backend, DEFAULT_MODELS[backend]
    if parakeet_available():
        return "parakeet", DEFAULT_MODELS["parakeet"]
    if device == "cuda" or (device == "auto" and _cuda_available_for_faster_whisper()):
        return "faster-whisper", "turbo"
    return "faster-whisper", resolve_default_local_model(device)


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
        if device == "amd":
            report.errors.append(
                "AMD GPU device requested for faster-whisper, but this backend only has "
                "CPU/CUDA coverage in Dictate. Use Parakeet for the AMD GPU lane."
            )
        if device in {"cuda", "auto"}:
            _check_cuda_with_ctranslate2(report, requested_device=device)

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
        if device in {"cuda", "auto"}:
            _check_cuda_with_onnxruntime(report, requested_device=device)
        if device == "amd":
            _check_amd_with_onnxruntime(report, requested_device=device)

    if backend == "parakeet-pyannote":
        _check_parakeet_pyannote(report, model_name=model_name, device=device)

    if backend == "parakeet-diarizen":
        _check_parakeet_diarizen(report, model_name=model_name, device=device)

    if backend == "parakeet-sortformer":
        _check_parakeet_sortformer(report, model_name=model_name, device=device)

    if backend == "whisperx":
        _check_whisperx(report, model_name=model_name, device=device)

    return report



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


def _check_parakeet_pyannote(
    report: BackendReadiness,
    *,
    model_name: str,
    device: ComputeDevice,
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
    if device in {"cuda", "auto", "amd"}:
        _check_cuda_with_torch(report, requested_device="auto" if device == "amd" else device)
        if device == "amd":
            report.warnings.append(
                "pyannote runs through PyTorch. On AMD, this requires a ROCm-enabled "
                "PyTorch build that reports availability through torch.cuda."
            )
    if device in {"cuda", "auto"}:
        _check_cuda_with_onnxruntime(report, requested_device=device)
    if device == "amd":
        _check_amd_with_onnxruntime(report, requested_device=device)


def _check_parakeet_diarizen(
    report: BackendReadiness,
    *,
    model_name: str,
    device: ComputeDevice,
) -> None:
    _check_parakeet_speaker_foundation(report, model_name=model_name, device=device, models=PARAKEET_DIARIZEN_MODELS)
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
    if device in {"cuda", "auto", "amd"}:
        _check_cuda_with_torch(report, requested_device="auto" if device == "amd" else device)
        if device == "amd":
            report.warnings.append(
                "DiariZen runs through PyTorch. On AMD, this requires a ROCm-enabled "
                "PyTorch build that reports availability through torch.cuda."
            )


def _check_parakeet_sortformer(
    report: BackendReadiness,
    *,
    model_name: str,
    device: ComputeDevice,
) -> None:
    _check_parakeet_speaker_foundation(report, model_name=model_name, device=device, models=PARAKEET_SORTFORMER_MODELS)
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
    if device in {"cuda", "auto", "amd"}:
        _check_cuda_with_torch(report, requested_device="auto" if device == "amd" else device)
        if device == "amd":
            report.warnings.append(
                "Sortformer runs through PyTorch. On AMD, this requires a ROCm-enabled "
                "PyTorch build that reports availability through torch.cuda."
            )


def _check_parakeet_speaker_foundation(
    report: BackendReadiness,
    *,
    model_name: str,
    device: ComputeDevice,
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
    if device in {"cuda", "auto"}:
        _check_cuda_with_onnxruntime(report, requested_device=device)
    if device == "amd":
        _check_amd_with_onnxruntime(report, requested_device=device)




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


def _check_amd_with_onnxruntime(
    report: BackendReadiness,
    *,
    requested_device: ComputeDevice,
) -> None:
    try:
        import onnxruntime as ort
    except Exception:  # noqa: BLE001
        if requested_device == "amd":
            report.errors.append(
                "AMD GPU device requested but onnxruntime is not importable."
            )
        return

    try:
        providers = tuple(str(provider) for provider in ort.get_available_providers())
    except Exception as exc:  # noqa: BLE001
        if requested_device == "amd":
            report.errors.append(f"Could not inspect ONNX Runtime execution providers: {exc}")
        return

    matched = tuple(provider for provider in ONNX_AMD_PROVIDERS if provider in providers)
    if matched:
        report.notes.append(f"ONNX Runtime AMD-capable provider detected: {matched[0]}")
        return

    if requested_device == "amd":
        report.errors.append(
            "AMD GPU device requested but ONNX Runtime has no AMD-capable execution "
            f"provider. Expected one of: {', '.join(ONNX_AMD_PROVIDERS)}. "
            "On Windows, install Dictate with the 'amd' extra for DirectML. On Linux, "
            "install a ROCm/MIGraphX-capable ONNX Runtime build before selecting "
            "--device amd."
        )
    elif providers:
        report.notes.append(
            "ONNX Runtime providers detected, but no AMD-capable provider is enabled: "
            + ", ".join(providers)
        )


def _check_cuda_with_onnxruntime(
    report: BackendReadiness,
    *,
    requested_device: ComputeDevice,
) -> None:
    try:
        import onnxruntime as ort
    except Exception:  # noqa: BLE001
        if requested_device == "cuda":
            report.errors.append(
                "CUDA device requested for Parakeet but onnxruntime is not importable."
            )
        return

    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        try:
            preload()
        except Exception as exc:  # noqa: BLE001
            if requested_device == "cuda":
                report.errors.append(f"Could not preload ONNX Runtime CUDA libraries: {exc}")
            return

    try:
        providers = tuple(str(provider) for provider in ort.get_available_providers())
    except Exception as exc:  # noqa: BLE001
        if requested_device == "cuda":
            report.errors.append(f"Could not inspect ONNX Runtime execution providers: {exc}")
        return

    if "CUDAExecutionProvider" in providers:
        report.notes.append("ONNX Runtime CUDA provider detected: CUDAExecutionProvider")
        return

    if requested_device == "cuda":
        report.errors.append(
            "CUDA device requested for Parakeet but ONNX Runtime has no CUDAExecutionProvider."
        )
    elif providers:
        report.notes.append(
            "ONNX Runtime providers detected, but CUDAExecutionProvider is not enabled: "
            + ", ".join(providers)
        )
