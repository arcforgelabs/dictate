"""Host audio libraries that must not be frozen into the Linux engine.

Dictate captures audio through ``sounddevice`` → PortAudio. On Linux the .deb
already depends on distro ``libportaudio2`` (Pulse/PipeWire-aware). PyInstaller
still tends to collect a private ``libportaudio`` / ``libasound`` from the build
machine — often an ALSA-only build that defaults to raw ``hw:*`` devices and
rejects 16 kHz under modern PipeWire (seen on Ubuntu 26).

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

_LINUX_HOST_AUDIO_RE = re.compile(
    r"^(?:lib)?(?:portaudio|asound|pulse(?:-simple|common)?)",
    re.IGNORECASE,
)


def should_exclude_host_audio_libs() -> bool:
    """True when the freeze must link against distro audio libraries."""
    return os.name != "nt" and not os.environ.get("DICTATE_BUNDLE_HOST_AUDIO")


def is_host_audio_binary(name: str | os.PathLike[str]) -> bool:
    """Return True if *name* is a Linux host audio shared library basename/path."""
    basename = PurePosixPath(str(name).replace("\\", "/")).name
    if not basename:
        return False
    lower = basename.lower()
    if _LINUX_HOST_AUDIO_RE.match(lower):
        return True
    return any(lower.startswith(prefix) for prefix in _LINUX_HOST_AUDIO_PREFIXES)


def filter_pyinstaller_toc(
    entries: Iterable[tuple],
    *,
    exclude: bool | None = None,
) -> list[tuple]:
    """Drop host audio shared libraries from a PyInstaller TOC (binaries or datas).

    Each item is typically ``(dest_name, src_path, typecode)``. ``collect_all``
    often places hashed ``av.libs/libasound-*.so`` entries in *datas*, not only
    in *binaries*, so both lists must be filtered.
    """
    if exclude is None:
        exclude = should_exclude_host_audio_libs()
    if not exclude:
        return list(entries)
    kept: list[tuple] = []
    for item in entries:
        name = item[0] if item else ""
        src = item[1] if len(item) > 1 else ""
        if is_host_audio_binary(name) or is_host_audio_binary(src):
            continue
        kept.append(item)
    return kept


# Back-compat alias used by the PyInstaller spec.
filter_pyinstaller_binaries = filter_pyinstaller_toc