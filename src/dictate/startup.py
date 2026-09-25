"""Platform launcher and startup integration helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dictate.platform_paths import user_data_dir


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


def install_linux_app_entry() -> Path | None:
    _linux_settings_entry_path().unlink(missing_ok=True)
    path = app_entry_path()
    if _packaged_app_entry_installed():
        # The .deb already ships a launcher; a user copy under a different
        # desktop ID shows up as a second "Dictate" in the app grid.
        _remove_generated_app_entry()
        return None
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
) -> tuple[Path | None, Path | None]:
    app_path = install_linux_app_entry()
    startup_path = install_linux_startup_entry() if include_startup else None
    return app_path, startup_path


def _desktop_integration_marker() -> Path:
    return user_data_dir() / ".desktop-integrated"


def ensure_desktop_integration_once() -> None:
    """First time the installed Linux app runs, create the app launcher and
    autostart entries so Dictate appears in the menu and starts on sign-in.

    The ``.deb`` ships its own launcher but no autostart entry, and the AppImage
    ships neither (source installs do both in ``install.sh``), so the engine
    self-registers on first run.
    Gated to the frozen app and run once via a marker, so a user who later
    disables startup is not overridden. Best-effort: never blocks daemon start.
    """
    if sys.platform.startswith("win"):
        return
    if not getattr(sys, "frozen", False):
        return
    marker = _desktop_integration_marker()
    if marker.exists():
        if _packaged_app_entry_installed():
            _remove_generated_app_entry()
        _repair_linux_entry_icons()
        return
    try:
        install_linux_desktop_integration(include_startup=True)
    except Exception:  # noqa: BLE001
        return
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1\n", encoding="utf-8")
    except OSError:
        pass


def install_windows_startup_shortcut() -> Path:
    startup_path = startup_entry_path()
    scripts_dir = Path(sys.executable).resolve().parent
    tray_launcher = scripts_dir / "dictate-tray.vbs"
    if not tray_launcher.is_file():
        raise RuntimeError(f"tray launcher not found: {tray_launcher}")
    install_location = scripts_dir.parents[1]
    icon_path = Path(__file__).resolve().parents[2] / "assets" / "dictate.ico"
    wscript = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"
    tray_arguments = f'"{tray_launcher}"'
    script = f"""
$startupDir = {_ps_quote(startup_path.parent)}
$shortcutPath = {_ps_quote(startup_path)}
$targetPath = {_ps_quote(wscript)}
$arguments = {_ps_quote(tray_arguments)}
$workingDirectory = {_ps_quote(install_location)}
$iconPath = {_ps_quote(icon_path)}
New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.Arguments = $arguments
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
        "Comment=Dictate into the focused app",
        f"Exec={exec_path}",
        f"Icon={_linux_icon_path()}",
        "Type=Application",
        "Categories=AudioVideo;Audio;",
        "Keywords=voice;speech;transcription;dictation;asr;whisper;canary;",
        "Terminal=false",
        "StartupWMClass=dictate-ui-shell",
    ]
    if autostart:
        lines.append("X-GNOME-Autostart-enabled=true")
    return "\n".join(lines) + "\n"


def _linux_exec_path() -> str:
    # The installed (.deb/AppImage) engine runs as a PyInstaller sidecar of the
    # Tauri shell, so there is no `dictate` console script on PATH — only
    # `dictate-ui-shell`, which spawns this engine. Autostart/launch the shell.
    if getattr(sys, "frozen", False):
        shell = shutil.which("dictate-ui-shell")
        if shell:
            return shell
    return (
        shutil.which("dictate")
        or shutil.which("dictate-ui-shell")
        or str(Path.home() / ".local" / "bin" / "dictate")
    )


_FALLBACK_ICON = "microphone-sensitivity-high-symbolic"
# Theme icon name the .deb/AppImage installs under hicolor (Tauri names it after
# the binary). The frozen engine has no assets/ dir, so without this it fell
# back to the generic symbolic mic and shadowed the packaged launcher's icon.
_PACKAGED_ICON = "dictate-ui-shell"


def _packaged_icon_installed() -> bool:
    data_dirs = [os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")]
    data_dirs += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return any(
        any((Path(base) / "icons" / "hicolor").glob(f"*/apps/{_PACKAGED_ICON}.png"))
        for base in data_dirs
        if base
    )


# Desktop ID the .deb installs its launcher under (Tauri names it after productName).
_PACKAGED_APP_ENTRY = "Dictate.desktop"
_GENERATED_ENTRY_MARK = "Comment=Dictate into the focused app\n"


def _packaged_app_entry_installed() -> bool:
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return any(
        (Path(base) / "applications" / _PACKAGED_APP_ENTRY).is_file() for base in data_dirs if base
    )


def _remove_generated_app_entry() -> None:
    """Delete the user launcher only if Dictate wrote it, never a hand-made one."""
    path = app_entry_path()
    try:
        if _GENERATED_ENTRY_MARK in path.read_text(encoding="utf-8"):
            path.unlink()
    except OSError:
        pass


def _repair_linux_entry_icons() -> None:
    """Rewrite the stale fallback icon in entries written by earlier releases.

    Only the Icon= line changes, so a user's disabled autostart stays disabled.
    """
    icon = _linux_icon_path()
    if icon == _FALLBACK_ICON:
        return
    for path in (app_entry_path(), startup_entry_path()):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        stale = f"Icon={_FALLBACK_ICON}\n"
        if stale in content:
            try:
                path.write_text(content.replace(stale, f"Icon={icon}\n"), encoding="utf-8")
            except OSError:
                pass


def _linux_icon_path() -> str:
    if getattr(sys, "frozen", False) and _packaged_icon_installed():
        return _PACKAGED_ICON
    installed_icon = (
        Path.home() / ".local" / "share" / "dictate" / "share" / "icons" / "dictate-simple.png"
    )
    if installed_icon.is_file():
        return str(installed_icon)
    source_icon = Path(__file__).resolve().parents[2] / "assets" / "dictate.png"
    if source_icon.is_file():
        return str(source_icon)
    return _FALLBACK_ICON


def _linux_applications_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "applications"


def _linux_settings_entry_path() -> Path:
    return _linux_applications_dir() / "dictate-settings.desktop"


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
