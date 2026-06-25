# Development Streams

Dictate has two active platform streams.

## Linux Stream

Linux desktop stream:

- GTK/Ayatana tray.
- X11 typing through `xdotool`.
- Wayland typing through `wtype` or `ydotool`.
- Wayland global shortcuts through desktop portals where available.
- Linux install scripts, desktop entry, icon, and autostart integration.

Use GitHub labels such as `platform:linux`, `area:tray`, `area:hotkeys`, and `area:packaging`.

## Windows 11 Stream

Windows 11 desktop stream:

- Tray and headless push-to-talk through `pynput`.
- Clipboard output through `pyperclip`.
- Windows app-data paths for config, history, and logs.
- Windows Settings/About UI.
- Windows CI smoke tests for install, update, app registration, startup, and uninstall.
- Hosted and repo-local PowerShell install paths for developer/source installs.
- Tauri `.msi`/NSIS installer build path for internal validation.
- Microsoft Store distribution as the target public Windows channel.
- Future signing and Store submission automation.

Use GitHub labels such as `platform:windows`, `area:windows-tray`, `area:installer`, and `area:packaging`.

## Branching

- `master`: release-ready integration branch for both streams.
- `linux/*`: Linux-specific work.
- `windows/*`: Windows-specific work.
- `release/YYYY.M.D`: release stabilization branch when a release needs final fixes.

Keep shared STT, audio, config, history, and CLI behavior on `master` unless the change is explicitly platform-specific.

Windows installation is intentionally implemented as a packaging edge around the shared app. The PowerShell installer should stay thin: create the environment, install `.[windows]`, seed config, write launchers, create shortcuts, and run diagnostics. Shared behavior should stay in `src/dictate`.

The public Windows release target is tracked in [GOALS.md](GOALS.md). Store API
automation wiring is tracked in [msstore-automation.md](msstore-automation.md).

## GitHub Project Organization

Recommended project views:

- `Current Release`: issues and PRs assigned to the next CalVer release.
- `Linux Stream`: filter `platform:linux`.
- `Windows 11 Stream`: filter `platform:windows`.
- `Packaging`: filter `area:packaging` or `area:installer`.

Milestone names should use the public release version, for example `2026.5.18`.
