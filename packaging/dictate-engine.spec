# PyInstaller spec for the frozen Dictate engine sidecar.
#
# Bundles the Python runtime + STT stack (faster-whisper / ctranslate2 /
# onnxruntime / av) plus the local Meeting runtime. The desktop builds stage
# Parakeet v2 int8 and pyannote Community-1 beside the engine so the default
# English ASR and Meeting mode do not need customer Hugging Face credentials.
#
# Two layouts, selected by DICTATE_ONEFILE:
#   - onedir (default): dist/dictate-engine/dictate-engine  — fast start; used
#     by the .deb/.rpm (their bundlers don't walk the engine's internal libs).
#   - onefile (DICTATE_ONEFILE=1): dist/dictate-engine  — a single self-extracting
#     binary, used by the AppImage so linuxdeploy sees one ELF, not the mangled
#     PyInstaller _internal/*.so tree it can't resolve.
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
for pkg in ("ctranslate2", "faster_whisper", "av", "onnxruntime", "tokenizers", "huggingface_hub"):
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

# Local Meeting backend runtime (pyannote Community-1 + torch). The model files
# are staged as Tauri resources by scripts/build-windows-desktop.ps1.
for pkg in ("torch", "torchaudio", "pyannote.audio", "pyannote.core", "pyannote.database", "pyannote.metrics"):
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
    excludes=["gi", "tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Analysis dependency walking can re-introduce host audio libs (_sounddevice →
# libportaudio, av.libs → libasound). Strip them again on Linux from both TOCs.
a.binaries = filter_pyinstaller_binaries(a.binaries)
a.datas = filter_pyinstaller_binaries(a.datas)

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
