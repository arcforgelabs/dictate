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

echo "▶ ensuring the Tauri CLI is available"
if ! npm --prefix ui-shell exec -- tauri --version >/dev/null 2>&1; then
  npm --prefix ui-shell install
fi

echo "▶ building the Tauri bundle (.deb + AppImage)"
( cd ui-shell && npm run tauri -- build --bundles deb,appimage )

echo
echo "✓ artifacts:"
find ui-shell/src-tauri/target/release/bundle -maxdepth 2 -type f \
  \( -name '*.deb' -o -name '*.AppImage' \) -print
