#!/usr/bin/env bash
# Install/update dictate into a standalone venv at ~/.local/share/dictate.
# Uses --system-site-packages so GTK/gi bindings are available.
# Re-run this script after pulling changes to update the installation.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/dictate"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
ICON_DIR="$INSTALL_DIR/share/icons"
ICON_PATH="$ICON_DIR/dictate-simple.png"
DESKTOP_PATH="$DESKTOP_DIR/dictate.desktop"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dictate"
CONFIG_PATH="$CONFIG_DIR/config.yaml"
DEFAULT_CONFIG_SOURCE="$SCRIPT_DIR/config/default-config.yaml"
VERIFY=1
PREPARE_TURBO=1
SEED_DEFAULT_CONFIG=1
STARTUP=1
INSTALL_UI=1
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Prefer the distro Python so --system-site-packages can see modules such as
# python3-gi from /usr/lib/python3/dist-packages.
if [ -x /usr/bin/python3 ]; then
  PYTHON_BIN="/usr/bin/python3"
fi

usage() {
  cat <<EOF
Usage: $0 [--no-verify] [--no-prepare-turbo] [--no-seed-default-config] [--no-startup] [--no-ui] [--session-backend auto|x11|wayland]

Installs dictate into ~/.local/share/dictate, links ~/.local/bin/dictate and
~/.local/bin/dictate-ui-server, seeds the default config on first install,
creates app launcher/autostart entries, prepares the faster-whisper turbo model,
and installs the desktop "Quiet Console" UI shell when a build toolchain is
present (unless disabled). All steps degrade gracefully when prerequisites are
missing.
EOF
}

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

SESSION_BACKEND="auto"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-verify)
      VERIFY=0
      ;;
    --no-prepare-turbo)
      PREPARE_TURBO=0
      ;;
    --no-seed-default-config)
      SEED_DEFAULT_CONFIG=0
      ;;
    --no-startup)
      STARTUP=0
      ;;
    --no-ui)
      INSTALL_UI=0
      ;;
    --session-backend)
      shift
      SESSION_BACKEND="${1:-}"
      ;;
    --session-backend=*)
      SESSION_BACKEND="${1#*=}"
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

if [ "$SESSION_BACKEND" = "auto" ]; then
  SESSION_BACKEND="$(detect_session_backend)"
fi

PIP_TARGET="$SCRIPT_DIR"
if [ "$SESSION_BACKEND" = "x11" ]; then
  PIP_TARGET="${SCRIPT_DIR}[x11]"
elif [ "$SESSION_BACKEND" = "wayland" ]; then
  PIP_TARGET="${SCRIPT_DIR}[wayland]"
elif [ "$SESSION_BACKEND" = "unknown" ]; then
  PIP_TARGET="${SCRIPT_DIR}[x11,wayland]"
fi

echo "Detected install session backend: $SESSION_BACKEND"

# The packaged build (.deb/.rpm) and this source install both ship a tray/daemon
# and would fight over the push-to-talk key. Warn rather than silently double up.
if command -v dpkg-query >/dev/null 2>&1 \
   && dpkg-query -W -f='${Status}' dictate 2>/dev/null | grep -q "install ok installed"; then
  echo "WARNING: a packaged Dictate (.deb) is already installed and would conflict."
  echo "  Use one install method. To remove the package first: sudo apt remove dictate"
elif command -v rpm >/dev/null 2>&1 && rpm -q dictate >/dev/null 2>&1; then
  echo "WARNING: a packaged Dictate (.rpm) is already installed and would conflict."
  echo "  Use one install method. To remove the package first: sudo dnf remove dictate"
fi

# Stop any running Dictate engine before we overwrite it, so the new install can
# claim the single-instance lock cleanly instead of colliding with a stale daemon.
stop_running_dictate() {
  # Prefer the installed CLI's own clean stop; it knows the lock location.
  if command -v dictate >/dev/null 2>&1 && dictate stop --quiet 2>/dev/null; then
    return 0
  fi
  # Fallback (older builds without `dictate stop`): kill via the lock PID file.
  local lockdir
  if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
    lockdir="$XDG_RUNTIME_DIR/dictate-daemon.lockdir"
  else
    lockdir="/tmp/dictate-daemon-$(id -u).lockdir"
  fi
  local pidfile="$lockdir/pid"
  [ -f "$pidfile" ] || return 0
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  [ -n "$pid" ] || return 0
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
    kill -9 "$pid" 2>/dev/null || true
  fi
}
echo "Stopping any running Dictate engine ..."
stop_running_dictate

echo "Creating venv at $INSTALL_DIR ..."
uv venv "$INSTALL_DIR/venv" --python "$PYTHON_BIN" --system-site-packages --quiet

echo "Installing dictate from $PIP_TARGET ..."
uv pip install "$PIP_TARGET" --python "$INSTALL_DIR/venv/bin/python" --quiet

echo "Linking binaries ..."
mkdir -p "$BIN_DIR"
ln -sf "$INSTALL_DIR/venv/bin/dictate" "$BIN_DIR/dictate"
# Expose the control server so the desktop shell can launch it on PATH.
ln -sf "$INSTALL_DIR/venv/bin/dictate-ui-server" "$BIN_DIR/dictate-ui-server"

echo "Installing icon ..."
mkdir -p "$ICON_DIR"
rm -f "$ICON_DIR/dictate-controls.png" "$ICON_DIR/dictate.png"
install -m 644 "$SCRIPT_DIR/assets/dictate.png" "$ICON_PATH"

echo "Installing desktop entry ..."
mkdir -p "$DESKTOP_DIR"
rm -f "$DESKTOP_DIR/dictate-settings.desktop" "$DESKTOP_DIR/Dictate.desktop" "$DESKTOP_DIR/dictate.desktop"
cat > "$DESKTOP_PATH" <<EOF
[Desktop Entry]
Name=Dictate
Comment=Dictate into the focused app
Exec=$HOME/.local/bin/dictate
Icon=$ICON_PATH
Type=Application
Categories=AudioVideo;Audio;
Keywords=voice;speech;transcription;dictation;asr;whisper;canary;
Terminal=false
EOF

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

if [ "$STARTUP" -eq 1 ]; then
  echo "Installing autostart entry ..."
  mkdir -p "$AUTOSTART_DIR"
  cat > "$AUTOSTART_DIR/dictate.desktop" <<EOF
[Desktop Entry]
Name=Dictate
Comment=Dictate into the focused app
Exec=$HOME/.local/bin/dictate
Icon=$ICON_PATH
Type=Application
Categories=AudioVideo;Audio;
Keywords=voice;speech;transcription;dictation;asr;whisper;canary;
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
fi

print_ui_hint() {
  cat <<EOF
  The Quiet Console desktop UI is optional — the tray app works without it
  (native dialogs as fallback). To add it later:
    - download a .deb / AppImage from the GitHub release, or
    - build it from this checkout: scripts/build-linux-desktop.sh
  See ui-shell/README.md for details.
EOF
}

install_desktop_ui() {
  local shell_src="$SCRIPT_DIR/ui-shell"
  local target="$BIN_DIR/dictate-ui-shell"

  if [ ! -d "$shell_src" ]; then
    echo "Desktop UI shell sources not present; skipping the optional UI."
    print_ui_hint
    return 0
  fi
  if ! command -v cargo >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1 \
     || ! pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
    echo "Desktop UI build toolchain not found (needs cargo, npm, webkit2gtk-4.1-dev)."
    print_ui_hint
    return 0
  fi

  echo "Building the desktop UI shell (this can take a few minutes) ..."
  npm --prefix "$SCRIPT_DIR/ui" ci >/dev/null 2>&1 \
    || npm --prefix "$SCRIPT_DIR/ui" install >/dev/null 2>&1 \
    || { echo "UI front-end install failed; skipping the optional shell."; print_ui_hint; return 0; }
  if ! npm --prefix "$SCRIPT_DIR/ui" run build >/dev/null 2>&1; then
    echo "UI front-end build failed; skipping the optional shell."; print_ui_hint; return 0
  fi
  if ! ( cd "$shell_src" && cargo build --release --manifest-path src-tauri/Cargo.toml ); then
    echo "Desktop UI shell build failed; the engine + tray remain fully functional."
    print_ui_hint
    return 0
  fi
  install -m 755 "$shell_src/src-tauri/target/release/dictate-ui-shell" "$target"
  echo "Installed desktop UI shell: $target"
}

if [ "$INSTALL_UI" -eq 1 ]; then
  install_desktop_ui
fi

if [ "$SEED_DEFAULT_CONFIG" -eq 1 ]; then
  if [ ! -f "$CONFIG_PATH" ]; then
    if [ ! -f "$DEFAULT_CONFIG_SOURCE" ]; then
      echo "Default config template not found: $DEFAULT_CONFIG_SOURCE"
      exit 1
    fi
    echo "Seeding default config at $CONFIG_PATH ..."
    mkdir -p "$CONFIG_DIR"
    install -m 600 "$DEFAULT_CONFIG_SOURCE" "$CONFIG_PATH"
    if [ "$SESSION_BACKEND" = "wayland" ]; then
      sed -i 's/^push_to_talk_combo: .*/push_to_talk_combo: ctrl+space/' "$CONFIG_PATH"
    fi
  else
    echo "Existing config found at $CONFIG_PATH; leaving it unchanged."
  fi
fi

DICTATE_BIN="$INSTALL_DIR/venv/bin/dictate"

run_logged_check() {
  local label="$1"
  local log_path="$2"
  local timeout_seconds="$3"
  shift 3
  echo "Running: $label ..."
  if command -v timeout >/dev/null 2>&1; then
    if ! timeout "${timeout_seconds}s" "$@" >"$log_path" 2>&1; then
      echo "Command failed: $label"
      echo "See: $log_path"
      tail -n 120 "$log_path" || true
      exit 1
    fi
  else
    if ! "$@" >"$log_path" 2>&1; then
      echo "Command failed: $label"
      echo "See: $log_path"
      tail -n 120 "$log_path" || true
      exit 1
    fi
  fi
}

if [ "$PREPARE_TURBO" -eq 1 ]; then
  PREPARE_LOG="/tmp/dictate-install-prepare.log"
  run_logged_check \
    "dictate prepare-model --stt-backend faster-whisper --model turbo --device auto --compute-type int8" \
    "$PREPARE_LOG" \
    1800 \
    "$DICTATE_BIN" \
    prepare-model \
    --stt-backend faster-whisper \
    --model turbo \
    --device auto \
    --compute-type int8
fi

if [ "$VERIFY" -eq 1 ]; then
  VERIFY_LOG="/tmp/dictate-install-verify.log"
  run_logged_check "dictate --help" "$VERIFY_LOG" 20 "$DICTATE_BIN" --help
  run_logged_check "dictate benchmark --help" "$VERIFY_LOG" 20 "$DICTATE_BIN" benchmark --help
  run_logged_check \
    "dictate doctor --quick --stt-backend faster-whisper --model turbo" \
    "$VERIFY_LOG" \
    20 \
    "$DICTATE_BIN" \
    doctor \
    --quick \
    --stt-backend faster-whisper \
    --model turbo
fi

if [ "$STARTUP" -eq 1 ]; then
  echo "Done. 'dictate' is now available on your PATH, in the app launcher, and starts when you sign in."
else
  echo "Done. 'dictate' is now available on your PATH and in the app launcher."
fi
