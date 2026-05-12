# Windows 11 Support

Windows 11 is supported as a separate runtime stream from the Linux tray build.

## Supported Surface

- Python 3.11 or newer.
- One-shot dictation: `dictate --once`.
- Clipboard output: `dictate --once --copy` through `pyperclip`.
- Headless push-to-talk daemon: `dictate --no-tray --type-backend pynput`.
- Speech-to-text: `faster-whisper` on CPU or CUDA where the local Python/CUDA stack supports it.
- Local AMD GPU path: `whisper-cpp` with a Vulkan-enabled `whisper-server.exe` and `ggml-large-v3-turbo-q5_0.bin`.

The Linux GTK/Ayatana tray is not part of the Windows stream. Windows tray packaging should be developed separately so Linux desktop behavior can keep moving without being blocked by Windows shell work.

## Install

From PowerShell in the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-windows.ps1
```

That one command creates `.venv`, installs Dictate with the Windows dependencies, seeds `%APPDATA%\dictate\config.yaml`, writes launcher scripts, prepares the default `faster-whisper/turbo` model, runs `dictate doctor --quick`, and adds a Start Menu shortcut named `Dictate`.

Skip model preparation or verification when needed:

```powershell
.\install-windows.ps1 -NoPrepareTurbo -NoVerify
```

CI/smoke-test install without a Start Menu shortcut:

```powershell
.\install-windows.ps1 -NoPrepareTurbo -NoVerify -NoShortcut
```

Manual install:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[windows]"
.\.venv\Scripts\dictate.exe doctor --quick --type-backend pynput
.\.venv\Scripts\dictate.exe doctor --quick --stt-backend whisper-cpp --model large-v3-turbo-q5_0 --type-backend pynput
```

## Run

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
- Launchers: `.venv\Scripts\dictate-daemon.cmd` and `.venv\Scripts\dictate-once.cmd`
- Start Menu shortcut: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Dictate.lnk`

## Known Gaps

- No native Windows tray yet.
- No signed Windows installer package yet; the repo-local PowerShell installer is the supported path for now.
- Global hotkey reliability depends on `pynput` permissions and the active desktop/session.
- NeMo Canary on Windows is not part of the supported baseline.
