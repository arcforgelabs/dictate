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

RELIABLE=""
printf '%s' "$BUNDLES" | grep -q deb && RELIABLE="deb"
printf '%s' "$BUNDLES" | grep -q rpm && RELIABLE="${RELIABLE:+$RELIABLE,}rpm"

build_engine_and_stage() {
  local layout="$1"
  case "$layout" in
    onedir)
      echo "▶ freezing the Python engine sidecar (PyInstaller, onedir for native packages)"
      # deb/rpm can safely carry an onedir bundle. Avoiding onefile's giant archive
      # compression step keeps native package builds within normal workstation resources.
      unset DICTATE_ONEFILE
      ;;
    onefile)
      echo "▶ freezing the Python engine sidecar (PyInstaller, onefile for AppImage)"
      # linuxdeploy walks the AppDir and trips over PyInstaller's mangled native
      # libraries, so AppImage builds require a single self-extracting executable.
      export DICTATE_ONEFILE=1
      ;;
    *)
      echo "✗ unsupported engine layout: $layout" >&2
      return 1
      ;;
  esac
  ./packaging/build-engine.sh || return 1
  echo "▶ staging the engine into the Tauri bundle resources"
  mkdir -p ui-shell/src-tauri/engine || return 1
  rm -rf ui-shell/src-tauri/engine/dictate-engine ui-shell/src-tauri/engine/_internal || return 1
  if [ "$layout" = "onefile" ]; then
    cp packaging/dist/dictate-engine ui-shell/src-tauri/engine/dictate-engine || return 1
  else
    cp -a packaging/dist/dictate-engine/. ui-shell/src-tauri/engine/ || return 1
  fi
  chmod +x ui-shell/src-tauri/engine/dictate-engine || return 1
}

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

if [ -n "$RELIABLE" ] || ! printf '%s' "$BUNDLES" | grep -q appimage; then
  build_engine_and_stage onedir
fi

echo "▶ ensuring the Tauri CLI is available"
if ! npm --prefix ui-shell exec -- tauri --version >/dev/null 2>&1; then
  npm --prefix ui-shell install
fi

# .deb/.rpm are the reliable primary artifacts (their bundlers don't walk the
# engine's internal libs); the AppImage (linuxdeploy) is fussier, so build it
# best-effort and never let it sink the native packages.
if [ -n "$RELIABLE" ]; then
  echo "▶ building native packages ($RELIABLE)"
  ( cd ui-shell && npm run tauri -- build --bundles "$RELIABLE" )
fi
APPIMAGE_FAILED=0
if printf '%s' "$BUNDLES" | grep -q appimage; then
  if build_engine_and_stage onefile; then
    echo "▶ building the AppImage bundle (best-effort)"
    if ! ( cd ui-shell && npm run tauri -- build --bundles appimage --verbose ); then
      APPIMAGE_FAILED=1
      echo "⚠ AppImage bundling failed (linuxdeploy)" >&2
    fi
  else
    APPIMAGE_FAILED=1
    echo "⚠ AppImage preparation failed (PyInstaller)" >&2
  fi
  if [ "$APPIMAGE_FAILED" -ne 0 ]; then
    if [ -n "$RELIABLE" ]; then
      echo "⚠ AppImage lane failed; shipping native packages only"
    else
      echo "⚠ AppImage lane failed; no AppImage artifact was produced" >&2
    fi
  fi
fi

echo
echo "✓ artifacts:"
if [ -d ui-shell/src-tauri/target/release/bundle ]; then
  find ui-shell/src-tauri/target/release/bundle -maxdepth 2 -type f \
    \( -name '*.deb' -o -name '*.rpm' -o -name '*.AppImage' \) -print
fi
if [ "$APPIMAGE_FAILED" -ne 0 ] && [ -z "$RELIABLE" ]; then
  exit 1
fi
