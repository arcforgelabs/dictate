#!/usr/bin/env bash
# Update Dictate and migrate old launcher/icon names from previous installs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/dictate"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="$INSTALL_DIR/share/icons"

cleanup_legacy_entries() {
  rm -f "$DESKTOP_DIR/dictate-settings.desktop"
  rm -f "$ICON_DIR/dictate-controls.png" "$ICON_DIR/dictate.png"
}

if [ -d "$SCRIPT_DIR/.git" ]; then
  git -C "$SCRIPT_DIR" pull --ff-only
fi

cleanup_legacy_entries
"$SCRIPT_DIR/install.sh" "$@"
