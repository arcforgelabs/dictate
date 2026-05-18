#!/usr/bin/env bash
# Run Dictate Windows PowerShell smoke checks inside a local QEMU/KVM VM.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_NAME="win11-dev"
MODE="syntax"
TIMEOUT_SECONDS="900"
KEEP_GUEST_WORKDIR=0

usage() {
  cat <<EOF
Usage: scripts/windows-vm-smoke.sh [options]

Options:
  --vm <name>          libvirt/QEMU VM name. Default: win11-dev
  --mode <mode>        syntax, install, or lifecycle. Default: syntax
  --timeout <seconds>  Guest command timeout. Default: 900
  --keep-guest-workdir Leave %TEMP%\\dictate-vm-smoke in the guest for inspection
  -h, --help           Show this help

Modes:
  syntax     Parse Dictate .ps1 scripts inside Windows PowerShell.
  install    syntax + install-windows.ps1 smoke install, compile, focused tests.
  lifecycle  install + update-windows.ps1 and uninstall-windows.ps1 smoke checks.

Requires libvirt virsh access and QEMU Guest Agent running in the Windows VM.
The source zip is copied into the guest through QEMU Guest Agent file APIs, so
guest-to-host networking is not required.
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

say() {
  printf '==> %s\n' "$*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required"
}

ps_single_quote() {
  python3 - "$1" <<'PY'
import sys
print("'" + sys.argv[1].replace("'", "''") + "'")
PY
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --vm)
      VM_NAME="${2:-}"
      shift 2
      ;;
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --timeout)
      TIMEOUT_SECONDS="${2:-}"
      shift 2
      ;;
    --keep-guest-workdir)
      KEEP_GUEST_WORKDIR=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

case "$MODE" in
  syntax|install|lifecycle) ;;
  *) die "--mode must be syntax, install, or lifecycle" ;;
esac

need_cmd virsh
need_cmd python3

if ! [[ "$TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]; then
  die "--timeout must be numeric"
fi

make_source_zip() {
  local zip_path="$1"
  python3 - "$ROOT_DIR" "$zip_path" <<'PY'
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
zip_path = Path(sys.argv[2]).resolve()
excluded_dirs = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "build",
    "dist",
}
excluded_suffixes = {".pyc", ".pyo"}

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if name not in excluded_dirs and not name.endswith(".egg-info")
        ]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            if path.suffix in excluded_suffixes:
                continue
            rel = path.relative_to(root)
            archive.write(path, rel.as_posix())
PY
}

qga_upload_file() {
  local local_path="$1"
  local guest_path="$2"
  python3 - "$VM_NAME" "$local_path" "$guest_path" <<'PY'
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

vm_name = sys.argv[1]
local_path = Path(sys.argv[2])
guest_path = sys.argv[3]


def qga(payload: dict) -> dict:
    raw = subprocess.check_output(
        ["virsh", "qemu-agent-command", vm_name, json.dumps(payload)],
        text=True,
    )
    return json.loads(raw)


handle = qga({
    "execute": "guest-file-open",
    "arguments": {"path": guest_path, "mode": "wb"},
})["return"]
try:
    with local_path.open("rb") as fh:
        while True:
            chunk = fh.read(8192)
            if not chunk:
                break
            result = qga({
                "execute": "guest-file-write",
                "arguments": {
                    "handle": handle,
                    "buf-b64": base64.b64encode(chunk).decode("ascii"),
                    "count": len(chunk),
                },
            })["return"]
            if int(result.get("count", 0)) != len(chunk):
                raise RuntimeError(
                    f"short guest-file-write: {result.get('count')} of {len(chunk)} bytes"
                )
    qga({"execute": "guest-file-flush", "arguments": {"handle": handle}})
finally:
    qga({"execute": "guest-file-close", "arguments": {"handle": handle}})
PY
}

qga_exec_powershell() {
  local script_path="$1"
  local timeout_seconds="$2"
  local payload result pid deadline status status_file

  payload="$(python3 - "$script_path" <<'PY'
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

script = Path(sys.argv[1]).read_text(encoding="utf-8")
encoded = base64.b64encode(
    ("$ProgressPreference = 'SilentlyContinue'\n" + script).encode("utf-16le")
).decode("ascii")
print(json.dumps({
    "execute": "guest-exec",
    "arguments": {
        "path": "powershell.exe",
        "arg": [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        "capture-output": True,
    },
}))
PY
)"

  result="$(virsh qemu-agent-command "$VM_NAME" "$payload")"
  pid="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["return"]["pid"])' <<<"$result")"
  deadline=$((SECONDS + timeout_seconds))
  while [ "$SECONDS" -lt "$deadline" ]; do
    status="$(virsh qemu-agent-command "$VM_NAME" "{\"execute\":\"guest-exec-status\",\"arguments\":{\"pid\":$pid}}")"
    if python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin)["return"].get("exited") else 1)' <<<"$status"; then
      status_file="$(mktemp)"
      printf '%s' "$status" > "$status_file"
      python3 - "$status_file" <<'PY'
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
result = payload["return"]
for key, stream in (("out-data", sys.stdout), ("err-data", sys.stderr)):
    data = result.get(key)
    if data:
        stream.write(base64.b64decode(data).decode("utf-8", errors="replace"))
for key, stream in (("out-truncated", sys.stderr), ("err-truncated", sys.stderr)):
    if result.get(key):
        stream.write(f"\nwarning: QEMU guest agent {key} was set; output was truncated\n")
raise SystemExit(int(result.get("exitcode", 0)))
PY
      local exit_code=$?
      rm -f "$status_file"
      return "$exit_code"
    fi
    sleep 2
  done
  die "timed out waiting for Windows guest PowerShell command after ${timeout_seconds}s"
}

say "Checking QEMU Guest Agent on $VM_NAME"
virsh qemu-agent-command "$VM_NAME" '{"execute":"guest-ping"}' >/dev/null

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

ZIP_PATH="$TMP_DIR/dictate-smoke.zip"
say "Packing working tree"
make_source_zip "$ZIP_PATH"

GUEST_ZIP='C:\Windows\Temp\dictate-smoke.zip'
say "Copying source zip into $VM_NAME through QEMU Guest Agent"
qga_upload_file "$ZIP_PATH" "$GUEST_ZIP"

GUEST_PS="$TMP_DIR/dictate-windows-vm-smoke.ps1"
cat >"$GUEST_PS" <<EOF
\$ErrorActionPreference = 'Stop'
\$PSNativeCommandUseErrorActionPreference = \$false

function Invoke-Checked {
    param(
        [Parameter(Mandatory = \$true)][string] \$Description,
        [Parameter(Mandatory = \$true)][scriptblock] \$Script
    )
    Write-Output "==> \$Description"
    & \$Script
    if (\$LASTEXITCODE -ne 0) {
        throw "\$Description failed with exit code \$LASTEXITCODE"
    }
}

\$mode = $(ps_single_quote "$MODE")
\$guestZip = $(ps_single_quote "$GUEST_ZIP")
\$root = Join-Path \$env:TEMP 'dictate-vm-smoke'
\$source = Join-Path \$root 'source'

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue \$root
New-Item -ItemType Directory -Force -Path \$source | Out-Null

Write-Output "==> Expanding Dictate source from \$guestZip"
Expand-Archive -Force -Path \$guestZip -DestinationPath \$source
Set-Location \$source

Write-Output "==> PowerShell syntax parse"
\$scripts = @(
    'install.ps1',
    'install-windows.ps1',
    'install-windows-wizard.ps1',
    'update.ps1',
    'update-windows.ps1',
    'uninstall-windows.ps1',
    'scripts/windows-user-smoke.ps1'
)
foreach (\$script in \$scripts) {
    [scriptblock]::Create((Get-Content -Raw -Path \$script)) | Out-Null
    Write-Output "parsed \$script"
}

if (\$mode -in @('install', 'lifecycle')) {
    Invoke-Checked 'Install Dictate Windows smoke' {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\install-windows.ps1 -NoPrepareTurbo -NoVerify -NoShortcut -NoStartup
    }
    Invoke-Checked 'Compile Python sources' {
        & .\\.venv\\Scripts\\python.exe -m compileall -q src tests scripts
    }
    Invoke-Checked 'Run focused Windows platform tests' {
        & .\\.venv\\Scripts\\python.exe -m unittest tests.test_update_status tests.test_windows_platform
    }
    Invoke-Checked 'Show Dictate version' {
        & .\\.venv\\Scripts\\dictate.exe --version
    }
    if (\$mode -eq 'install') {
        Invoke-Checked 'Uninstall Dictate Windows smoke cleanup' {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\uninstall-windows.ps1 -Quiet
        }
    }
}

if (\$mode -eq 'lifecycle') {
    Invoke-Checked 'Update Dictate Windows smoke' {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\update-windows.ps1 -NoPrepareTurbo -NoVerify -NoShortcut -NoStartup -SkipGitPull
    }
    Invoke-Checked 'Doctor quick after update' {
        & .\\.venv\\Scripts\\dictate.exe doctor --quick --type-backend pynput
    }
    Invoke-Checked 'Uninstall Dictate Windows smoke' {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\uninstall-windows.ps1 -Quiet
    }
}

if ($KEEP_GUEST_WORKDIR -eq 0) {
    Set-Location \$env:TEMP
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue \$root
    Remove-Item -Force -ErrorAction SilentlyContinue \$guestZip
}

Write-Output "Dictate Windows VM smoke passed: \$mode"
EOF

say "Running Windows VM smoke mode: $MODE"
qga_exec_powershell "$GUEST_PS" "$TIMEOUT_SECONDS"
