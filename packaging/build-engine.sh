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
  uv pip install --python "$VPY" -e "$ROOT[x11,wayland,meeting]" pyinstaller --quiet
else
  "$PYTHON" -m venv "$BUILD_VENV"
  VPY="$BUILD_VENV/bin/python"
  "$VPY" -m pip install --upgrade pip --quiet
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
echo "✓ engine frozen: $BIN  ($(du -sh "$BIN" | cut -f1))"
