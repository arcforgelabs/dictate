# Development Streams

Dictate now has two active platform streams.

## Linux Stream

Linux remains the primary desktop stream:

- GTK/Ayatana tray.
- X11 typing through `xdotool`.
- Wayland typing through `wtype` or `ydotool`.
- Wayland global shortcuts through desktop portals where available.
- Linux install scripts and desktop-entry work.

Use GitHub labels such as `platform:linux`, `area:tray`, `area:hotkeys`, and `area:packaging`.

## Windows 11 Stream

Windows 11 is a parallel compatibility stream:

- Headless push-to-talk through `pynput`.
- Clipboard output through `pyperclip`.
- Windows app-data paths for config, history, and logs.
- Windows CI smoke tests.
- Repo-local PowerShell install path.
- Future native tray and signed installer work.

Use GitHub labels such as `platform:windows`, `area:windows-tray`, `area:installer`, and `area:packaging`.

## Branching

- `master`: release-ready integration branch for both streams.
- `linux/*`: Linux-specific work.
- `windows/*`: Windows-specific work.
- `release/YYYY.M.D`: release stabilization branch when a release needs final fixes.

Keep shared STT, audio, config, history, and CLI behavior on `master` unless the change is explicitly platform-specific.

Windows installation is intentionally implemented as a packaging edge around the shared app. The PowerShell installer should stay thin: create the environment, install `.[windows]`, seed config, write launchers, create shortcuts, and run diagnostics. Shared behavior should stay in `src/dictate`.

## GitHub Project Organization

Recommended project views:

- `Current Release`: issues and PRs assigned to the next CalVer release.
- `Linux Stream`: filter `platform:linux`.
- `Windows 11 Stream`: filter `platform:windows`.
- `Packaging`: filter `area:packaging` or `area:installer`.

Milestone names should use the public release version, for example `2026.5.18`.
