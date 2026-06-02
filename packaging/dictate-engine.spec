# PyInstaller spec for the frozen Dictate engine sidecar.
#
# Produces a single self-contained `dictate-engine` binary (onedir under
# dist/dictate-engine/) bundling the Python runtime + the STT stack
# (faster-whisper / ctranslate2 / onnxruntime / av). Models are NOT bundled —
# they download on first use, exactly as in a normal install.
#
# Build:  pyinstaller packaging/dictate-engine.spec --noconfirm
# (the build script packaging/build-engine.sh wraps this with a clean venv)

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# The native-heavy packages PyInstaller's stock hooks don't fully capture.
for pkg in ("ctranslate2", "faster_whisper", "av", "onnxruntime", "tokenizers", "huggingface_hub"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

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
