#!/usr/bin/env bash
# Provision Ubuntu/Debian dependencies, then install Dictate with the repo installer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

detect_session_backend() {
  if [ -n "${WAYLAND_DISPLAY:-}" ] || [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    printf 'wayland\n'
    return
  fi
  if [ -n "${DISPLAY:-}" ] || [ "${XDG_SESSION_TYPE:-}" = "x11" ]; then
    printf 'x11\n'
    return
  fi
  if [ -n "${XDG_SESSION_ID:-}" ] && command -v loginctl >/dev/null 2>&1; then
    local detected
    detected="$(loginctl show-session "$XDG_SESSION_ID" -p Type --value 2>/dev/null || true)"
    if [ "$detected" = "wayland" ] || [ "$detected" = "x11" ]; then
      printf '%s\n' "$detected"
      return
    fi
  fi
  printf 'unknown\n'
}

usage() {
  cat <<EOF
Usage: $0 [install.sh options]

Installs Ubuntu/Debian runtime packages required by Dictate, ensures uv is
available for the current user, then runs ./install.sh with any remaining args.
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer targets Ubuntu/Debian systems and requires apt-get."
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  SUDO=()
else
  if ! command -v sudo >/dev/null 2>&1; then
    echo "sudo is required to install Ubuntu packages."
    exit 1
  fi
  SUDO=(sudo)
fi

APT_PACKAGES=(
  ca-certificates
  curl
  desktop-file-utils
  gir1.2-ayatanaappindicator3-0.1
  libportaudio2
  libpulse0
  python3
  python3-gi
  python3-venv
  xclip
)

SESSION_BACKEND="$(detect_session_backend)"
echo "Detected install session backend: $SESSION_BACKEND"

if [ "$SESSION_BACKEND" = "wayland" ]; then
  APT_PACKAGES+=(
    libei1
    libportal1
    python3-evdev
    xdg-desktop-portal
    xdg-desktop-portal-gnome
    ydotool
  )
else
  APT_PACKAGES+=(
    xdotool
  )
fi

echo "Installing Ubuntu packages required by Dictate ..."
"${SUDO[@]}" apt-get update
"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PACKAGES[@]}"

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv for user $USER ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv was not found after installation. Ensure \$HOME/.local/bin is on PATH."
  exit 1
fi

"$SCRIPT_DIR/install.sh" --session-backend "$SESSION_BACKEND" "$@"
