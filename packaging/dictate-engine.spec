# PyInstaller spec for the frozen Dictate engine sidecar.
#
# Bundles the Python runtime + STT stack (onnx-asr / onnxruntime). The desktop
# builds stage Parakeet v2 int8 beside the engine so the default English ASR
# works offline from the first run.
#
# Two layouts, selected by DICTATE_ONEFILE:
#   - onedir (default): dist/dictate-engine/dictate-engine[.exe] + _internal/  —
#     starts without unpacking; used by the .deb/.rpm (their bundlers don't walk
#     the engine's internal libs) and by every Windows package (MSI, NSIS, Store
#     MSIX), which install the folder as is.
#   - onefile (DICTATE_ONEFILE=1): dist/dictate-engine  — a single self-extracting
#     binary, used only by the AppImage so linuxdeploy sees one ELF, not the
#     mangled PyInstaller _internal/*.so tree it can't resolve. It unpacks its
#     whole runtime into a temp dir on every launch, which costs seconds.
#
# Build:  pyinstaller packaging/dictate-engine.spec --noconfirm
# (the build script packaging/build-engine.sh wraps this with a clean venv)
#
# Linux host audio: do NOT freeze libportaudio / libasound / libpulse. The .deb
# depends on distro libportaudio2 (Pulse/PipeWire-aware). Bundling an ALSA-only
# PortAudio made Ubuntu 26 reject 16 kHz capture. Override with
# DICTATE_BUNDLE_HOST_AUDIO=1 only for deliberate AppImage experiments.

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# packaging/ sits beside this spec; import the shared filter helper.
sys.path.insert(0, SPECPATH)
from host_audio_libs import filter_pyinstaller_binaries  # noqa: E402

ONEFILE = os.environ.get("DICTATE_ONEFILE") == "1"
WINDOWED = os.name == "nt"

datas, binaries, hiddenimports = [], [], []

# The native-heavy packages PyInstaller's stock hooks don't fully capture.
for pkg in ("onnxruntime", "huggingface_hub"):
    d, b, h = collect_all(pkg)
    datas += filter_pyinstaller_binaries(d)
    binaries += filter_pyinstaller_binaries(b)
    hiddenimports += h

# Optional Linux-only AGC + noise suppression (webrtc-noise-gain). It is imported
# lazily and degrades gracefully, so only bundle it when it is actually installed.
try:
    import webrtc_noise_gain  # noqa: F401

    d, b, h = collect_all("webrtc_noise_gain")
    datas += filter_pyinstaller_binaries(d)
    binaries += filter_pyinstaller_binaries(b)
    hiddenimports += h
except Exception:
    pass

# Parakeet English backend runtime (onnx-asr + onnxruntime). Lazily imported and
# degrades gracefully; bundle when installed. Models download at first use.
for pkg in ("onnx_asr", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += filter_pyinstaller_binaries(d)
        binaries += filter_pyinstaller_binaries(b)
        hiddenimports += h
    except Exception:
        pass

# Our own package + its lazily-imported backends/dialogs.
hiddenimports += collect_submodules("dictate")
hiddenimports += [
    "sounddevice",
    "numpy",
    "yaml",
    # X11 hotkeys. Evdev is present for Wayland, but a normal desktop session
    # cannot read /dev/input, so the frozen engine must still contain pynput.
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
]
# pynput picks its backend with importlib at runtime, so PyInstaller never
# sees it. Name the backend for this platform, and its Xlib dependency on X11.
if sys.platform.startswith("linux"):
    hiddenimports += [
        "pynput._util.xorg",
        "pynput._util.xorg_keysyms",
        "pynput.keyboard._xorg",
        "pynput.mouse._xorg",
    ]
    hiddenimports += collect_submodules("Xlib")
elif os.name == "nt":
    hiddenimports += [
        "pynput._util.win32",
        "pynput._util.win32_vks",
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
    ]

block_cipher = None

a = Analysis(
    [os.path.join(SPECPATH, "engine_entry.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # GUI toolkits the headless sidecar never needs — keep the binary lean.
    # readline links GNU Readline (GPL-3.0) and is only for interactive shells.
    excludes=["gi", "tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6", "readline"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Analysis dependency walking can re-introduce host audio libs (_sounddevice →
# libportaudio). Strip them again on Linux from both TOCs.
a.binaries = filter_pyinstaller_binaries(a.binaries)
a.datas = filter_pyinstaller_binaries(a.datas)

# Windows installs the onedir folder file by file (MSI, NSIS, MSIX), so drop the
# build-time files collect_all() drags in: C/C++ headers, import/static
# libraries, CMake config and debug symbols. Nothing loads them at runtime.
# Linux builds are left as they are.
_BUILD_ONLY_SUFFIXES = (".h", ".hpp", ".hxx", ".cuh", ".inl", ".lib", ".a", ".cmake", ".pdb")


def _build_only_file(dest):
    parts = dest.replace("\\", "/").lower().split("/")
    return parts[-1].endswith(_BUILD_ONLY_SUFFIXES) or "include" in parts[:-1] or (
        "share" in parts[:-1] and "cmake" in parts[:-1]
    )


if os.name == "nt":
    _before = len(a.datas) + len(a.binaries)
    a.datas = [entry for entry in a.datas if not _build_only_file(entry[0])]
    a.binaries = [entry for entry in a.binaries if not _build_only_file(entry[0])]
    print(
        f"dictate-engine.spec: dropped {_before - len(a.datas) - len(a.binaries)} "
        "build-only files (headers, .lib, CMake, .pdb) from the Windows engine"
    )

# Removed runtimes. The Whisper family went first: faster-whisper, WhisperX,
# CTranslate2 and PyAV, whose FFmpeg build carried GPL libx264/libx265. Meeting
# capture followed (#140): pyannote and the torch stack it ran on. Fail the
# build if a transitive import brings any of them back, in either layout.
_REMOVED_PACKAGES = {
    "av", "ctranslate2", "faster_whisper", "whisperx",
    "torch", "torchaudio", "torchcodec", "pyannote",
}
_REMOVED_DIRS = _REMOVED_PACKAGES | {"av.libs", "ctranslate2.libs", "torch.libs", "torchcodec.libs"}
_REMOVED_LIBS = ("libx264", "libx265", "libtorch", "torch_cpu", "torch_python", "libc10", "c10.dll")


def _removed_file(dest):
    parts = dest.replace("\\", "/").split("/")
    name = parts[-1].lower()
    return parts[0] in _REMOVED_DIRS or name.startswith(_REMOVED_LIBS)


_found = sorted(
    {entry[0] for entry in a.pure if entry[0].split(".", 1)[0] in _REMOVED_PACKAGES}
    | {entry[0] for entry in list(a.binaries) + list(a.datas) if _removed_file(entry[0])}
)
if _found:
    raise SystemExit(
        "dictate-engine.spec: removed Whisper-family or Meeting runtime in the frozen engine: "
        + ", ".join(_found[:20])
    )
print(
    f"dictate-engine.spec: no av, ctranslate2, faster_whisper, whisperx, libx264, libx265, "
    f"torch, torchaudio, torchcodec or pyannote among {len(a.pure)} modules, "
    f"{len(a.binaries)} binaries, {len(a.datas)} data files"
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if ONEFILE:
    # Single self-extracting binary: dist/dictate-engine
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="dictate-engine",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=not WINDOWED,
    )
else:
    # onedir: dist/dictate-engine/dictate-engine + _internal/
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="dictate-engine",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=not WINDOWED,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="dictate-engine",
    )
