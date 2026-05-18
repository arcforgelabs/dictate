"""Platform launcher and startup integration helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def app_entry_path() -> Path:
    if sys.platform.startswith("win"):
        return _windows_programs_dir() / "Dictate.lnk"
    return _linux_applications_dir() / "dictate.desktop"


def startup_entry_path() -> Path:
    if sys.platform.startswith("win"):
        return _windows_programs_dir() / "Startup" / "Dictate.lnk"
    return _linux_autostart_dir() / "dictate.desktop"


def startup_enabled() -> bool:
    path = startup_entry_path()
    if not path.exists():
        return False
    if sys.platform.startswith("win"):
        return True
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "Hidden=true" not in content and "X-GNOME-Autostart-enabled=false" not in content


def set_startup_enabled(enabled: bool) -> None:
    if sys.platform.startswith("win"):
        if enabled:
            install_windows_startup_shortcut()
        else:
            startup_entry_path().unlink(missing_ok=True)
        return

    if enabled:
        install_linux_startup_entry()
    else:
        startup_entry_path().unlink(missing_ok=True)


def install_linux_app_entry() -> Path:
    path = app_entry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_linux_desktop_entry(autostart=False), encoding="utf-8")
    update_desktop_database = shutil.which("update-desktop-database")
    if update_desktop_database:
        subprocess.run(
            [update_desktop_database, str(path.parent)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return path


def install_linux_startup_entry() -> Path:
    path = startup_entry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_linux_desktop_entry(autostart=True), encoding="utf-8")
    return path


def install_linux_desktop_integration(
    *,
    include_startup: bool = True,
) -> tuple[Path, Path | None]:
    app_path = install_linux_app_entry()
    startup_path = install_linux_startup_entry() if include_startup else None
    return app_path, startup_path


def install_windows_startup_shortcut() -> Path:
    startup_path = startup_entry_path()
    scripts_dir = Path(sys.executable).resolve().parent
    tray_launcher = scripts_dir / "dictate-tray.vbs"
    if not tray_launcher.is_file():
        raise RuntimeError(f"tray launcher not found: {tray_launcher}")
    install_location = scripts_dir.parents[1]
    icon_path = Path(__file__).resolve().parents[2] / "assets" / "dictate.ico"
    script = f"""
$startupDir = {_ps_quote(startup_path.parent)}
$shortcutPath = {_ps_quote(startup_path)}
$targetPath = {_ps_quote(tray_launcher)}
$workingDirectory = {_ps_quote(install_location)}
$iconPath = {_ps_quote(icon_path)}
New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $workingDirectory
$shortcut.Description = 'Start Dictate automatically at sign-in'
if (Test-Path $iconPath) {{ $shortcut.IconLocation = $iconPath }}
$shortcut.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
    )
    return startup_path


def _linux_desktop_entry(*, autostart: bool) -> str:
    exec_path = _linux_exec_path()
    lines = [
        "[Desktop Entry]",
        "Name=Dictate",
        "Comment=Local voice-to-text with push-to-talk",
        f"Exec={exec_path}",
        f"Icon={_linux_icon_path()}",
        "Type=Application",
        "Categories=AudioVideo;Audio;",
        "Keywords=voice;speech;transcription;dictation;asr;whisper;canary;",
        "Terminal=false",
    ]
    if autostart:
        lines.append("X-GNOME-Autostart-enabled=true")
    return "\n".join(lines) + "\n"


def _linux_exec_path() -> str:
    return shutil.which("dictate") or str(Path.home() / ".local" / "bin" / "dictate")


def _linux_icon_path() -> str:
    installed_icon = (
        Path.home() / ".local" / "share" / "dictate" / "share" / "icons" / "dictate-simple.png"
    )
    if installed_icon.is_file():
        return str(installed_icon)
    source_icon = Path(__file__).resolve().parents[2] / "assets" / "dictate.png"
    if source_icon.is_file():
        return str(source_icon)
    return "microphone-sensitivity-high-symbolic"


def _linux_applications_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "applications"


def _linux_autostart_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return base / "autostart"


def _windows_programs_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return (
        Path.home()
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )


def _ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"
