#!/usr/bin/env bash
# Remove Dictate launchers/autostart and installed runtime files.
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/dictate"
BIN_PATH="$HOME/.local/bin/dictate"
UI_SERVER_BIN_PATH="$HOME/.local/bin/dictate-ui-server"
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

# Stop a running source-install daemon/server before pulling its venv out from
# under it (only our venv path is matched, never a packaged /usr install).
stop_source_processes() {
  local pattern="$INSTALL_DIR/venv"
  if command -v pkill >/dev/null 2>&1 && pgrep -f "$pattern" >/dev/null 2>&1; then
    say "Stopping running source-install Dictate processes ..."
    pkill -TERM -f "$pattern" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      pgrep -f "$pattern" >/dev/null 2>&1 || break
      sleep 0.3
    done
    pkill -KILL -f "$pattern" 2>/dev/null || true
  fi
}

remove_managed_symlink() {
  local link="$1" want="$2"
  if [ -L "$link" ]; then
    local target
    target="$(readlink "$link" || true)"
    if [ "$target" = "$want" ]; then
      remove_file "$link"
    else
      say "Leaving $link because it points to $target"
    fi
  elif [ -e "$link" ]; then
    say "Leaving $link because it is not a Dictate-managed symlink"
  fi
}

stop_source_processes

remove_file "$DESKTOP_DIR/dictate.desktop"
remove_file "$DESKTOP_DIR/Dictate.desktop"
remove_file "$DESKTOP_DIR/dictate-settings.desktop"
remove_file "$AUTOSTART_DIR/dictate.desktop"

remove_managed_symlink "$BIN_PATH" "$INSTALL_DIR/venv/bin/dictate"
remove_managed_symlink "$UI_SERVER_BIN_PATH" "$INSTALL_DIR/venv/bin/dictate-ui-server"

rm -rf "$INSTALL_DIR/venv" "$INSTALL_DIR/share/icons" "$INSTALL_DIR/logs"
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
