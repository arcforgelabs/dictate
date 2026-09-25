#!/usr/bin/env bash
# Install a published Dictate Windows release in a Windows VM, launch it in the
# signed-in desktop session, check the running engine's version, and uninstall.
#
# This is the gate before a Microsoft Store draft: it exercises the exact
# setup.exe users download from GitHub Releases, not the source tree
# (scripts/windows-vm-smoke.sh covers the source tree).
set -euo pipefail

HOST="${DICTATE_WINDOWS_HOST:-win11-gpu}"
REPO="${DICTATE_REPO:-arcforgelabs/dictate}"
TAG=""
INSTALLER=""
TIMEOUT_SECONDS="300"
KEEP_GUEST_FILES=0
# The local SSH agent can stall waiting for an approval prompt; use the key
# file from ~/.ssh/config directly.
read -r -a SSH_OPTS <<<"${DICTATE_WINDOWS_SSH_OPTS:--o IdentityAgent=none -o BatchMode=yes -o ConnectTimeout=15}"

usage() {
  cat <<EOF
Usage: scripts/windows-vm-release-gate.sh [options]

Options:
  --tag <vYYYY.M.D[-N]>  Release to test. Default: the latest GitHub release.
  --installer <path>     Test a local *_x64-setup.exe instead of downloading.
                         Requires --tag so the expected version is known.
  --host <ssh-host>      Windows VM SSH host. Default: $HOST
  --timeout <seconds>    Wait for the app to come up. Default: $TIMEOUT_SECONDS
  --keep-guest-files     Leave the installer in the guest for inspection.
  -h, --help             Show this help

Checks, in the guest, as the signed-in user:
  1. Removes any existing Dictate install.
  2. Runs the NSIS installer silently (/S).
  3. The Installed Apps entry reports the expected version.
  4. Launches the app in the interactive desktop session.
  5. The engine's /api/health answers with the expected version.
  6. Uninstalls silently; the Installed Apps entry and the app are gone.

The guest must run OpenSSH Server, and the user must be signed in at the
console, because the app is a desktop window.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

say() {
  printf '==> %s\n' "$*"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tag) TAG="${2:-}"; shift 2 ;;
    --installer) INSTALLER="${2:-}"; shift 2 ;;
    --host) HOST="${2:-}"; shift 2 ;;
    --timeout) TIMEOUT_SECONDS="${2:-}"; shift 2 ;;
    --keep-guest-files) KEEP_GUEST_FILES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || die "--timeout must be numeric"
for cmd in ssh scp; do
  command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required"
done

if [ -n "$INSTALLER" ]; then
  [ -n "$TAG" ] || die "--installer needs --tag so the expected version is known"
  [ -f "$INSTALLER" ] || die "installer not found: $INSTALLER"
else
  command -v gh >/dev/null 2>&1 || die "gh is required to download the release"
  if [ -z "$TAG" ]; then
    TAG="$(gh release view -R "$REPO" --json tagName -q .tagName)"
  fi
fi
[[ "$TAG" =~ ^v20[0-9]{2}\.[0-9]{1,2}\.[0-9]{1,2}(-[0-9]+)?$ ]] \
  || die "tag must look like vYYYY.M.D or vYYYY.M.D-N: $TAG"
VERSION="${TAG#v}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# GitHub release downloads are capped per connection (about 0.15 MB/s at
# times), so fetch the installer as parallel byte ranges and check the
# SHA-256 GitHub publishes for the asset.
fetch_release_asset() {
  local name="$1" out="$2" parts=16 meta size digest url i start end
  meta="$(gh api "repos/$REPO/releases/tags/$TAG" \
    -q ".assets[] | select(.name == \"$name\") | \"\\(.size) \\(.digest)\"")"
  [ -n "$meta" ] || die "release $TAG has no $name"
  read -r size digest <<<"$meta"
  url="https://github.com/$REPO/releases/download/$TAG/$name"
  local chunk=$(( (size + parts - 1) / parts ))
  local pids=()
  for ((i = 0; i < parts; i++)); do
    start=$(( i * chunk ))
    end=$(( start + chunk - 1 ))
    [ "$end" -ge "$size" ] && end=$(( size - 1 ))
    curl -fsSL --retry 5 -r "$start-$end" -o "$out.part$i" "$url" &
    pids+=("$!")
  done
  for i in "${!pids[@]}"; do
    wait "${pids[$i]}" || die "download of $name part $i failed"
  done
  for ((i = 0; i < parts; i++)); do cat "$out.part$i"; done >"$out"
  rm -f "$out".part*
  [ "$(stat -c %s "$out")" = "$size" ] || die "$name is not $size bytes"
  if [ "${digest%%:*}" = "sha256" ]; then
    echo "${digest#sha256:}  $out" | sha256sum -c --quiet - || die "$name failed its SHA-256 check"
  fi
}

if [ -z "$INSTALLER" ]; then
  # Keep verified installers so a rerun does not download 800 MB again.
  CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/dictate-release-gate"
  mkdir -p "$CACHE_DIR"
  find "$CACHE_DIR" -name 'Dictate_*_x64-setup.exe' ! -name "Dictate_${VERSION}_x64-setup.exe" -delete
  INSTALLER="$CACHE_DIR/Dictate_${VERSION}_x64-setup.exe"
  if [ -f "$INSTALLER" ]; then
    say "Using the cached installer for $TAG"
  else
    say "Downloading the Windows installer for $TAG"
    fetch_release_asset "Dictate_${VERSION}_x64-setup.exe" "$INSTALLER.tmp"
    mv "$INSTALLER.tmp" "$INSTALLER"
  fi
fi

say "Checking SSH to $HOST"
ssh "${SSH_OPTS[@]}" "$HOST" "echo ok" >/dev/null \
  || die "cannot reach $HOST over SSH"

GUEST_DIR="dictate-release-gate"
GUEST_PS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/windows-release-gate.ps1"

say "Copying the installer and gate script to $HOST"
ssh "${SSH_OPTS[@]}" "$HOST" "if not exist $GUEST_DIR mkdir $GUEST_DIR" >/dev/null
scp -q "${SSH_OPTS[@]}" "$INSTALLER" "$GUEST_PS" "$HOST:$GUEST_DIR/"

say "Running the release gate for $VERSION on $HOST"
status=0
ssh "${SSH_OPTS[@]}" "$HOST" \
  "powershell -NoProfile -ExecutionPolicy Bypass -File $GUEST_DIR\\windows-release-gate.ps1 -Installer $GUEST_DIR\\$(basename "$INSTALLER") -ExpectedVersion $VERSION -TimeoutSeconds $TIMEOUT_SECONDS" \
  || status=$?

if [ "$KEEP_GUEST_FILES" -eq 0 ]; then
  ssh "${SSH_OPTS[@]}" "$HOST" "rmdir /s /q $GUEST_DIR" >/dev/null 2>&1 || true
fi

if [ "$status" -ne 0 ]; then
  die "Windows release gate failed for $VERSION on $HOST"
fi
say "Windows release gate passed for $VERSION on $HOST"
