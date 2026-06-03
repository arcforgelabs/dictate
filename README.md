# 🎙️ Dictate

Desktop dictation that types into the focused app.

`dictate` runs as a small tray app. Press your configured push-to-talk shortcut,
speak, and it transcribes into whatever app you are already using.

Current status: early desktop app. Linux installs, Windows 11 source installs,
tray controls, startup integration, recent history, model selection, API key
storage, update, and uninstall paths are implemented. Windows Store/signed
installer packaging is being prepared; see `docs/goal.md`.

## Install

Windows 11 normal install:

The target public channel is Microsoft Store distribution. Until that listing is
ready, use the GitHub release installer artifacts for internal validation only.
The PowerShell bootstrap installer below is a developer/source path, not the
normal public install route.

Windows developer/source install from the hosted bootstrap:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"
```

Open **Dictate** from the Start Menu after install.

Ubuntu/Debian source install:

```bash
./install-ubuntu.sh
```

Generic Linux source install:

```bash
./install.sh
```

Open **Dictate** from the app launcher after install.

Windows developer/source install, from the repo/source directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows-wizard.ps1
```

The local `.ps1` installer scripts must be run from a checkout or extracted
source directory. They will not work from `C:\Windows\System32`.

Node/npm users can also run the developer bootstrap:

```powershell
npx @arcforgelabs/dictate install
```

## Workflow

```text
Open Dictate
Select Model
Set API key if using a hosted model
Set push-to-talk shortcut if desired
Hold shortcut, speak, release
Review Recent History when needed
```

By default, Dictate installs a normal app launcher entry and starts on sign-in.
Startup can be changed from Settings.

## Update And Uninstall

Windows developer/bootstrap install:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/update.ps1 | iex"
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/uninstall.ps1 | iex"
```

Windows from source:

```powershell
powershell -ExecutionPolicy Bypass -File .\update-windows.ps1
powershell -ExecutionPolicy Bypass -File .\uninstall-windows.ps1
```

Linux:

```bash
./update.sh
./uninstall.sh
```

Use `-RemoveUserData` on Windows or `--remove-user-data` on Linux only when you
also want to remove config, logs, history, and downloaded model data.

## What It Does Today

- Starts from the Windows Start Menu or Linux app launcher
- Runs as a tray app
- Types dictated text into the focused app
- Supports configurable push-to-talk
- Shows selected model/status in the app UI
- Supports launch on startup
- Stores hosted-provider API keys in the OS secret store
- Keeps a small Recent History for copy/paste recovery
- Provides installer, updater, uninstaller, and doctor paths

## Models

Supported provider defaults:

- `faster-whisper/turbo` for local transcription
- `openai/gpt-4o-mini-transcribe`
- `xai/grok-speech-to-text`
- `gemini/gemini-3-flash-preview`

Local transcription can use CPU or GPU where supported. Hosted providers require
an API key before they can be selected.

## Commands

```bash
dictate
dictate --no-tray
dictate --once
dictate --once --copy
dictate doctor --quick
dictate doctor --quick --fix
dictate doctor --check-model-load
```

Hotword and model options are available from Settings. CLI flags still exist for
automation and testing:

```bash
dictate --stt-backend faster-whisper --model turbo
dictate --stt-backend openai --model gpt-4o-mini-transcribe
dictate --stt-backend xai --model grok-speech-to-text
dictate --stt-backend gemini --model gemini-3-flash-preview
dictate --add-hotword AcmeWidget
dictate --list-hotwords
```

## State

User state is local:

```text
Linux:
  ~/.config/dictate/config.yaml
  ~/.local/share/dictate/

Windows:
  %APPDATA%\dictate\config.yaml
  %LOCALAPPDATA%\dictate\
```

Repo defaults intentionally ship with `hotwords: []`. Hotwords are user-specific
and should not be packaged into the public repo default config.

## Safety

- Dictate does not intentionally write raw API keys to `config.yaml`.
- API keys configured in the app use the OS secret store.
- Dictation text can be sensitive; check logs and issue reports before sharing.
- Important transcriptions should be verified before relying on them.
- Support and maintenance are best-effort.

## Desktop UI — the Quiet Console (preview)

A design-system desktop Settings window is being built alongside the tray:

- [`ui/`](ui/README.md) — React/Vite front-end (the Quiet Console: seven views,
  ⌘K palette, listening HUD, light/dark, GNOME/KDE chrome).
- [`ui-shell/`](ui-shell/README.md) — Tauri 2 shell that hosts it on Linux.
- `src/dictate/ui_server.py` — the loopback control server the UI talks to; the
  tray's **Open Settings…** launches the shell (falling back to native dialogs).
- See [`design/PLAN.md`](design/PLAN.md) for the cross-platform plan.

**Install it like a normal app:** tagged releases attach a **self-contained**
Linux **`.deb`** and **`.AppImage`** — they bundle the frozen Python engine
inside (PyInstaller sidecar), so there's no separate Python/pip step. Download,
install, launch; speech models download on first use.

```bash
sudo apt install ./dictate_*_amd64.deb      # or: chmod +x Dictate_*.AppImage && ./Dictate_*.AppImage
```

The app lives in the tray (Open Settings / Quit) and does push-to-talk straight
away. Build the package yourself in one step with
[`scripts/build-linux-desktop.sh`](scripts/build-linux-desktop.sh) — see
[`ui-shell/README.md`](ui-shell/README.md). The `pip`/`install.sh` route remains
for source/dev installs.

## Docs

- [Windows 11 support](docs/windows-11.md)
- [Recent History spec](docs/recent-dictation-history-spec.md)
- [Release/versioning](docs/release-versioning.md)
- [Desktop packaging & CI runbook](docs/desktop-packaging.md)
- [Microsoft Store automation](docs/msstore-automation.md)
- [Microsoft Store listing draft](docs/msstore-listing.md)
- [Windows release goal](docs/goal.md)
- [Development streams](docs/development-streams.md)
- [Security policy](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE).
