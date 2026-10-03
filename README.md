<p align="center">
  <img src="https://raw.githubusercontent.com/arcforgelabs/dictate/master/assets/dictate.png" alt="Dictate" width="128" height="128">
</p>

# Dictate

Desktop dictation that types into the focused app.

`dictate` runs as a small tray app. Press your configured push-to-talk shortcut,
speak, and it transcribes into whatever app you are already using.

**Local only.** Transcription runs on your machine. No account, no
subscription, no API key, no hosted model. Nothing you say leaves the device.

Current status: not a commercial product. Dictate was retired as one on
2026-08-25 and is now worked on when there is time. Linux installs, Windows 11
source installs, tray controls, startup integration, local dictation history,
update, and uninstall paths are implemented.

The account, subscription, cloud sync and hosted-transcription code was
removed on 2026-09-19 — 27,064 lines across 107 files. See
`docs/local-only-audit.md` for what went and why, and `VISION.md` for the
direction. The current transcription/model plan is
`docs/TRANSCRIPTION_PLAN.md`.

## Install

Windows 11 — Microsoft Store remains the intended public channel, with direct
download from GitHub Releases available meanwhile.

The Store listing is overdue for an update and will get one once the first
stable local-only build is done. Store packaging, submission automation and the
listing copy all stay; only the in-app subscription part goes, since there is
nothing to subscribe to. See `docs/msstore-automation.md`.

Windows direct download:

1. Open the latest GitHub release.
2. Download `Dictate_*_x64_en-US.msi` when a staging MSI is attached.
3. Run the MSI and open **Dictate** from the Start Menu. Windows may warn that
   the installer is from an untrusted publisher; that is expected for staging
   builds.

If a release does not yet have an MSI attached, use the developer/source
bootstrap below or wait for the Microsoft Store package.

Windows developer/source install from the hosted bootstrap:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"
```

Unstable developer/source bootstrap for pre-stable feature testing:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@unstable/install.ps1 | iex"
```

Open **Dictate** from the Start Menu after install.

Linux (Ubuntu) — install the release `.deb`. It is built once in CI with the
engine, model and desktop shell inside, so every install of a version is the
same:

1. Download `Dictate_<version>_amd64.deb` from the latest GitHub release.
2. Install it with apt, giving the path to the file:

   ```bash
   sudo apt install ~/Downloads/Dictate_<version>_amd64.deb
   ```

3. Open **Dictate** from the app launcher. It starts on sign-in.

Dictate does not publish an apt repository, so `apt upgrade` does not see new
versions. Update from the app, or install the next release's `.deb` the same
way.

Linux latest code (per-user, builds on your machine, no sudo). This installs
from source into `~/.local/share/dictate` and compiles the desktop shell
locally, so it needs `cargo`, `npm` and `webkit2gtk-4.1-dev`:

```bash
npx @arcforgelabs/dictate install
```

Or from a checkout: `./install-ubuntu.sh`, or `./install.sh` on other
distributions.

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

Linux `.deb` install: update from the app, or install the newer `.deb` with
`sudo apt install`. Remove it with:

```bash
sudo apt purge dictate
```

Linux latest-code (per-user) install:

```bash
npx @arcforgelabs/dictate update --user
npx @arcforgelabs/dictate uninstall
```

From a checkout, `./update.sh` and `./uninstall.sh` do the same.

Use `-RemoveUserData` on Windows or `--remove-user-data` on Linux only when you
also want to remove config, logs, history, and downloaded model data.

## What It Does Today

- Starts from the Windows Start Menu or Linux app launcher
- Runs as a tray app
- Types dictated text into the focused app. A terminal, including the Grok
  CLI, receives that text with Shift+Insert so it is not filed as an attachment.
- Supports configurable push-to-talk
- Presents a simple capture-first desktop UI
- Supports launch on startup
- Keeps a small local dictations history for copy/paste recovery
- Provides installer, updater, uninstaller, and doctor paths

## Models

Dictation runs NVIDIA Parakeet TDT 0.6B through ONNX Runtime: v2 for English
(the default, bundled with the desktop app) or v3 for 25 European languages.
Every supported model runs on your machine. The Whisper-family backends
(faster-whisper, WhisperX, whisper.cpp) were removed on 2026-09-30; a saved
config that still names one falls back to Parakeet. The desktop UI keeps engine names out of the primary workflow;
advanced users and tests can still select an explicit local engine through CLI
options and `dictate config`.

Dictate runs on the CPU. GPU support (NVIDIA CUDA, AMD) was dropped on
2026-10-01 to focus on CPU latency. The installers no longer install a GPU
runtime; their old GPU flags are accepted and ignored so existing update
commands keep working. The engine has no device choice: a saved GPU device in
`config.yaml` moves to CPU on upgrade, and `--device` is still accepted so the
installers and old scripts run, and is ignored.

- The Meeting button and the dictation-list filter are beta-channel chrome.
  The normal channel is dictation only. Meeting uses a dedicated
  speaker-attribution lane. Inspect it with
  `dictate config show`; set it with
  `dictate config set-meeting-model parakeet-pyannote/parakeet-tdt-0.6b-v2`.
  Source installs can add pyannote support with `./install.sh --meeting` or
  `.\install-windows.ps1 -Meeting`, then verify with
  `dictate doctor --stt-backend parakeet-pyannote --quick`.
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
dictate --stt-backend parakeet --model parakeet-tdt-0.6b-v3
dictate config show
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

- Audio and transcripts stay on the device. There is no hosted transcription
  path and no account.
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

**Install it like a normal app:** on Linux that is the release **`.deb`**. It
bundles the frozen Python engine (PyInstaller sidecar) and the prebuilt desktop
shell, so there is no Python, pip or compiler step:

```bash
sudo apt install ./Dictate_*_amd64.deb
```

The app lives in the tray and desktop shell and does push-to-talk straight away.
Build the package yourself in one step with
[`scripts/build-linux-desktop.sh`](scripts/build-linux-desktop.sh) — see
[`ui-shell/README.md`](ui-shell/README.md). The per-user `npm`/`install.sh`
route installs under `~/.local/share/dictate` and builds on your machine; use it
to try the latest code, not as the everyday install.

## Docs

- [Windows 11 support](docs/windows-11.md)
- [Transcription deployment plan](docs/TRANSCRIPTION_PLAN.md)
- [Release policy: channels, versions, validation](docs/RELEASING.md)
- [Release/versioning (current procedure)](docs/release-versioning.md)
- [Desktop packaging & CI runbook](docs/desktop-packaging.md)
- [Microsoft Store automation](docs/msstore-automation.md)
- [Microsoft Store listing draft](docs/msstore-listing.md)
- [Deployment security](docs/deployment-security.md)
- [Development streams](docs/development-streams.md)
- [Archived docs index](docs/archive/README.md)
- [Security policy](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE).
