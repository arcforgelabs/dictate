#!/usr/bin/env bash
# Build the Dictate desktop UI (Tauri shell) into installable Linux artifacts:
# a .deb and an AppImage under ui-shell/src-tauri/target/release/bundle/.
#
# Requires (one-time, needs root for the apt step):
#   sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev \
#       libayatana-appindicator3-dev librsvg2-dev build-essential \
#       curl wget file libssl-dev libxdo-dev
#   curl https://sh.rustup.rs -sSf | sh -s -- -y      # Rust toolchain
#
# Then just run:  scripts/build-linux-desktop.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Which bundle types to produce (deb,rpm,appimage). Override for a faster/leaner
# artifact, e.g. DICTATE_BUNDLES=deb scripts/build-linux-desktop.sh
BUNDLES="${DICTATE_BUNDLES:-deb,rpm,appimage}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "✗ missing '$1' — see the header of this script for setup."; exit 1; }; }

echo "▶ preflight"
need cargo
need npm
if ! pkg-config --exists webkit2gtk-4.1; then
  echo "✗ webkit2gtk-4.1 dev libraries not found."
  echo "  Install them: sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev \\"
  echo "      libayatana-appindicator3-dev librsvg2-dev libssl-dev libxdo-dev build-essential"
  exit 1
fi

echo "▶ building the front-end (ui/ -> dist/)"
npm --prefix ui ci 2>/dev/null || npm --prefix ui install
npm --prefix ui run build

echo "▶ freezing the Python engine sidecar (PyInstaller, onefile)"
# onefile: the AppDir then holds a single self-extracting binary, so linuxdeploy
# (AppImage) doesn't trip over PyInstaller's mangled _internal/*.so tree. The
# .deb/.rpm are happy with it too (one file instead of ~1200).
export DICTATE_ONEFILE=1
./packaging/build-engine.sh
echo "▶ staging the engine into the Tauri bundle resources"
rm -rf ui-shell/src-tauri/engine
mkdir -p ui-shell/src-tauri/engine
cp packaging/dist/dictate-engine ui-shell/src-tauri/engine/dictate-engine
chmod +x ui-shell/src-tauri/engine/dictate-engine

echo "▶ ensuring the Tauri CLI is available"
if ! npm --prefix ui-shell exec -- tauri --version >/dev/null 2>&1; then
  npm --prefix ui-shell install
fi

# .deb/.rpm are the reliable primary artifacts (their bundlers don't walk the
# engine's internal libs); the AppImage (linuxdeploy) is fussier, so build it
# best-effort and never let it sink the native packages.
RELIABLE=""
printf '%s' "$BUNDLES" | grep -q deb && RELIABLE="deb"
printf '%s' "$BUNDLES" | grep -q rpm && RELIABLE="${RELIABLE:+$RELIABLE,}rpm"
if [ -n "$RELIABLE" ]; then
  echo "▶ building native packages ($RELIABLE)"
  ( cd ui-shell && npm run tauri -- build --bundles "$RELIABLE" )
fi
if printf '%s' "$BUNDLES" | grep -q appimage; then
  echo "▶ building the AppImage bundle (best-effort)"
  ( cd ui-shell && npm run tauri -- build --bundles appimage --verbose ) \
    || echo "⚠ AppImage bundling failed (linuxdeploy); shipping native packages only"
fi

echo
echo "✓ artifacts:"
find ui-shell/src-tauri/target/release/bundle -maxdepth 2 -type f \
  \( -name '*.deb' -o -name '*.rpm' -o -name '*.AppImage' \) -print
