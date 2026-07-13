#!/usr/bin/env bash
# Freeze the Dictate engine into a single self-contained directory bundle at
# packaging/dist/dictate-engine/ (launcher: .../dictate-engine). This is the
# Tauri sidecar embedded in the .deb / AppImage. The desktop bundles stage the
# bundled local ASR / meeting model resources beside the engine separately.
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

if [ -z "${DICTATE_HF_TOKEN:-${HUGGINGFACE_HUB_TOKEN:-${HF_TOKEN:-}}}" ]; then
  echo "✗ staging pyannote Community-1 requires a Hugging Face token via DICTATE_HF_TOKEN, HUGGINGFACE_HUB_TOKEN, or HF_TOKEN" >&2
  exit 1
fi

echo "▶ creating isolated build venv"
if command -v uv >/dev/null 2>&1; then
  uv venv "$BUILD_VENV" --python "$PYTHON" --quiet
  VPY="$BUILD_VENV/bin/python"
  # Linux .deb must stay under GitHub's 2 GiB release-asset limit. Default
  # PyTorch wheels pull CUDA/nvidia/triton (~4+ GiB). Pin the CPU index first so
  # the meeting extra resolves against it.
  if [ "$(uname -s)" = "Linux" ]; then
    uv pip install --python "$VPY" torch --index-url https://download.pytorch.org/whl/cpu --quiet
  fi
  uv pip install --python "$VPY" -e "$ROOT[x11,wayland,meeting]" pyinstaller --quiet
else
  "$PYTHON" -m venv "$BUILD_VENV"
  VPY="$BUILD_VENV/bin/python"
  "$VPY" -m pip install --upgrade pip --quiet
  if [ "$(uname -s)" = "Linux" ]; then
    "$VPY" -m pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet
  fi
  "$VPY" -m pip install -e "$ROOT[x11,wayland,meeting]" pyinstaller --quiet
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
"$VPY" "$ROOT/scripts/prepare-pyannote-community-model.py" --output "$STAGE_DIR/models/pyannote-speaker-diarization-community-1"

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
    echo "  Linux builds must use CPU torch. See packaging/host_audio_libs.py." >&2
    exit 1
  fi
  echo "✓ nvidia/triton trees not bundled"
fi

echo "✓ engine frozen: $BIN  ($(du -sh "$BIN" | cut -f1))"
