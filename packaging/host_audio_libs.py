"""Host audio and oversized GPU libraries that must not be frozen on Linux.

Dictate captures audio through ``sounddevice`` → PortAudio. On Linux the .deb
already depends on distro ``libportaudio2`` (Pulse/PipeWire-aware). PyInstaller
still tends to collect a private ``libportaudio`` / ``libasound`` from the build
machine — often an ALSA-only build that defaults to raw ``hw:*`` devices and
rejects 16 kHz under modern PipeWire (seen on Ubuntu 26).

Default PyTorch wheels also pull CUDA/nvidia/triton trees that push the Linux
``.deb`` past GitHub's 2 GiB release-asset limit. Those stay out of the freeze
unless ``DICTATE_BUNDLE_GPU_LIBS=1``.

Windows keeps its bundled PortAudio DLLs: there is no equivalent system package
contract for the MSI/Store payloads.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import PurePosixPath

# Soname / basename prefixes collected from sounddevice, av.libs, and linker deps.
_LINUX_HOST_AUDIO_PREFIXES = (
    "libportaudio",
    "libasound",
    "libpulse",
    "libpulse-simple",
    "libpulsecommon",
)

# CUDA / ROCm / Triton trees must not ship in the default Linux .deb — they alone
# exceed GitHub's 2 GiB release asset limit. GPU users install optional extras.
_LINUX_HEAVY_RUNTIME_PREFIXES = (
    "nvidia",
    "triton",
    "cuda",
    "cudnn",
    "cublas",
    "cufft",
    "curand",
    "cusolver",
    "cusparse",
    "nvjitlink",
    "nccl",
)

_LINUX_HOST_AUDIO_RE = re.compile(
    r"^(?:lib)?(?:portaudio|asound|pulse(?:-simple|common)?)",
    re.IGNORECASE,
)


def should_exclude_host_audio_libs() -> bool:
    """True when the freeze must link against distro audio libraries."""
    return os.name != "nt" and not os.environ.get("DICTATE_BUNDLE_HOST_AUDIO")


def should_exclude_heavy_gpu_runtimes() -> bool:
    """True when CUDA/nvidia/triton trees must stay out of the Linux freeze."""
    return os.name != "nt" and not os.environ.get("DICTATE_BUNDLE_GPU_LIBS")


def is_host_audio_binary(name: str | os.PathLike[str]) -> bool:
    """Return True if *name* is a Linux host audio shared library basename/path."""
    basename = PurePosixPath(str(name).replace("\\", "/")).name
    if not basename:
        return False
    lower = basename.lower()
    if _LINUX_HOST_AUDIO_RE.match(lower):
        return True
    return any(lower.startswith(prefix) for prefix in _LINUX_HOST_AUDIO_PREFIXES)


def is_heavy_gpu_runtime_path(name: str | os.PathLike[str]) -> bool:
    """Return True if *name* is under a CUDA/nvidia/triton packaging tree."""
    text = str(name).replace("\\", "/").lower()
    parts = PurePosixPath(text).parts
    if any(part in _LINUX_HEAVY_RUNTIME_PREFIXES for part in parts):
        return True
    basename = PurePosixPath(text).name
    return any(basename.startswith(prefix) for prefix in _LINUX_HEAVY_RUNTIME_PREFIXES)


def filter_pyinstaller_toc(
    entries: Iterable[tuple],
    *,
    exclude_audio: bool | None = None,
    exclude_gpu: bool | None = None,
) -> list[tuple]:
    """Drop host-audio and oversized GPU runtime files from a PyInstaller TOC.

    Each item is typically ``(dest_name, src_path, typecode)``. ``collect_all``
    often places hashed ``av.libs/libasound-*.so`` entries in *datas*, not only
    in *binaries*, so both lists must be filtered.
    """
    if exclude_audio is None:
        exclude_audio = should_exclude_host_audio_libs()
    if exclude_gpu is None:
        exclude_gpu = should_exclude_heavy_gpu_runtimes()
    if not exclude_audio and not exclude_gpu:
        return list(entries)
    kept: list[tuple] = []
    for item in entries:
        name = item[0] if item else ""
        src = item[1] if len(item) > 1 else ""
        if exclude_audio and (is_host_audio_binary(name) or is_host_audio_binary(src)):
            continue
        if exclude_gpu and (is_heavy_gpu_runtime_path(name) or is_heavy_gpu_runtime_path(src)):
            continue
        kept.append(item)
    return kept


# Back-compat alias used by the PyInstaller spec.
filter_pyinstaller_binaries = filter_pyinstaller_toc
