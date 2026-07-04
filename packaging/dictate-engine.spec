# PyInstaller spec for the frozen Dictate engine sidecar.
#
# Bundles the Python runtime + STT stack (faster-whisper / ctranslate2 /
# onnxruntime / av). Models are NOT bundled — they download on first use.
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

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ONEFILE = os.environ.get("DICTATE_ONEFILE") == "1"

datas, binaries, hiddenimports = [], [], []

# The native-heavy packages PyInstaller's stock hooks don't fully capture.
for pkg in ("ctranslate2", "faster_whisper", "av", "onnxruntime", "tokenizers", "huggingface_hub"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Optional Linux-only AGC + noise suppression (webrtc-noise-gain). It is imported
# lazily and degrades gracefully, so only bundle it when it is actually installed.
try:
    import webrtc_noise_gain  # noqa: F401

    d, b, h = collect_all("webrtc_noise_gain")
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass

# Parakeet English backend runtime (onnx-asr + onnxruntime). Lazily imported and
# degrades gracefully; bundle when installed. Models download at first use.
for pkg in ("onnx_asr", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

# Our own package + its lazily-imported backends/dialogs.
hiddenimports += collect_submodules("dictate")
hiddenimports += [
    "sounddevice",
    "numpy",
    "yaml",
]

block_cipher = None

a = Analysis(
    ["engine_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # GUI toolkits the headless sidecar never needs — keep the binary lean.
    excludes=["gi", "tkinter", "torch", "matplotlib", "PyQt5", "PyQt6", "PySide6"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
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
        console=True,
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
        console=True,
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
