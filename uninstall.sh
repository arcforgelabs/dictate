#!/usr/bin/env bash
# Remove Dictate launchers/autostart and installed runtime files.
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/dictate"
BIN_PATH="$HOME/.local/bin/dictate"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dictate"
REMOVE_USER_DATA=0
QUIET=0

usage() {
  cat <<EOF
Usage: $0 [--remove-user-data] [--quiet]

Removes Dictate launcher/autostart entries, ~/.local/bin/dictate, and the
installed runtime venv/icons. User config, logs, history, and downloaded models
are preserved unless --remove-user-data is passed.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --remove-user-data)
      REMOVE_USER_DATA=1
      ;;
    --quiet)
      QUIET=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 1
      ;;
  esac
  shift
done

say() {
  if [ "$QUIET" -eq 0 ]; then
    printf '%s\n' "$1"
  fi
}

remove_file() {
  local path="$1"
  if [ -e "$path" ] || [ -L "$path" ]; then
    rm -f "$path"
    say "Removed $path"
  fi
}

remove_dir_if_empty() {
  local path="$1"
  if [ -d "$path" ]; then
    rmdir "$path" 2>/dev/null || true
  fi
}

remove_file "$DESKTOP_DIR/dictate.desktop"
remove_file "$DESKTOP_DIR/dictate-settings.desktop"
remove_file "$AUTOSTART_DIR/dictate.desktop"

if [ -L "$BIN_PATH" ]; then
  target="$(readlink "$BIN_PATH" || true)"
  if [ "$target" = "$INSTALL_DIR/venv/bin/dictate" ]; then
    remove_file "$BIN_PATH"
  else
    say "Leaving $BIN_PATH because it points to $target"
  fi
elif [ -e "$BIN_PATH" ]; then
  say "Leaving $BIN_PATH because it is not a Dictate-managed symlink"
fi

rm -rf "$INSTALL_DIR/venv" "$INSTALL_DIR/share/icons"
remove_dir_if_empty "$INSTALL_DIR/share"
say "Removed installed runtime files from $INSTALL_DIR"

if [ "$REMOVE_USER_DATA" -eq 1 ]; then
  rm -rf "$CONFIG_DIR" "$INSTALL_DIR"
  say "Removed user config/data: $CONFIG_DIR and $INSTALL_DIR"
else
  say "Preserved user config/data: $CONFIG_DIR and $INSTALL_DIR"
fi

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

say "Dictate uninstall complete."
