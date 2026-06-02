#!/usr/bin/env bash
# Freeze the Dictate engine into a single self-contained directory bundle at
# packaging/dist/dictate-engine/ (launcher: .../dictate-engine). This is the
# Tauri sidecar embedded in the .deb / AppImage. Models are NOT bundled.
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
