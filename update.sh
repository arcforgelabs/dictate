#!/usr/bin/env bash
# Update Dictate and migrate old launcher/icon names from previous installs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/dictate"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
ICON_DIR="$INSTALL_DIR/share/icons"
AUTOSTART_PATH="$AUTOSTART_DIR/dictate.desktop"

cleanup_legacy_entries() {
  rm -f "$DESKTOP_DIR/dictate-settings.desktop"
  rm -f "$ICON_DIR/dictate-controls.png" "$ICON_DIR/dictate.png"
}

if [ -d "$SCRIPT_DIR/.git" ]; then
  git -C "$SCRIPT_DIR" pull --ff-only
fi

cleanup_legacy_entries

args=("$@")
startup_option_seen=0
for arg in "${args[@]}"; do
  if [ "$arg" = "--no-startup" ]; then
    startup_option_seen=1
  fi
done
if [ "$startup_option_seen" -eq 0 ] && [ ! -e "$AUTOSTART_PATH" ]; then
  args+=("--no-startup")
fi

"$SCRIPT_DIR/install.sh" "${args[@]}"
