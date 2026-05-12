# dictate

Local voice-to-text for desktop dictation: hold `Right Ctrl`, speak, release to transcribe and type into the focused window.

Linux is the primary tray desktop. Windows 11 is supported as a separate headless compatibility stream.

## Features

- Local speech-to-text with selectable backends:
  - `faster-whisper` (default)
  - `whisper-cpp` (local whisper.cpp server; useful for Vulkan/AMD GPU builds)
  - `nemo-canary` (`nvidia/canary-1b`, `nvidia/canary-1b-flash`, `nvidia/canary-1b-v2`)
- Capability-aware backend contract (`hotwords`, prompt bias, language hint handling) so unsupported options fail soft with clear warnings.
- Backend-agnostic lexical adaptation modes: `native`, `prompt`, `post`, `hybrid`.
- Push-to-talk daemon: `Right Ctrl` hold/release to record/transcribe/type.
- Configurable push-to-talk key (`ctrl_r` default, `ctrl_l` supported for Wayland/laptop compatibility).
- System tray toggle (pause/resume dictation).
- Tray menu STT switcher (change backend/model without restart).
- Tray runtime profile switcher (device/compute tuning without restart).
- One-shot mode for terminal workflows (print to stdout or copy to clipboard).
- Typing backend auto-selection (`xdotool` on X11, `wtype`/`ydotool` on Wayland, `pynput` on Windows).
- Explicit backend resource release on switch (including CUDA cache cleanup when switching away from NeMo Canary).

## Requirements

- Linux (X11 recommended; Wayland supported depending on typing backend and hotkey support).
- Windows 11 for headless push-to-talk and one-shot modes.
- Python >= 3.11.
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

Ubuntu/Debian install with system packages, seeded default hotwords config, and prepared `faster-whisper/turbo`:

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

This creates `.venv`, installs the Windows dependencies, seeds config, writes launcher scripts, prepares the default model, runs diagnostics, and installs a Start Menu shortcut named `Dictate`. See [Windows 11 support](docs/windows-11.md) for the supported Windows surface and current gaps.

Optional: install NVIDIA NeMo backend dependencies in your active environment:

```bash
uv pip install -e ".[nemo]"
```

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
dictate doctor --check-model-load
```

Select model/device/compute-type/language:

```bash
# code-level faster-whisper fallback is "base"; installer-seeded config defaults to "turbo"
dictate --stt-backend faster-whisper --model large-v3-turbo
dictate --stt-backend whisper-cpp --model large-v3-turbo-q5_0
dictate --stt-backend nemo-canary --model nvidia/canary-1b-flash
dictate --device cpu
dictate --compute-type float16
dictate --language en
dictate --lexicon-mode hybrid
```

`--compute-type` affects `faster-whisper` only. For `nemo-canary`, it is ignored.

Prepare/download a heavy model ahead of activation:

```bash
dictate prepare-model --stt-backend nemo-canary --model nvidia/canary-1b-flash --device auto --compute-type int8
```

Manage lexical post-corrections:

```bash
dictate --add-lexicon-replacement kinneri=canary
dictate --remove-lexicon-replacement kinneri
dictate --list-lexicon-replacements
```

## STT Backends (RTX 4090)

Recommended defaults for low-latency dictation:

- Best balance of accuracy + speed: `nemo-canary` with `nvidia/canary-1b-flash`
- Best local Windows/AMD path: `whisper-cpp` with `large-v3-turbo-q5_0` and a Vulkan-enabled `whisper-server.exe`
- Best compatibility + hotword biasing: `faster-whisper` with `large-v3-turbo`

Examples:

```bash
# Fast, high-accuracy Canary path (recommended on RTX 4090)
dictate --stt-backend nemo-canary --model nvidia/canary-1b-flash --language en

# Canary v2 (often better quality than Canary 1B, but usually heavier)
dictate --stt-backend nemo-canary --model nvidia/canary-1b-v2 --language en

# Faster-whisper baseline with Whisper Turbo
dictate --stt-backend faster-whisper --model large-v3-turbo --language en

# Local whisper.cpp path for Windows/AMD Vulkan builds
dictate --stt-backend whisper-cpp --model large-v3-turbo-q5_0 --language en
```

Faster-whisper model choices used by Dictate (`Speech Model` menu):

- `base` (not "bass"): smallest option, fastest startup, lowest resource use, lower accuracy.
- `turbo`: optimized large-family variant (maps to `large-v3-turbo`), best speed/accuracy balance for push-to-talk.
- `large-v3`: full large model, highest accuracy in difficult audio, highest latency/memory usage.

Quick rule of thumb:

- If latency is critical: start with `turbo`.
- If quality is critical and you can accept extra delay: try `large-v3`.
- If you need minimal cold-start and resource use: use `base`.

Force typing backend (daemon modes):

```bash
dictate --type-backend xdotool
dictate --type-backend wtype
dictate --type-backend ydotool
dictate --type-backend pynput
```

## Hotwords

Hotwords improve recognition of custom vocabulary (project names, technical terms, etc.).

Manage saved hotwords:

```bash
dictate --add-hotword Kubernetes
dictate --add-hotword OpenBao,Vikunja
dictate --remove-hotword Vikunja
dictate --list-hotwords
```

Hotwords are saved to the platform config file. On Linux this is usually `~/.config/dictate/config.yaml`; on Windows this is `%APPDATA%\dictate\config.yaml`. Fresh installs created through the repo installer seed this file from [`config/default-config.yaml`](config/default-config.yaml).

You can also pass one-off hotwords without saving them:

```bash
dictate --hotwords "Kubernetes,OpenBao"
```

CLI `--hotwords` and saved hotwords are merged at startup.

Lexical adaptation modes (backend-agnostic):

- `native` (default): use backend-native hotword biasing (effective on `faster-whisper`)
- `prompt`: use prompt/context biasing (effective on prompt-capable backends such as `nemo-canary`)
- `post`: run lightweight post-correction against hotwords/replacements
- `hybrid`: apply all supported strategies

Mode behavior by backend:

- `faster-whisper`: `native`/`hybrid` applies decode-time hotword bias.
- `whisper-cpp`: hotwords are passed to the local server as prompt context.
- `nemo-canary`: use `prompt` or `hybrid` for prompt/context biasing, and/or `post`/`hybrid` for post-correction.
- In `native` mode on backends without native hotwords, hotwords are ignored with a warning.

Examples:

```bash
# Use prompt biasing for Canary with your hotwords list
dictate --stt-backend nemo-canary --lexicon-mode prompt

# Hybrid mode combines native/prompt/post where available
dictate --lexicon-mode hybrid

# Add explicit post-correction replacements
dictate --add-lexicon-replacement kinneri=canary
dictate --remove-lexicon-replacement kinneri
dictate --list-lexicon-replacements
```

## How It Works

**Hold Right Ctrl** to record, **release** to transcribe and type into the focused window.

If your desktop or keyboard reports `Right Ctrl` unreliably, set this in your platform config file:

```yaml
push_to_talk_combo: ctrl_l
```

In tray mode, a microphone icon appears in the system tray with a right-click menu:

- **Dictation active** — checkbox to pause/resume listening for the hotkey. The icon switches to a muted microphone when paused.
- **Speech Model** — switch backend/model live. For unprepared `nemo-canary` choices, Dictate first runs a subprocess preparation step, then activates on success.
- **Runtime Profile** — switch device/compute profile live (for example `cuda/int8`, `cuda/float16`, `cpu/int8`).
- Switching away from a loaded backend releases prior model resources; for NeMo Canary this includes CUDA cache cleanup to avoid long-lived VRAM retention.
- If switching fails, Dictate keeps the previous model active and shows an error dialog.
- **Quit** — stops the daemon.

You can also quit from the terminal with `Ctrl+C`.

Runtime profile presets currently shipped in tray:

- `cuda / int8` (recommended default)
- `cuda / float16`
- `cpu / int8`
- `auto / int8`

## Notes And Troubleshooting

- First run will likely download model files (Whisper or NeMo, depending on backend). Network is required once per model.
- Tray model/profile selections are persisted in the platform config file and used on startup unless CLI flags override them.
- Persisted STT selection keys:
  - `stt_backend`
  - `stt_model`
  - `stt_device`
  - `stt_compute_type`
- Additional recognized config keys:
  - `push_to_talk_combo` (examples: `ctrl_r`, `ctrl_l`, `ctrl+space`, `ctrl+shift`)
  - `lexicon_mode` (optional startup default; set manually in config)
  - `lexicon_replacements` (managed by CLI replacement commands)
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
- On Windows 11, use `dictate --no-tray --type-backend pynput` or one-shot mode; the Linux tray is not part of the Windows stream.
- If preflight reports missing tools, install them via your distro package manager (e.g. `xdotool`, `xclip`, `wtype`) or install the Windows extra with `pip install -e ".[windows]"`.
- Dictation uses the system default microphone input device. If your default input is misconfigured, fix it in your OS audio settings.
- If NeMo backend fails to load, install optional deps with `uv pip install -e ".[nemo]"`.
- If the app does not launch from GUI, run `dictate doctor --quick` and inspect the reported active log directory.

## Benchmarking

Use the local benchmark harness to compare backends/models on your own accent and vocabulary:

```bash
dictate benchmark \
  --manifest benchmarks/example_manifest.csv \
  --audio-root benchmarks \
  --stt-backend nemo-canary \
  --model nvidia/canary-1b-flash \
  --device cuda \
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

MIT (see `LICENSE`).
