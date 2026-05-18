# Windows 11 Support

Windows 11 is supported as a separate runtime stream from the Linux tray build.

## Supported Surface

- Python 3.11 or 3.12.
- One-shot dictation: `dictate --once`.
- Clipboard output: `dictate --once --copy` through `pyperclip`.
- Push-to-talk tray app: `dictate --type-backend pynput`.
- Headless push-to-talk daemon: `dictate --no-tray --type-backend pynput`.
- Speech-to-text: `faster-whisper` on CPU or CUDA where the local Python/CUDA stack supports it.
- Local AMD GPU path: `whisper-cpp` with a Vulkan-enabled `whisper-server.exe` and `ggml-large-v3-turbo-q5_0.bin`.

The Windows tray uses the native notification area. The Linux GTK/Ayatana tray remains a separate implementation.

## Install

Hosted one-liner from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@iamsamuelrodda/dictate@latest/install.ps1 | iex"
```

The npm package is an installer shim that publishes the PowerShell lifecycle scripts. The hosted bootstrap downloads the matching tagged Dictate source release and runs the platform installer. If Node.js is already installed, this is equivalent:

```powershell
npx @iamsamuelrodda/dictate install
```

From PowerShell in a repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
```

Windows setup wizard from a repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows-wizard.ps1
```

That command creates `.venv` with Python 3.11 or 3.12, installs Dictate with the Windows dependencies, installs the Microsoft Visual C++ runtime if it is missing, seeds `%APPDATA%\dictate\config.yaml`, writes launcher scripts, prepares the default `faster-whisper/turbo` model, runs `dictate doctor --quick`, and adds a Start Menu shortcut named `Dictate`.

Skip model preparation or verification when needed:

```powershell
.\install-windows.ps1 -NoPrepareTurbo -NoVerify
```

CI/smoke-test install without a Start Menu shortcut:

```powershell
.\install-windows.ps1 -NoPrepareTurbo -NoVerify -NoShortcut
```

Host-driven QEMU/KVM VM smoke test from Linux:

```bash
scripts/windows-vm-smoke.sh --vm win11-dev --mode syntax
scripts/windows-vm-smoke.sh --vm win11-dev --mode install
scripts/windows-vm-smoke.sh --vm win11-dev --mode lifecycle
```

The VM smoke script uses libvirt `virsh qemu-agent-command`, so the Windows guest must have QEMU Guest Agent installed and running. It copies the source zip through QEMU Guest Agent file APIs, so guest-to-host networking is not required. `syntax` only parses the PowerShell scripts in Windows PowerShell. `install` also runs a no-model/no-shortcut install, focused tests, version check, and uninstall cleanup. `lifecycle` adds update and uninstall smoke checks.

GitHub-hosted Windows user smoke test:

```powershell
.\scripts\windows-user-smoke.ps1
```

This CI gate installs Dictate through the hosted bootstrap path from a deterministic source zip, verifies the Start Menu shortcut, default startup shortcut, Installed Apps registry entry, config seeding, `dictate --version`, `dictate doctor --quick`, `dictate doctor --fix`, hosted update, and uninstall cleanup. It does not test a real microphone, visible tray interaction, or Windows Search indexing.

Update or uninstall from a repo root:

```powershell
.\update-windows.ps1
.\uninstall-windows.ps1
```

Use `-RemoveUserData` with the uninstaller only when config, logs, history, and downloaded model data should also be removed.

The setup wizard links to Dictate documentation and Arc Forge terms at <https://arcforge.au/terms>. Dictate is built to be useful, but support and maintenance are best-effort. Verify important transcriptions, keep control of connected provider accounts, report issues, and consider paid support if Dictate saves you time and you have the means.

Manual install:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[windows]"
.\.venv\Scripts\dictate.exe doctor --quick --type-backend pynput
.\.venv\Scripts\dictate.exe doctor --quick --fix --type-backend pynput
.\.venv\Scripts\dictate.exe doctor --quick --update-paths --type-backend pynput
.\.venv\Scripts\dictate.exe doctor --quick --stt-backend whisper-cpp --model large-v3-turbo-q5_0 --type-backend pynput
```

## Run

Tray push-to-talk:

```powershell
.\.venv\Scripts\dictate-tray.cmd
```

Headless push-to-talk:

```powershell
.\.venv\Scripts\dictate-daemon.cmd
```

One-shot:

```powershell
.\.venv\Scripts\dictate-once.cmd
.\.venv\Scripts\dictate-once.cmd --copy
```

## Windows Paths

- Config: `%APPDATA%\dictate\config.yaml`
- History: `%LOCALAPPDATA%\dictate\recent-history.json`
- Logs: `%LOCALAPPDATA%\dictate\logs\`
- Fallback logs: `%TEMP%\dictate-logs\`
- Launchers: `.venv\Scripts\dictate-tray.cmd`, `.venv\Scripts\dictate-daemon.cmd`, `.venv\Scripts\dictate-once.cmd`, and `.venv\Scripts\dictate-controls.cmd`
- Start Menu shortcut: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Dictate.lnk`

## Known Gaps

- No signed Windows installer package yet; the repo-local PowerShell installer is the supported path for now.
- Global hotkey reliability depends on `pynput` permissions and the active desktop/session.
- NeMo Canary on Windows is not part of the supported baseline.
