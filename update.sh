#!/usr/bin/env bash
# Update Dictate and migrate old launcher/icon names from previous installs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/dictate"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
ICON_DIR="$INSTALL_DIR/share/icons"
AUTOSTART_PATH="$AUTOSTART_DIR/dictate.desktop"
UPDATE_SCOPE="user"

usage() {
  cat <<EOF
Usage: $0 [--user|--system] [install.sh options]

Default: --user.

--user updates the per-user install in ~/.local/share/dictate without sudo.
--system updates a Linux desktop package in system paths using apt/pkexec or sudo.
EOF
}

cleanup_legacy_entries() {
  rm -f "$DESKTOP_DIR/dictate-settings.desktop"
  rm -f "$ICON_DIR/dictate-controls.png" "$ICON_DIR/dictate.png"
}

args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --user)
      UPDATE_SCOPE="user"
      ;;
    --system)
      UPDATE_SCOPE="system"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      args+=("$1")
      ;;
  esac
  shift
done

if [ "$UPDATE_SCOPE" = "system" ]; then
  "$SCRIPT_DIR/install.sh" --system "${args[@]}"
  exit 0
fi

if [ -d "$SCRIPT_DIR/.git" ]; then
  git -C "$SCRIPT_DIR" pull --ff-only
fi

cleanup_legacy_entries

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
