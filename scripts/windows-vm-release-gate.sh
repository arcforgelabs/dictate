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

if [ -z "$INSTALLER" ]; then
  say "Downloading the Windows installer for $TAG"
  gh release download "$TAG" -R "$REPO" -p "Dictate_${VERSION}_x64-setup.exe" -D "$TMP_DIR"
  INSTALLER="$TMP_DIR/Dictate_${VERSION}_x64-setup.exe"
  [ -f "$INSTALLER" ] || die "release $TAG has no Dictate_${VERSION}_x64-setup.exe"
fi

say "Checking SSH to $HOST"
ssh "${SSH_OPTS[@]}" "$HOST" "cmd /c ver" >/dev/null \
  || die "cannot reach $HOST over SSH"

GUEST_DIR="dictate-release-gate"
GUEST_PS="$TMP_DIR/release-gate.ps1"
cat >"$GUEST_PS" <<'PS'
param(
    [Parameter(Mandatory = $true)][string] $Installer,
    [Parameter(Mandatory = $true)][string] $ExpectedVersion,
    [int] $TimeoutSeconds = 300
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$taskName = 'DictateReleaseGate'
$handshake = Join-Path $env:LOCALAPPDATA 'dictate\ui-server.json'

function Step([string] $message) { Write-Output "==> $message" }

function Get-DictateEntry {
    $keys = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    Get-ItemProperty -Path $keys -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -eq 'Dictate' } |
        Select-Object -First 1
}

function Stop-Dictate {
    Get-Process -Name 'dictate-ui-shell', 'dictate-engine', 'Dictate' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

function Uninstall-Dictate($entry) {
    $command = [string] $entry.QuietUninstallString
    if (-not $command) { $command = [string] $entry.UninstallString }
    if (-not $command) { throw 'Dictate uninstall entry has no uninstall command' }
    $exe = if ($command -match '^"([^"]+)"') { $Matches[1] } else { ($command -split ' ')[0] }
    Start-Process -FilePath $exe -ArgumentList '/S' -Wait
    # NSIS copies its uninstaller to %TEMP% and returns early; wait for the
    # Installed Apps entry to disappear.
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-DictateEntry) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    if (Get-DictateEntry) { throw 'Dictate is still listed in Installed Apps after uninstall' }
}

function Remove-GateTask {
    schtasks.exe /Delete /TN $taskName /F 2>$null | Out-Null
}

try {
    Stop-Dictate
    $existing = Get-DictateEntry
    if ($existing) {
        Step "Removing existing Dictate $($existing.DisplayVersion)"
        Uninstall-Dictate $existing
    }
    Remove-Item -Force -ErrorAction SilentlyContinue $handshake

    Step "Installing $([IO.Path]::GetFileName($Installer)) silently"
    $install = Start-Process -FilePath $Installer -ArgumentList '/S' -Wait -PassThru
    if ($install.ExitCode -ne 0) { throw "installer exited with $($install.ExitCode)" }

    $entry = Get-DictateEntry
    if (-not $entry) { throw 'Dictate is not listed in Installed Apps after install' }
    if ($entry.DisplayVersion -ne $ExpectedVersion) {
        throw "Installed Apps reports $($entry.DisplayVersion), expected $ExpectedVersion"
    }
    Write-Output "Installed Apps: Dictate $($entry.DisplayVersion)"

    $installDir = [string] $entry.InstallLocation
    if (-not $installDir) {
        $uninstaller = [string] $entry.UninstallString
        if ($uninstaller -match '^"([^"]+)"') { $uninstaller = $Matches[1] }
        $installDir = Split-Path -Parent $uninstaller
    }
    $installDir = $installDir.Trim('"')
    $app = Get-ChildItem -Path $installDir -Filter '*.exe' -File |
        Where-Object { $_.Name -notmatch '^uninstall' } |
        Select-Object -First 1
    if (-not $app) { throw "no app executable in $installDir" }
    $engine = Get-ChildItem -Path $installDir -Recurse -Filter 'dictate-engine.exe' -File | Select-Object -First 1
    if (-not $engine) { throw "no dictate-engine.exe under $installDir" }
    Write-Output "App: $($app.FullName)"
    Write-Output "Engine: $($engine.FullName)"

    Step 'Launching Dictate in the signed-in desktop session'
    Remove-GateTask
    $run = '"' + $app.FullName + '"'
    schtasks.exe /Create /TN $taskName /TR $run /SC ONCE /ST 00:00 /IT /RL LIMITED /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'could not create the launch task' }
    schtasks.exe /Run /TN $taskName | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'could not run the launch task' }

    Step "Waiting up to ${TimeoutSeconds}s for the engine to answer"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $health = $null
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $handshake) {
            try {
                $url = ([Uri] (Get-Content -Raw $handshake | ConvertFrom-Json).url)
                $base = $url.GetLeftPart([UriPartial]::Authority)
                $health = Invoke-RestMethod -Uri "$base/api/health" -TimeoutSec 5
                if ($health.status -eq 'ok') { break }
            } catch {
                $health = $null
            }
        }
        Start-Sleep -Seconds 3
    }
    if (-not $health) {
        $running = (Get-Process -Name 'dictate-ui-shell', 'dictate-engine' -ErrorAction SilentlyContinue).Name -join ', '
        throw "engine did not answer /api/health within ${TimeoutSeconds}s (running: $running)"
    }
    if ($health.version -ne $ExpectedVersion) {
        throw "running engine reports $($health.version), expected $ExpectedVersion"
    }
    Write-Output "Engine /api/health: ok, version $($health.version)"
    foreach ($name in 'dictate-ui-shell', 'dictate-engine') {
        if (-not (Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            throw "$name is not running after launch"
        }
    }
    Write-Output 'Window and engine processes are running'

    Step 'Uninstalling'
    Stop-Dictate
    Remove-GateTask
    Uninstall-Dictate (Get-DictateEntry)
    if (Test-Path $app.FullName) { throw "$($app.FullName) is still present after uninstall" }
    Write-Output 'Uninstalled: Installed Apps entry and app executable are gone'

    Write-Output "Dictate Windows release gate passed: $ExpectedVersion"
} finally {
    Remove-GateTask
}
PS

say "Copying the installer and gate script to $HOST"
ssh "${SSH_OPTS[@]}" "$HOST" "cmd /c if not exist $GUEST_DIR mkdir $GUEST_DIR" >/dev/null
scp -q "${SSH_OPTS[@]}" "$INSTALLER" "$GUEST_PS" "$HOST:$GUEST_DIR/"

say "Running the release gate for $VERSION on $HOST"
status=0
ssh "${SSH_OPTS[@]}" "$HOST" \
  "powershell -NoProfile -ExecutionPolicy Bypass -File $GUEST_DIR\\release-gate.ps1 -Installer $GUEST_DIR\\$(basename "$INSTALLER") -ExpectedVersion $VERSION -TimeoutSeconds $TIMEOUT_SECONDS" \
  || status=$?

if [ "$KEEP_GUEST_FILES" -eq 0 ]; then
  ssh "${SSH_OPTS[@]}" "$HOST" "cmd /c rmdir /s /q $GUEST_DIR" >/dev/null 2>&1 || true
fi

if [ "$status" -ne 0 ]; then
  die "Windows release gate failed for $VERSION on $HOST"
fi
say "Windows release gate passed for $VERSION on $HOST"
