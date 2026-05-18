"""Diagnostic command for validating dictate runtime health."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from dictate.config import CONFIG_PATH, load_config
from dictate.preflight import run_preflight
from dictate.runtime_logging import (
    FALLBACK_LOG_DIR,
    LOG_DIR,
    resolve_log_paths,
)
from dictate.stt import (
    GEMINI_MODELS,
    OPENAI_MODELS,
    STT_BACKENDS,
    XAI_MODELS,
    create_speech_to_text,
    resolve_model_name,
)
from dictate.startup import (
    app_entry_path,
    install_linux_desktop_integration,
    settings_entry_path,
    startup_entry_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose dictate environment and runtime health")
    parser.add_argument(
        "--stt-backend",
        choices=STT_BACKENDS,
        default="faster-whisper",
        help="STT backend to diagnose",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model name override for diagnosis. "
            "local example: turbo. "
            f"openai examples: {', '.join(OPENAI_MODELS)}. "
            f"xai examples: {', '.join(XAI_MODELS)}. "
            f"gemini examples: {', '.join(GEMINI_MODELS)}."
        ),
    )
    parser.add_argument(
        "--device",
        choices=["cpu", "cuda", "auto"],
        default="auto",
        help="Compute device to validate",
    )
    parser.add_argument(
        "--type-backend",
        choices=["auto", "xdotool", "wtype", "ydotool", "pynput"],
        default="auto",
        help="Typing backend to validate",
    )
    parser.add_argument(
        "--push-to-talk-combo",
        default="ctrl_r",
        help="Push-to-talk combo to validate",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Skip model load check (faster; suitable for install-time verification)",
    )
    parser.add_argument(
        "--check-model-load",
        action="store_true",
        help="Force model instantiation check (may download model files)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe local repairs such as creating config/log directories and Windows shortcuts",
    )
    parser.add_argument(
        "--update-paths",
        action="store_true",
        help="Print supported update/install commands for this platform",
    )
    return parser


def run_doctor(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    model_name = resolve_model_name(args.stt_backend, args.model)
    config = load_config()
    if args.stt_backend == "openai" and config.openai_api_key_command:
        os.environ.setdefault("DICTATE_OPENAI_API_KEY_COMMAND", config.openai_api_key_command)
    if args.stt_backend == "xai" and config.xai_api_key_command:
        os.environ.setdefault("DICTATE_XAI_API_KEY_COMMAND", config.xai_api_key_command)
    if args.stt_backend == "gemini" and config.gemini_api_key_command:
        os.environ.setdefault("DICTATE_GEMINI_API_KEY_COMMAND", config.gemini_api_key_command)

    report = run_preflight(
        require_typing=True,
        require_clipboard=False,
        typing_backend=args.type_backend,
        push_to_talk_combo=args.push_to_talk_combo,
        stt_backend=args.stt_backend,
        stt_model=model_name,
        stt_device=args.device,
    )

    if args.fix:
        _apply_safe_fixes(report)
    _check_runtime_paths(report)

    should_check_model_load = args.check_model_load or not args.quick
    if should_check_model_load:
        _check_model_load(
            report,
            backend=args.stt_backend,
            model_name=model_name,
            device=args.device,
        )

    fixes = _fix_items(report)
    updates = _update_paths() if args.update_paths else []
    _print_report(report, fixes=fixes, updates=updates)
    return 0 if report.ok else 2


def _check_runtime_paths(report) -> None:  # noqa: ANN001
    desktop_path = _desktop_entry_path()
    if desktop_path.exists():
        report.notes.append(f"Desktop entry: {desktop_path}")
    else:
        report.warnings.append(f"Desktop entry not found: {desktop_path}")
    settings_path = settings_entry_path()
    if settings_path.exists():
        report.notes.append(f"Settings entry: {settings_path}")
    else:
        report.warnings.append(f"Settings entry not found: {settings_path}")
    startup_path = startup_entry_path()
    if startup_path.exists():
        report.notes.append(f"Startup entry: {startup_path}")
    else:
        report.warnings.append(f"Startup entry not found: {startup_path}")

    primary_log_writable = False
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        test_path = LOG_DIR / ".write-test"
        with test_path.open("w", encoding="utf-8") as handle:
            handle.write("ok")
        test_path.unlink(missing_ok=True)
        report.notes.append(f"Log directory writable: {LOG_DIR}")
        primary_log_writable = True
    except Exception as exc:  # noqa: BLE001
        report.warnings.append(f"Log directory is not writable ({LOG_DIR}): {exc}")

    active_log_paths = resolve_log_paths()
    if active_log_paths is None:
        report.errors.append("No writable log directory available.")
        return

    latest_log_path, last_failure_log_path = active_log_paths
    report.notes.append(f"Active log directory: {latest_log_path.parent}")
    if latest_log_path.exists():
        report.notes.append(f"Latest startup log: {latest_log_path}")
    if last_failure_log_path.exists():
        report.notes.append(f"Last failure log: {last_failure_log_path}")
    if not primary_log_writable and latest_log_path.parent == FALLBACK_LOG_DIR:
        report.warnings.append(f"Using fallback log directory: {FALLBACK_LOG_DIR}")


def _check_model_load(report, *, backend: str, model_name: str, device: str) -> None:  # noqa: ANN001
    stt = None
    try:
        stt = create_speech_to_text(
            backend=backend,  # type: ignore[arg-type]
            model=model_name,
            device=device,  # type: ignore[arg-type]
        )
        _ = stt.model
        report.notes.append(
            f"Model load OK: backend='{backend}' model='{model_name}' device='{device}'"
        )
    except Exception as exc:  # noqa: BLE001
        report.errors.append(
            f"Model load failed for backend='{backend}' model='{model_name}' on '{device}': {exc}"
        )
    finally:
        if stt is not None:
            try:
                stt.release()
            except Exception as exc:  # noqa: BLE001
                report.warnings.append(f"Model release failed: {exc}")


def _apply_safe_fixes(report) -> None:  # noqa: ANN001
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        report.notes.append(f"Ensured log directory exists: {LOG_DIR}")
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"Could not create log directory {LOG_DIR}: {exc}")

    try:
        _seed_config_if_missing()
        report.notes.append(f"Ensured config file exists: {CONFIG_PATH}")
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"Could not seed config file {CONFIG_PATH}: {exc}")

    if sys.platform.startswith("win"):
        try:
            _install_windows_shortcuts()
            report.notes.append("Ensured Windows Start Menu, startup, and Installed Apps entries exist.")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Could not install Windows shortcuts/app registration: {exc}")
    else:
        try:
            _install_linux_desktop_entry()
            report.notes.append("Ensured Linux app launcher and startup entries exist.")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"Could not install Linux app launcher/startup entries: {exc}")


def _seed_config_if_missing() -> None:
    if CONFIG_PATH.exists():
        return
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    default_config = Path(__file__).resolve().parents[2] / "config" / "default-config.yaml"
    if default_config.is_file():
        shutil.copyfile(default_config, CONFIG_PATH)
        return
    CONFIG_PATH.write_text(
        "push_to_talk_combo: ctrl_r\n"
        "stt_backend: faster-whisper\n"
        "stt_model: turbo\n"
        "stt_device: auto\n"
        "stt_compute_type: int8\n",
        encoding="utf-8",
    )


def _install_windows_shortcuts() -> None:
    scripts_dir = Path(sys.executable).resolve().parent
    tray_launcher = scripts_dir / "dictate-tray.vbs"
    controls_launcher = scripts_dir / "dictate-controls.exe"
    if not tray_launcher.is_file():
        raise RuntimeError(f"tray launcher not found: {tray_launcher}")
    if not controls_launcher.is_file():
        raise RuntimeError(f"controls launcher not found: {controls_launcher}")

    programs_dir = _desktop_entry_path().parent
    startup_dir = programs_dir / "Startup"
    icon_path = Path(__file__).resolve().parents[2] / "assets" / "dictate-controls.ico"
    install_location = scripts_dir.parents[1]
    uninstall_script = install_location / "uninstall-windows.ps1"
    script = f"""
$programsDir = {_ps_quote(programs_dir)}
$startupDir = {_ps_quote(startup_dir)}
$installLocation = {_ps_quote(install_location)}
$displayIcon = {_ps_quote(icon_path)}
$uninstallScript = {_ps_quote(uninstall_script)}
New-Item -ItemType Directory -Force -Path $programsDir | Out-Null
New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $programsDir 'Dictate.lnk'))
$shortcut.TargetPath = {_ps_quote(tray_launcher)}
$shortcut.WorkingDirectory = $installLocation
$shortcut.Description = 'Start Dictate push-to-talk tray'
if (Test-Path $displayIcon) {{ $shortcut.IconLocation = $displayIcon }}
$shortcut.Save()
$controls = $shell.CreateShortcut((Join-Path $programsDir 'Dictate Controls.lnk'))
$controls.TargetPath = {_ps_quote(controls_launcher)}
$controls.WorkingDirectory = $installLocation
$controls.Description = 'Open Dictate configuration and recent history'
if (Test-Path $displayIcon) {{ $controls.IconLocation = $displayIcon }}
$controls.Save()
$startup = $shell.CreateShortcut((Join-Path $startupDir 'Dictate.lnk'))
$startup.TargetPath = {_ps_quote(tray_launcher)}
$startup.WorkingDirectory = $installLocation
$startup.Description = 'Start Dictate automatically at sign-in'
if (Test-Path $displayIcon) {{ $startup.IconLocation = $displayIcon }}
$startup.Save()
$keyPath = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Dictate'
New-Item -Force -Path $keyPath | Out-Null
New-ItemProperty -Force -Path $keyPath -Name 'DisplayName' -Value 'Dictate' -PropertyType String | Out-Null
New-ItemProperty -Force -Path $keyPath -Name 'DisplayVersion' -Value '2026.5.18' -PropertyType String | Out-Null
New-ItemProperty -Force -Path $keyPath -Name 'Publisher' -Value 'Arc Forge Labs' -PropertyType String | Out-Null
New-ItemProperty -Force -Path $keyPath -Name 'InstallLocation' -Value $installLocation -PropertyType String | Out-Null
if (Test-Path $displayIcon) {{ New-ItemProperty -Force -Path $keyPath -Name 'DisplayIcon' -Value $displayIcon -PropertyType String | Out-Null }}
if (Test-Path $uninstallScript) {{
    $uninstallCommand = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$uninstallScript`""
    New-ItemProperty -Force -Path $keyPath -Name 'UninstallString' -Value $uninstallCommand -PropertyType String | Out-Null
    New-ItemProperty -Force -Path $keyPath -Name 'QuietUninstallString' -Value "$uninstallCommand -Quiet" -PropertyType String | Out-Null
}}
New-ItemProperty -Force -Path $keyPath -Name 'NoModify' -Value 1 -PropertyType DWord | Out-Null
New-ItemProperty -Force -Path $keyPath -Name 'NoRepair' -Value 1 -PropertyType DWord | Out-Null
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
    )


def _ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _install_linux_desktop_entry() -> None:
    install_linux_desktop_integration(include_startup=True)


def _fix_items(report) -> list[str]:  # noqa: ANN001
    items: list[str] = []
    for warning in report.warnings:
        if "Desktop entry not found" in warning:
            items.append("Run `dictate doctor --fix` to recreate Start Menu/Desktop launchers.")
        if "Settings entry not found" in warning:
            items.append("Run `dictate doctor --fix` to recreate the Settings launcher.")
        if "Startup entry not found" in warning:
            items.append("Run `dictate doctor --fix` to restore launch-on-startup integration.")
        if "Log directory is not writable" in warning or "fallback log directory" in warning:
            items.append("Run `dictate doctor --fix` to recreate writable log/config directories.")
        if "CUDA" in warning:
            items.append("Use Local / CPU in controls, or install a CUDA-enabled CTranslate2 stack.")
    for error in report.errors:
        if "faster-whisper package is not importable" in error:
            if sys.platform.startswith("win"):
                items.append(
                    "Install or repair the Microsoft Visual C++ runtime, then rerun `dictate doctor`."
                )
            else:
                items.append("Run `./install.sh` or reinstall Dictate with local STT dependencies.")
        if "API key" in error:
            items.append("Open Dictate Controls and save a valid provider API key before selecting it.")
        if "No microphone" in error or "audio devices" in error:
            items.append("Set a default microphone in Windows Sound settings or your desktop audio settings.")
        if "typing backend" in error or "Hotkey backend" in error:
            items.append("Install the platform typing/hotkey dependency, or use `dictate --once`.")
    return _dedupe(items)


def _update_paths() -> list[str]:
    if sys.platform.startswith("win"):
        return [
            'Hosted install/update: powershell -ExecutionPolicy Bypass -Command "iwr -useb https://raw.githubusercontent.com/arcforgelabs/dictate/master/install.ps1 | iex"',
            r"Source checkout update: git pull --ff-only; powershell -ExecutionPolicy Bypass -File .\install-windows.ps1",
            r"Smoke update: powershell -ExecutionPolicy Bypass -File .\install-windows.ps1 -NoPrepareTurbo -NoVerify",
        ]
    return [
        "Source checkout update: git pull --ff-only && ./install.sh",
        "Smoke update: ./install.sh --no-prepare-turbo --no-verify",
    ]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _print_report(report, *, fixes: list[str] | None = None, updates: list[str] | None = None) -> None:  # noqa: ANN001
    print("dictate doctor report", file=sys.stderr)
    for note in report.notes:
        print(f"[OK] {note}", file=sys.stderr)
    for warning in report.warnings:
        print(f"[WARN] {warning}", file=sys.stderr)
    for error in report.errors:
        print(f"[FAIL] {error}", file=sys.stderr)
    for fix in fixes or []:
        print(f"[FIX] {fix}", file=sys.stderr)
    for update in updates or []:
        print(f"[UPDATE] {update}", file=sys.stderr)
    if report.ok:
        print("Result: healthy", file=sys.stderr)
    else:
        print("Result: problems detected", file=sys.stderr)


def _desktop_entry_path() -> Path:
    return app_entry_path()
