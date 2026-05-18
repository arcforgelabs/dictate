# dictate

Dictate is a small desktop dictation app: press your configured push-to-talk shortcut, speak, and Dictate types the transcription into the focused app.

It is meant to do one job well: dictate anywhere on your computer without turning the app into a writing suite. Linux and Windows 11 both have install paths, tray/status UI, startup integration, model settings, recent history, and update/uninstall support.

## Features

- Dictate into whatever app currently has focus.
- Configurable push-to-talk shortcut from the app settings or config file.
- Start Menu / app launcher integration and launch-on-startup support.
- Tray/status UI with the selected model shown at the top.
- Recent History with copy/paste actions and pagination for up to 20 dictations.
- About/update controls with version, documentation, terms, update check, and update action.
- Speech-to-text backends kept intentionally small:
  - `faster-whisper` with `turbo` (default local Whisper path)
  - `openai` with `gpt-4o-mini-transcribe`
  - `xai` with `grok-speech-to-text`
  - `gemini` with `gemini-3-flash-preview`
- Local CPU/GPU runtime selection for the local model.
- API key status for hosted providers: Ready, None, or Invalid.
- Capability-aware backend contract (`hotwords`, prompt bias, language hint handling) so unsupported options fail soft with clear warnings.
- Backend-agnostic lexical adaptation modes: `native`, `prompt`, `post`, `hybrid`.
- One-shot mode for terminal workflows (print to stdout or copy to clipboard).
- Typing backend auto-selection (`xdotool` on X11, `wtype`/`ydotool` on Wayland, `pynput` on Windows).
- Explicit backend resource release on switch.

## Requirements

- Linux (X11 recommended; Wayland supported depending on typing backend and hotkey support).
- Windows 11 for tray, settings, startup, push-to-talk, and one-shot modes.
- Python 3.11 or 3.12.
- Microphone/audio: `sounddevice` + a working PortAudio setup.
- Typing backend (for daemon modes):
  - X11: `xdotool` (recommended)
  - Wayland: `wtype` or `ydotool`
  - Windows 11: `pynput`
- Clipboard (for `--once --copy`): `xclip` on Linux or `pyperclip` on Windows.
- Tray icon dependencies (for default tray mode):
  - GTK + GI bindings (`python3-gi`)
  - Ayatana indicator bindings (`gir1.2-ayatanaappindicator3-0.1` or equivalent for your distro)

## Install

Ubuntu/Debian install with system packages, seeded user config, and prepared `faster-whisper/turbo`:

```bash
./install-ubuntu.sh
```

Generic repo install (assumes OS packages and `uv` are already present):

```bash
./install.sh
```

`install.sh` seeds the Linux config file from [`config/default-config.yaml`](config/default-config.yaml) on first install and prepares the `faster-whisper/turbo` model by default. Existing user config is left untouched.

Installer verification/model preparation can be skipped if needed:

```bash
./install.sh --no-verify --no-prepare-turbo
```

Windows 11 install from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
```

Windows setup wizard:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows-wizard.ps1
```

Hosted Windows one-liner:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@iamsamuelrodda/dictate@latest/install.ps1 | iex"
```

Node/npm users can also run:

```powershell
npx @iamsamuelrodda/dictate install
```

This creates `.venv`, installs the Windows dependencies, seeds config, writes launcher scripts, prepares the default model, runs diagnostics, and installs a Start Menu shortcut named `Dictate`. The `Dictate` shortcut starts the Windows tray app. See [Windows 11 support](docs/windows-11.md) for details.
The Windows installer also verifies the Microsoft Visual C++ runtime needed by the native transcription wheels and installs it when it is missing.
Linux installs create a desktop launcher named `Dictate`, install the app icon, and enable launch on startup by default unless `--no-startup` is used.

Update or uninstall from a source checkout:

```bash
./update.sh
./uninstall.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\update-windows.ps1
powershell -ExecutionPolicy Bypass -File .\uninstall-windows.ps1
```

Use `--remove-user-data` on Linux or `-RemoveUserData` on Windows only when you also want to remove config, logs, history, and downloaded model data.

Dictate is built to be useful, but it has real-world risks. Support and maintenance are best-effort, and important output should be checked before you rely on it. Report issues so they can be fixed; if Dictate saves you time and you have the means, paid support helps keep the work moving. Arc Forge terms are at <https://arcforge.au/terms>.

## Usage

Tray mode (default):

```bash
dictate
```

Headless daemon (no tray icon):

```bash
dictate --no-tray
```

One-shot (record until Enter, print to stdout):

```bash
dictate --once
```

One-shot (record until Enter, copy to clipboard):

```bash
dictate --once --copy
```

Run diagnostics:

```bash
dictate doctor --quick
dictate doctor --quick --fix
dictate doctor --quick --update-paths
dictate doctor --check-model-load
```

Select model/runtime/language from the UI or CLI:

```bash
dictate --stt-backend faster-whisper --model turbo
dictate --stt-backend openai --model gpt-4o-mini-transcribe
dictate --stt-backend xai --model grok-speech-to-text
dictate --stt-backend gemini --model gemini-3-flash-preview
dictate --device cpu
dictate --compute-type float16
dictate --language en
dictate --lexicon-mode hybrid
```

`--device` and `--compute-type` affect local transcription only. Hosted API backends ignore local CPU/GPU settings.
For hosted backends, use the **Select Model** options in the tray/settings UI to store keys in the OS secret store
(Secret Service/libsecret on Linux, Windows Credential Manager on Windows). Dictate never writes raw API keys
to `config.yaml`. Environment variables such as `DICTATE_OPENAI_API_KEY`, `DICTATE_XAI_API_KEY`, and
`DICTATE_GEMINI_API_KEY` still take priority, and advanced users can keep using `*_api_key_command` config
entries that call their own secret manager.

Manage lexical post-corrections:

```bash
dictate --add-lexicon-replacement acme-widgit=AcmeWidget
dictate --remove-lexicon-replacement acme-widgit
dictate --list-lexicon-replacements
```

## STT Backends

Supported defaults for low-latency dictation:

- Local default: `faster-whisper` with `turbo`
- Hosted OpenAI route: `openai` with `gpt-4o-mini-transcribe`
- Hosted xAI route: `xai` with `grok-speech-to-text`
- Hosted Gemini route: `gemini` with `gemini-3-flash-preview`

Examples:

```bash
# Local transcription
dictate --stt-backend faster-whisper --model turbo --language en

# Hosted transcription path, useful when local GPU should be reserved for other work
OPENAI_API_KEY=... dictate --stt-backend openai --model gpt-4o-mini-transcribe --language en

# Hosted xAI path with keyterm biasing from configured hotwords
XAI_API_KEY=... dictate --stt-backend xai --model grok-speech-to-text --language en

# Hosted Gemini path using Gemini audio understanding
GEMINI_API_KEY=... dictate --stt-backend gemini --model gemini-3-flash-preview --language en

# Desktop autostart can use keys stored from the app settings.
# Advanced external secret-manager helpers are still supported:
# stt_backend: openai
# stt_model: gpt-4o-mini-transcribe
# openai_api_key_command: ~/.local/bin/dictate-openai-key
# stt_backend: xai
# stt_model: grok-speech-to-text
# xai_api_key_command: ~/.local/bin/dictate-xai-key
# stt_backend: gemini
# stt_model: gemini-3-flash-preview
# gemini_api_key_command: ~/.local/bin/dictate-gemini-key
```

The app UI exposes one local option: `faster-whisper/turbo`, with CPU/GPU runtime selection where supported.

Force typing backend (daemon modes):

```bash
dictate --type-backend xdotool
dictate --type-backend wtype
dictate --type-backend ydotool
dictate --type-backend pynput
```

## Hotwords

Hotwords improve recognition of custom vocabulary such as project names, product names, people, and technical terms. In the desktop UI, hotwords live with the selected model options when that provider can use them.

Manage saved hotwords:

```bash
dictate --add-hotword AcmeWidget
dictate --add-hotword ProjectNova,TeamAtlas
dictate --remove-hotword TeamAtlas
dictate --list-hotwords
```

Hotwords are saved to the platform config file. On Linux this is usually `~/.config/dictate/config.yaml`; on Windows this is `%APPDATA%\dictate\config.yaml`. Fresh installs created through the repo installer seed this file from [`config/default-config.yaml`](config/default-config.yaml), which intentionally ships with an empty hotword list because vocabulary is user-specific.

You can also pass one-off hotwords without saving them:

```bash
dictate --hotwords "AcmeWidget,ProjectNova"
```

CLI `--hotwords` and saved hotwords are merged at startup.

Lexical adaptation modes (backend-agnostic):

- `native` (default): use backend-native hotword biasing (effective on `faster-whisper`)
- `prompt`: use prompt/context biasing (effective on prompt-capable API backends)
- `post`: run lightweight post-correction against hotwords/replacements
- `hybrid`: apply all supported strategies

Mode behavior by backend:

- `faster-whisper`: `native`/`hybrid` applies decode-time hotword bias.
- `openai` and `gemini`: use `prompt` or `hybrid` for prompt/context biasing, and/or `post`/`hybrid` for post-correction.
- `xai`: `native`/`hybrid` passes keyterms to the hosted STT API.
- In `native` mode on backends without native hotwords, hotwords are ignored with a warning.

Examples:

```bash
# Use prompt biasing with your hotwords list on a prompt-capable API backend
dictate --stt-backend gemini --lexicon-mode prompt

# Hybrid mode combines native/prompt/post where available
dictate --lexicon-mode hybrid

# Add explicit post-correction replacements
dictate --add-lexicon-replacement acme-widgit=AcmeWidget
dictate --remove-lexicon-replacement acme-widgit
dictate --list-lexicon-replacements
```

## How It Works

Use your configured push-to-talk shortcut to record, then release it to transcribe and type into the focused window.

If your desktop or keyboard reports a shortcut unreliably, change it from the app settings or set `push_to_talk_combo` in your platform config file:

```yaml
push_to_talk_combo: ctrl+space
```

In tray mode, a microphone icon appears in the system tray. The menu and settings surfaces include:

- **Active** — checkbox to pause/resume listening for the hotkey. The icon switches to a muted microphone when paused.
- **Model status** — top-line indication of the active provider/model, including CPU/GPU for Local.
- **Select Model** — switch between Local, OpenAI, xAI, and Gemini. Hosted providers show API key status before they can be selected.
- **Local** — choose CPU or GPU for local transcription where supported.
- **API key** — store or clear OpenAI, xAI, and Gemini keys in the OS secret store.
- **Hotwords** — manage saved vocabulary when the selected model can use it.
- **Hotkeys** — configure the recording shortcut.
- **Launch on start up** — enable or disable automatic start at sign-in.
- **About** — view the running version, check for updates, run an update, and open documentation/terms.
- **Recent History** — copy or paste a previous dictation. History keeps up to 20 entries and paginates the list.
- If switching fails, Dictate keeps the previous backend active and shows an error dialog.
- **Quit** — stops the daemon.

You can also quit from the terminal with `Ctrl+C`.

## Notes And Troubleshooting

- First local run will likely download Whisper model files. Network is required once per model.
- Tray backend selections are persisted in the platform config file and used on startup unless CLI flags override them.
- Persisted STT selection keys:
  - `stt_backend`
  - `stt_model`
  - `stt_device`
  - `stt_compute_type`
- Additional recognized config keys:
  - `push_to_talk_combo` (examples: `ctrl+space`, `ctrl+shift`, `ctrl_r`, `ctrl_l`)
  - `lexicon_mode` (optional startup default; set manually in config)
  - `lexicon_replacements` (managed by CLI replacement commands)
  - `openai_api_key_command`, `xai_api_key_command`, `gemini_api_key_command`
- Preflight now checks STT backend readiness (dependency imports + CUDA visibility) before model load.
- Startup stderr is mirrored to logs:
  - Linux latest run: `~/.local/share/dictate/logs/latest.log`
  - Linux last non-zero exit: `~/.local/share/dictate/logs/last_failure.log`
  - Windows logs: `%LOCALAPPDATA%\dictate\logs\`
  - fallback when home path is not writable: system temp directory `dictate-logs`
- On Wayland:
  - `xdotool` generally will not work for native Wayland apps.
  - Prefer `wtype` (simple) or `ydotool` (may require extra setup/permissions).
  - Global hotkeys can be restricted on some Wayland compositors; if your combo does not fire, try `push_to_talk_combo: ctrl_l` or `push_to_talk_combo: ctrl+space`, use `--once`, or run an X11 session.
- On Windows 11, the Start Menu shortcut named `Dictate` starts the native tray app. Use `dictate --no-tray --type-backend pynput` only when you explicitly want a headless daemon.
- If preflight reports missing tools, install them via your distro package manager (e.g. `xdotool`, `xclip`, `wtype`) or install the Windows extra with `pip install -e ".[windows]"`.
- Dictation uses the system default microphone input device. If your default input is misconfigured, fix it in your OS audio settings.
- If the app does not launch from GUI, run `dictate doctor --quick` and inspect the reported active log directory.

## Benchmarking

Use the local benchmark harness to compare backends/models on your own accent and vocabulary:

```bash
dictate benchmark \
  --manifest benchmarks/example_manifest.csv \
  --audio-root benchmarks \
  --stt-backend faster-whisper \
  --model turbo \
  --device auto \
  --language en
```

Legacy wrapper still works:

```bash
uv run python scripts/benchmark_stt.py --help
```

Create your own manifest with Australian-accent phrases and proper nouns. Format docs: `benchmarks/README.md`.

## Testing

Run regression tests:

```bash
uv run python -m unittest discover -s tests
```

## Development

- Entry point: `dictate` is `dictate.__main__:main_with_logging` (see `src/dictate/__main__.py`).
- Core pipeline modules:
  - audio capture: `src/dictate/audio.py`
  - transcription engine: `src/dictate/engine.py`
  - typing/clipboard outputs: `src/dictate/outputs.py`
  - environment checks: `src/dictate/preflight.py`
  - STT backends + registry: `src/dictate/stt/`
- Platform docs:
  - Windows 11 stream: `docs/windows-11.md`
  - Development streams: `docs/development-streams.md`
  - CalVer releases: `docs/release-versioning.md`

## License

Apache-2.0 (see `LICENSE`). Preserve `NOTICE` when redistributing the project.
Contributions are accepted under the terms in `CONTRIBUTING.md`.
