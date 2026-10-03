#!/usr/bin/env bash
# Freeze the Dictate engine into a single self-contained directory bundle at
# packaging/dist/dictate-engine/ (launcher: .../dictate-engine). This is the
# Tauri sidecar embedded in the .deb / AppImage. The bundled Parakeet model is
# staged beside the engine under ui-shell/src-tauri/engine/models.
#
# Uses an isolated build venv so the freeze is reproducible and doesn't depend
# on the dev environment.
#
# Usage: packaging/build-engine.sh [python]
set -euo pipefail

PYTHON="${1:-python3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BUILD_VENV="$HERE/.build-venv"

echo "▶ creating isolated build venv"
if command -v uv >/dev/null 2>&1; then
  uv venv "$BUILD_VENV" --python "$PYTHON" --quiet
  VPY="$BUILD_VENV/bin/python"
  uv pip install --python "$VPY" -e "$ROOT[x11,wayland]" pyinstaller --quiet
else
  "$PYTHON" -m venv "$BUILD_VENV"
  VPY="$BUILD_VENV/bin/python"
  "$VPY" -m pip install --upgrade pip --quiet
  "$VPY" -m pip install -e "$ROOT[x11,wayland]" pyinstaller --quiet
fi

echo "▶ freezing the engine (PyInstaller${DICTATE_ONEFILE:+, onefile})"
rm -rf "$HERE/dist" "$HERE/build"
( cd "$HERE" && "$VPY" -m PyInstaller dictate-engine.spec --noconfirm \
    --distpath dist --workpath build --log-level WARN )

STAGE_DIR="$ROOT/ui-shell/src-tauri/engine"
echo "▶ staging bundled model resources"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
"$VPY" "$ROOT/scripts/prepare-parakeet-v2-int8-model.py" --output "$STAGE_DIR/models/parakeet-tdt-0.6b-v2-onnx"
echo "▶ staging third-party notices and model attributions"
"$VPY" "$ROOT/scripts/stage-notices.py" --engine-dir "$STAGE_DIR"

# onefile -> dist/dictate-engine ; onedir -> dist/dictate-engine/dictate-engine
if [ "${DICTATE_ONEFILE:-}" = "1" ]; then
  BIN="$HERE/dist/dictate-engine"
else
  BIN="$HERE/dist/dictate-engine/dictate-engine"
fi
[ -x "$BIN" ] || { echo "✗ freeze did not produce $BIN" >&2; exit 1; }

echo "▶ smoke-testing the frozen binary"
"$BIN" --version >/dev/null

# Linux .deb/.rpm must use distro PortAudio (Pulse/PipeWire-aware). A private
# libportaudio in _internal shadows libportaudio2 and breaks 16 kHz capture.
if [ "$(uname -s)" = "Linux" ] && [ -z "${DICTATE_BUNDLE_HOST_AUDIO:-}" ]; then
  ENGINE_DIR="$(cd "$(dirname "$BIN")" && pwd)"
  if find "$ENGINE_DIR" \( -name 'libportaudio*' -o -name 'libasound*' -o -name 'libpulse*' \) \
      ! -path '*/models/*' 2>/dev/null | grep -q .; then
    echo "✗ frozen engine still bundles host audio libs (portaudio/asound/pulse);" >&2
    echo "  Linux builds must link against distro libportaudio2. See packaging/host_audio_libs.py." >&2
    find "$ENGINE_DIR" \( -name 'libportaudio*' -o -name 'libasound*' -o -name 'libpulse*' \) \
      ! -path '*/models/*' 2>/dev/null | head -20 >&2
    exit 1
  fi
  echo "✓ host audio libs not bundled (using system libportaudio2)"
fi

if [ "$(uname -s)" = "Linux" ] && [ -z "${DICTATE_BUNDLE_GPU_LIBS:-}" ]; then
  ENGINE_DIR="$(cd "$(dirname "$BIN")" && pwd)"
  if find "$ENGINE_DIR" \( -path '*/nvidia/*' -o -path '*/triton/*' \) 2>/dev/null | grep -q .; then
    echo "✗ frozen engine still contains nvidia/triton trees;" >&2
    echo "  Nothing in the engine needs CUDA. See packaging/host_audio_libs.py." >&2
    exit 1
  fi
  echo "✓ nvidia/triton trees not bundled"
fi

# The Whisper-family runtimes and the Meeting runtime (torch, pyannote; #140)
# were removed. dictate-engine.spec already fails on them; this checks the
# files that actually landed (onedir: _internal/) and the staged models.
ENGINE_DIR="$(cd "$(dirname "$BIN")" && pwd)"
REMOVED_RUNTIME="$(find "$ENGINE_DIR" "$STAGE_DIR" \( -name 'av' -o -name 'av.libs' -o -name 'ctranslate2*' \
  -o -name 'faster_whisper*' -o -name 'whisperx*' -o -name 'libx264*' -o -name 'libx265*' \
  -o -name 'torch' -o -name 'torch.libs' -o -name 'torchaudio*' -o -name 'torchcodec*' \
  -o -name 'libtorch*' -o -name 'pyannote*' \) 2>/dev/null || true)"
if [ -n "$REMOVED_RUNTIME" ]; then
  echo "✗ frozen engine contains a removed Whisper-family or Meeting runtime:" >&2
  printf '%s\n' "$REMOVED_RUNTIME" | head -20 >&2
  exit 1
fi
echo "✓ no av, ctranslate2, faster_whisper, whisperx, libx264, libx265, torch, torchaudio, torchcodec or pyannote under $ENGINE_DIR or $STAGE_DIR ($(find "$ENGINE_DIR" -type f | wc -l) engine files)"

echo "✓ engine frozen: $BIN  ($(du -sh "$BIN" | cut -f1))"
