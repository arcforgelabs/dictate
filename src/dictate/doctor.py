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
    COMPUTE_DEVICES,
    PARAKEET_DIARIZEN_MODELS,
    PARAKEET_MODELS,
    PARAKEET_PYANNOTE_MODELS,
    PARAKEET_SORTFORMER_MODELS,
    STT_BACKENDS,
    WHISPERX_MODELS,
    create_speech_to_text,
    resolve_default_local_model,
    resolve_model_name,
)
from dictate.startup import (
    app_entry_path,
    install_linux_desktop_integration,
    startup_entry_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose dictate environment and runtime health")
    parser.add_argument(
        "--stt-backend",
        choices=STT_BACKENDS,
        default="parakeet",
        help="STT backend to diagnose (default: parakeet)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model name override for diagnosis. "
            f"parakeet examples: {', '.join(PARAKEET_MODELS)}. "
            "faster-whisper examples: turbo, small. "
            f"parakeet-pyannote examples: {', '.join(PARAKEET_PYANNOTE_MODELS)}. "
            f"parakeet-diarizen examples: {', '.join(PARAKEET_DIARIZEN_MODELS)}. "
            f"parakeet-sortformer examples: {', '.join(PARAKEET_SORTFORMER_MODELS)}. "
            f"whisperx examples: {', '.join(WHISPERX_MODELS)}."
        ),
    )
    parser.add_argument(
        "--device",
        choices=COMPUTE_DEVICES,
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

    if args.stt_backend == "faster-whisper" and not args.model:
        # No explicit --model: check the hardware-aware local default (turbo on
        # capable hardware, small on a weak CPU), consistent with what the daemon runs.
        model_name = resolve_default_local_model(args.device)
    else:
        model_name = resolve_model_name(args.stt_backend, args.model)
    report = run_preflight(
        require_typing=True,
        require_clipboard=True,
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
    desktop_paths = _desktop_entry_paths()
    existing_desktop_path = next((path for path in desktop_paths if path.exists()), None)
    if desktop_path.exists():
        report.notes.append(f"Desktop entry: {desktop_path}")
    elif existing_desktop_path is not None:
        report.notes.append(f"Desktop entry: {existing_desktop_path}")
    else:
        report.warnings.append(f"Desktop entry not found: {desktop_path}")
    startup_path = startup_entry_path()
    if startup_path.exists():
        report.notes.append(f"Startup entry: {startup_path}")
    else:
        report.warnings.append(f"Startup entry not found: {startup_path}")

    stale_checks = [("Desktop entry", existing_desktop_path or desktop_path), ("Startup entry", startup_path)]
    for label, path in stale_checks:
        if path.exists():
            stale_target = _desktop_exec_target_missing(path)
            if stale_target is not None:
                report.warnings.append(
                    f"{label} points to a missing target ({stale_target}); "
                    "it will not launch."
                )

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


def _desktop_exec_target_missing(path) -> str | None:  # noqa: ANN001
    """Return the Exec target of a .desktop file if its binary is missing, else None.

    Catches the legacy/migration case where a pip-era entry points at a removed
    ``~/.local/bin/dictate`` after switching to the packaged app.
    """
    if sys.platform.startswith("win"):
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    target = ""
    for line in lines:
        if line.startswith("Exec="):
            value = line[len("Exec=") :].strip()
            target = value.split()[0] if value else ""
            break
    if not target:
        return None
    resolved = target if os.path.sep in target else shutil.which(target)
    if resolved is None or not Path(resolved).exists():
        return target
    return None


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
    # Leave stt_model UNSET so the hardware-aware resolver picks the local model
    # dynamically at startup (turbo vs small for THIS machine) rather than pinning
    # a doctor-time decision into config.
    CONFIG_PATH.write_text(
        "push_to_talk_combo: ctrl_r\n"
        "stt_backend: faster-whisper\n"
        "stt_device: auto\n"
        "stt_compute_type: int8\n",
        encoding="utf-8",
    )


def _install_windows_shortcuts() -> None:
    scripts_dir = Path(sys.executable).resolve().parent
    tray_launcher = scripts_dir / "dictate-tray.vbs"
    if not tray_launcher.is_file():
        raise RuntimeError(f"tray launcher not found: {tray_launcher}")

    programs_dir = _desktop_entry_path().parent
    startup_dir = programs_dir / "Startup"
    icon_path = Path(__file__).resolve().parents[2] / "assets" / "dictate.ico"
    install_location = scripts_dir.parents[1]
    uninstall_script = install_location / "uninstall-windows.ps1"
    wscript = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wscript.exe"
    tray_arguments = f'"{tray_launcher}"'
    script = f"""
$programsDir = {_ps_quote(programs_dir)}
$startupDir = {_ps_quote(startup_dir)}
$installLocation = {_ps_quote(install_location)}
$displayIcon = {_ps_quote(icon_path)}
$uninstallScript = {_ps_quote(uninstall_script)}
$wscript = {_ps_quote(wscript)}
$trayArguments = {_ps_quote(tray_arguments)}
New-Item -ItemType Directory -Force -Path $programsDir | Out-Null
New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $programsDir 'Dictate.lnk'))
$shortcut.TargetPath = $wscript
$shortcut.Arguments = $trayArguments
$shortcut.WorkingDirectory = $installLocation
$shortcut.Description = 'Start Dictate push-to-talk tray'
if (Test-Path $displayIcon) {{ $shortcut.IconLocation = $displayIcon }}
$shortcut.Save()
Remove-Item -Force -ErrorAction SilentlyContinue -Path (Join-Path $programsDir 'Dictate Controls.lnk')
$startup = $shell.CreateShortcut((Join-Path $startupDir 'Dictate.lnk'))
$startup.TargetPath = $wscript
$startup.Arguments = $trayArguments
$startup.WorkingDirectory = $installLocation
$startup.Description = 'Start Dictate automatically at sign-in'
if (Test-Path $displayIcon) {{ $startup.IconLocation = $displayIcon }}
$startup.Save()
$keyPath = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Dictate'
New-Item -Force -Path $keyPath | Out-Null
New-ItemProperty -Force -Path $keyPath -Name 'DisplayName' -Value 'Dictate' -PropertyType String | Out-Null
New-ItemProperty -Force -Path $keyPath -Name 'DisplayVersion' -Value '2026.9.25-1' -PropertyType String | Out-Null
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
        if "Startup entry not found" in warning:
            items.append("Run `dictate doctor --fix` to restore launch-on-startup integration.")
        if "points to a missing target" in warning:
            items.append(
                "Run `dictate doctor --fix` to repair launcher/startup entries left by a "
                "previous install."
            )
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
            items.append("Open Dictate Settings and save a valid provider API key before selecting it.")
        if "No microphone" in error or "audio devices" in error or "microphone input" in error:
            items.append(
                "Set a default microphone in desktop audio settings, and on Linux ensure "
                "distro libportaudio2 + libpulse0 are installed (Dictate does not bundle PortAudio)."
            )
        if "typing backend" in error or "Hotkey backend" in error:
            items.append("Install the platform typing/hotkey dependency, or use `dictate --once`.")
    return _dedupe(items)


def _update_paths() -> list[str]:
    if sys.platform.startswith("win"):
        return [
            'Developer bootstrap install/update: powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"',
            r"Windows setup wizard: powershell -ExecutionPolicy Bypass -File .\install-windows-wizard.ps1",
            r"Source checkout update: powershell -ExecutionPolicy Bypass -File .\update-windows.ps1",
            r"Source checkout uninstall: powershell -ExecutionPolicy Bypass -File .\uninstall-windows.ps1",
            r"Repair: dictate doctor --quick --fix --type-backend pynput",
            r"Smoke update: powershell -ExecutionPolicy Bypass -File .\update-windows.ps1 -NoPrepareTurbo -NoVerify",
        ]
    return [
        "Source checkout update: ./update.sh",
        "Source checkout uninstall: ./uninstall.sh",
        "Repair: dictate doctor --quick --fix",
        "Smoke update: ./update.sh --no-prepare-turbo --no-verify",
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


def _desktop_entry_paths() -> list[Path]:
    paths = [app_entry_path()]
    if sys.platform.startswith("linux"):
        paths.append(Path("/usr/share/applications/Dictate.desktop"))
    return _unique_paths(paths)


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result
