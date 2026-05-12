"""Diagnostic command for validating dictate runtime health."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from dictate.preflight import run_preflight
from dictate.runtime_logging import (
    FALLBACK_LOG_DIR,
    LOG_DIR,
    resolve_log_paths,
)
from dictate.stt import (
    NEMO_CANARY_MODELS,
    STT_BACKENDS,
    WHISPER_CPP_MODELS,
    create_speech_to_text,
    resolve_model_name,
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
            "faster-whisper examples: base, turbo, large-v3-turbo. "
            f"nemo-canary examples: {', '.join(NEMO_CANARY_MODELS)}. "
            f"whisper-cpp examples: {', '.join(WHISPER_CPP_MODELS)}."
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
    return parser


def run_doctor(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    model_name = resolve_model_name(args.stt_backend, args.model)

    report = run_preflight(
        require_typing=True,
        require_clipboard=False,
        typing_backend=args.type_backend,
        push_to_talk_combo=args.push_to_talk_combo,
        stt_backend=args.stt_backend,
        stt_model=model_name,
        stt_device=args.device,
    )

    _check_runtime_paths(report)

    should_check_model_load = args.check_model_load or not args.quick
    if should_check_model_load:
        _check_model_load(
            report,
            backend=args.stt_backend,
            model_name=model_name,
            device=args.device,
        )

    _print_report(report)
    return 0 if report.ok else 2


def _check_runtime_paths(report) -> None:  # noqa: ANN001
    desktop_path = _desktop_entry_path()
    if desktop_path.exists():
        report.notes.append(f"Desktop entry: {desktop_path}")
    else:
        report.warnings.append(f"Desktop entry not found: {desktop_path}")

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


def _print_report(report) -> None:  # noqa: ANN001
    print("dictate doctor report", file=sys.stderr)
    for note in report.notes:
        print(f"[OK] {note}", file=sys.stderr)
    for warning in report.warnings:
        print(f"[WARN] {warning}", file=sys.stderr)
    for error in report.errors:
        print(f"[FAIL] {error}", file=sys.stderr)
    if report.ok:
        print("Result: healthy", file=sys.stderr)
    else:
        print("Result: problems detected", file=sys.stderr)


def _desktop_entry_path() -> Path:
    if sys.platform.startswith("win"):
        start_menu = os.environ.get("APPDATA")
        if start_menu:
            return (
                Path(start_menu)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
                / "Dictate.lnk"
            )
        return (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Dictate.lnk"
        )
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / "applications" / "dictate.desktop"
