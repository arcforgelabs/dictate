# 🎙️ Dictate

Desktop dictation that types into the focused app.

`dictate` runs as a small tray app. Press your configured push-to-talk shortcut,
speak, and it transcribes into whatever app you are already using.

Current status: early desktop app. Linux installs, Windows 11 source installs,
tray controls, startup integration, local dictation history, update, and
uninstall paths are implemented. Microsoft Store packaging and submission
automation are maintained separately from GitHub releases; see
`docs/msstore-automation.md`. The current transcription/model deployment plan is
`docs/TRANSCRIPTION_PLAN.md`.

## Install

Windows 11 normal install:

The target public channel is Microsoft Store distribution. Tagged GitHub
releases can also attach a signed Windows `.msi` as a direct-download fallback
for users who do not want the Store route. Unsigned Windows installers are never
published as public release assets.

Windows direct download:

1. Open the latest GitHub release.
2. Download `Dictate_*_x64_en-US.msi` when it is attached.
3. Run the MSI and open **Dictate** from the Start Menu.

If a release does not yet have an MSI attached, use the developer/source
bootstrap below or wait for the signed MSI asset to be published.

Windows developer/source install from the hosted bootstrap:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"
```

Unstable developer/source bootstrap for pre-stable feature testing:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@unstable/install.ps1 | iex"
```

Open **Dictate** from the Start Menu after install.

Linux default install (per-user, no sudo for app updates):

```bash
./install-ubuntu.sh
```

Generic Linux user install:

```bash
./install.sh
```

Open **Dictate** from the app launcher after install.

Linux system package install is also supported when you explicitly want a
machine-wide `.deb` install:

```bash
DICTATE_BUNDLES=deb scripts/build-linux-desktop.sh
./install.sh --system
```

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
Use the mic button or configured push-to-talk shortcut
Hold shortcut, speak, release
Review Dictations when needed
```

By default, Dictate installs a normal app launcher entry and starts on sign-in.
Advanced configuration is available through the `dictate config` CLI.

## Update And Uninstall

Windows developer/bootstrap install:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/update.ps1 | iex"
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/uninstall.ps1 | iex"
```

To test updates before they are promoted to stable:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@unstable/update.ps1 | iex"
```

Users on the app's npm-backed update path can opt into or out of unstable
updates from the CLI:

```bash
dictate config set-update-channel unstable
dictate config set-update-channel stable
```

Windows from source:

```powershell
powershell -ExecutionPolicy Bypass -File .\update-windows.ps1
powershell -ExecutionPolicy Bypass -File .\uninstall-windows.ps1
```

Linux user install:

```bash
./update.sh
./uninstall.sh
```

Linux system package update:

```bash
./update.sh --system
```

Use `-RemoveUserData` on Windows or `--remove-user-data` on Linux only when you
also want to remove config, logs, history, and downloaded model data.

## What It Does Today

- Starts from the Windows Start Menu or Linux app launcher
- Runs as a tray app
- Types dictated text into the focused app
- Supports configurable push-to-talk
- Presents a simple capture-first desktop UI
- Supports launch on startup
- Stores CLI-configured hosted-provider API keys in the OS secret store
- Keeps a small local dictations history for copy/paste recovery
- Provides installer, updater, uninstaller, and doctor paths

## Models

The default local English path is Parakeet where the runtime is available. The
desktop UI keeps engine names out of the primary workflow; advanced users and
tests can still configure explicit local or hosted providers through CLI options
and `dictate config`.

GPU lanes are explicit:

- NVIDIA CUDA: install with the `gpu` extra and verify with
  `dictate doctor --stt-backend parakeet --device cuda --quick`.
- Windows AMD GPU: install with the `amd` extra for ONNX Runtime DirectML and
  verify with `dictate doctor --stt-backend parakeet --device amd --quick`.
- Linux AMD GPU: install a ROCm/MIGraphX-capable ONNX Runtime build, then verify
  with `dictate doctor --stt-backend parakeet --device amd --quick`.
- Meeting uses a dedicated speaker-attribution lane. Inspect it with
  `dictate config show`; set it with
  `dictate config set-meeting-model parakeet-pyannote/parakeet-tdt-0.6b-v2`.
  Source installs can add pyannote support with `./install.sh --meeting` or
  `.\install-windows.ps1 -Meeting`, then verify with
  `dictate doctor --stt-backend parakeet-pyannote --device cuda --quick`.
  Experimental preflight targets also exist for
  `parakeet-diarizen/parakeet-tdt-0.6b-v2` and
  `parakeet-sortformer/parakeet-tdt-0.6b-v2`; these still require their
  runtime-specific DiariZen or NeMo setup before selection.

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

Advanced configuration remains available for automation and testing:

```bash
dictate --stt-backend faster-whisper --model turbo
dictate config show
dictate config set-provider online
dictate config set-key xai xai-YOUR_KEY_HERE
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
- API keys configured through the CLI use the OS secret store.
- Dictation text can be sensitive; check logs and issue reports before sharing.
- Important transcriptions should be verified before relying on them.
- Support and maintenance are best-effort.

## Desktop UI — the Quiet Console (preview)

A quiet desktop window sits alongside the tray — a capture home (the mic is the
record button), the notes list, and the ⌘K palette; no settings menu (config via
the `dictate config` CLI).

- [`ui/`](ui/README.md) — React/Vite front-end. For UI work, **`cd ui && npm run
  dev`** opens the whole app at `http://localhost:5173` against a built-in mock
  (no engine, no Tauri, no STT) — the fast UI loop in a browser. Details, and
  when to use the Tauri shell instead, are in that README's *Develop* section.
- [`ui-shell/`](ui-shell/README.md) — Tauri 2 shell that hosts it on Linux.
- `src/dictate/ui_server.py` — the loopback control server the UI talks to; the
  tray can launch the shell for the desktop capture surface.
- See [`design/PLAN.md`](design/PLAN.md) for the cross-platform plan.

**Install it like a normal app:** the default Linux channel is a per-user install
under `~/.local/share/dictate` with launchers in `~/.local/bin` and
`~/.local/share/applications`. App updates do not need sudo.

```bash
./install.sh
./update.sh
```

Tagged releases can also attach a **self-contained** Linux **`.deb`** for users
who explicitly want a system package. It bundles the frozen Python engine inside
(PyInstaller sidecar), so there's no separate Python/pip step:

```bash
sudo apt install ./Dictate_*_amd64.deb
```

The app lives in the tray and desktop shell and does push-to-talk straight away.
Build the package yourself in one step with
[`scripts/build-linux-desktop.sh`](scripts/build-linux-desktop.sh) — see
[`ui-shell/README.md`](ui-shell/README.md). The `pip`/`install.sh` route remains
for source/dev installs.

## Docs

- [Windows 11 support](docs/windows-11.md)
- [Transcription deployment plan](docs/TRANSCRIPTION_PLAN.md)
- [Release/versioning](docs/release-versioning.md)
- [Desktop packaging & CI runbook](docs/desktop-packaging.md)
- [Microsoft Store automation](docs/msstore-automation.md)
- [Microsoft Store listing draft](docs/msstore-listing.md)
- [Deployment security](docs/deployment-security.md)
- [Development streams](docs/development-streams.md)
- [Archived docs index](docs/archive/README.md)
- [Security policy](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE).
