# Windows 11 Support

Windows 11 is a supported desktop target for Dictate. The normal path is the
installed `Dictate` app entry, which starts the desktop capture app and tray
process. The primary workflow is simple dictation and local dictation recovery;
advanced configuration (model, meeting model, shortcut, hotwords, update
channel) lives in the `dictate config` CLI.

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

The signed, stable Windows channel is Microsoft Store distribution. A stable
Windows release means a Store package that we are happy to submit and support.
Direct stable and unstable installers are also supported and update independently
from GitHub release assets. Paid Authenticode signing for those assets is a future option only;
it is not a current release blocker or standing task. Early testers can use
staging MSI builds and accept the expected Windows untrusted-publisher warnings.

Direct MSI download:

1. Open the latest GitHub release.
2. Download `Dictate_*_x64_en-US.msi` when a staging MSI is attached.
3. Run the installer and open **Dictate** from the Start Menu.

Developer/source bootstrap from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"
```

Pre-stable developer/source bootstrap from the npm `unstable` channel:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@unstable/install.ps1 | iex"

Direct installs can choose Normal or Beta updates inside Dictate. Microsoft Store
installs show `Microsoft Store · Stable`; checking for updates opens the Store's
Downloads and updates surface and never switches to the direct-install ecosystem.

Transcription is local-only: there is no cloud lane, account, or API key on
Windows or anywhere else. See `VISION.md`.
```

The npm package is an installer shim that publishes the PowerShell lifecycle scripts. The hosted bootstrap downloads the matching tagged Dictate source release and runs the platform installer. It is a developer/bootstrap path, not the public Windows install target. If Node.js is already installed, this is equivalent:

```powershell
npx @arcforgelabs/dictate install
```

Use `npx @arcforgelabs/dictate@unstable install` or the `@unstable` CDN URL
only for pre-stable feature testing. Stable public promotion still goes through
CalVer release tags and the guarded Store/MSIX path.

From PowerShell in a repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
```

Windows setup wizard from a repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows-wizard.ps1
```

That command creates `.venv` with Python 3.11 or 3.12, installs Dictate with the Windows dependencies, installs the Microsoft Visual C++ runtime if it is missing, seeds `%APPDATA%\dictate\config.yaml`, writes launcher scripts, prepares the default Parakeet local model, runs `dictate doctor --quick`, registers Dictate in Installed Apps, adds a Start Menu shortcut named `Dictate`, and enables launch on startup by default.

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
scripts/windows-vm-smoke.sh --vm <your-windows-vm> --mode syntax
scripts/windows-vm-smoke.sh --vm <your-windows-vm> --mode install
scripts/windows-vm-smoke.sh --vm <your-windows-vm> --mode lifecycle
```

The VM smoke script uses libvirt `virsh qemu-agent-command`, so the Windows guest must have QEMU Guest Agent installed and running. It copies the source zip through QEMU Guest Agent file APIs, so guest-to-host networking is not required. `syntax` only parses the PowerShell scripts in Windows PowerShell. `install` resets Dictate app data in the guest, runs a no-shortcut install, compiles Python sources, runs focused tests, checks the version, verifies the fresh Parakeet default with `dictate doctor --quick`, and uninstalls. `lifecycle` adds update and post-update doctor/uninstall smoke checks.

GitHub-hosted Windows user smoke test:

```powershell
.\scripts\windows-user-smoke.ps1
```

This CI gate installs Dictate through the hosted developer bootstrap path from a deterministic source zip, verifies the Start Menu shortcut, default startup shortcut, Installed Apps registry entry, config seeding, `dictate --version`, `dictate doctor --quick`, `dictate doctor --fix`, hosted update, and uninstall cleanup. It does not test a real microphone, visible tray interaction, or Windows Search indexing.

Update or uninstall from a repo root:

```powershell
.\update-windows.ps1
.\uninstall-windows.ps1
```

Use `-RemoveUserData` with the uninstaller only when config, logs, history, and downloaded model data should also be removed.

The setup wizard links to Dictate documentation, the dedicated Dictate privacy policy at <https://arcforge.au/privacy/dictate>, and Arc Forge terms at <https://arcforge.au/terms>. Dictate is built to be useful, but support and maintenance are best-effort. Verify important transcriptions, report issues, and consider paid support if Dictate saves you time and you have the means.

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

Tray app:

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
- Startup shortcut: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Dictate.lnk`

## Desktop App

Open `Dictate` from the Start Menu. The desktop app includes:

- a capture home with a mic control
- a local dictations view for copy/paste recovery
- a command palette for daily actions
- a privacy pill stating that transcription stays on this device
- quiet update status when an app update is available

Advanced configuration remains available from PowerShell:

```powershell
.\.venv\Scripts\dictate.exe config show
.\.venv\Scripts\dictate.exe config set-model parakeet-tdt-0.6b-v3
.\.venv\Scripts\dictate.exe config set-shortcut ctrl_r
```

## Known Gaps

- Microsoft Store Submission 2 is staged with refreshed listing assets and is
  held until the next version package is bundled and tested.
- Global hotkey reliability depends on `pynput` permissions and the active desktop/session.
- NeMo Canary on Windows is not part of the supported baseline.
