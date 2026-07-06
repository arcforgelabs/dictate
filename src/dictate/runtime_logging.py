"""Startup logging helpers for GUI/launcher-friendly diagnostics."""

from __future__ import annotations

import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dictate.platform_paths import fallback_log_dir, user_data_dir

LOG_DIR = user_data_dir() / "logs"
LATEST_LOG_PATH = LOG_DIR / "latest.log"
LAST_FAILURE_LOG_PATH = LOG_DIR / "last_failure.log"
FALLBACK_LOG_DIR = fallback_log_dir()


class _TeeStderr:
    """Mirror stderr output to both terminal and log file."""

    def __init__(self, primary: Any, secondary: Any):
        self.primary = primary
        self.secondary = secondary

    def write(self, data: str) -> int:
        if self.primary is not None:
            self.primary.write(data)
        self.secondary.write(data)
        # Keep startup diagnostics on disk even if the process is terminated abruptly.
        self.secondary.flush()
        return len(data)

    def flush(self) -> None:
        if self.primary is not None:
            self.primary.flush()
        self.secondary.flush()

    def isatty(self) -> bool:
        return bool(self.primary is not None and getattr(self.primary, "isatty", lambda: False)())


def run_with_startup_logging(main_fn: Callable[[], int]) -> int:
    """Run CLI entrypoint with stderr mirrored to a persistent log file."""
    original_stderr = sys.stderr
    log_paths = resolve_log_paths()
    if log_paths is None:
        return _run_main(main_fn)

    latest_log_path, last_failure_log_path = log_paths

    with latest_log_path.open("w", encoding="utf-8", buffering=1) as log_file:
        sys.stderr = _TeeStderr(original_stderr, log_file)
        _write_header()
        exit_code = 0
        try:
            result = main_fn()
            exit_code = int(result) if result is not None else 0
            return exit_code
        except SystemExit as exc:
            exit_code = _normalize_system_exit_code(exc.code)
            return exit_code
        except Exception:  # noqa: BLE001
            exit_code = 1
            traceback.print_exc(file=sys.stderr)
            return exit_code
        finally:
            print(f"dictate: exit code {exit_code}", file=sys.stderr)
            sys.stderr.flush()
            sys.stderr = original_stderr
            if exit_code != 0:
                shutil.copyfile(latest_log_path, last_failure_log_path)


def resolve_log_paths() -> tuple[Path, Path] | None:
    """Choose a writable log directory, with fallback to /tmp."""
    for base_dir in (LOG_DIR, FALLBACK_LOG_DIR):
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            test_path = base_dir / ".write-test"
            with test_path.open("w", encoding="utf-8") as handle:
                handle.write("ok")
            test_path.unlink(missing_ok=True)
            return (base_dir / "latest.log", base_dir / "last_failure.log")
        except Exception:  # noqa: BLE001
            continue
    return None


def _run_main(main_fn: Callable[[], int]) -> int:
    """Run main function without logging fallback."""
    try:
        result = main_fn()
        return int(result) if result is not None else 0
    except SystemExit as exc:
        return _normalize_system_exit_code(exc.code)
    except Exception:  # noqa: BLE001
        if sys.stderr is not None:
            traceback.print_exc(file=sys.stderr)
        return 1


def _write_header() -> None:
    now = datetime.now(timezone.utc).astimezone()
    timestamp = now.isoformat(timespec="seconds")
    print(f"dictate: startup at {timestamp}", file=sys.stderr)
    print(f"dictate: argv={sys.argv[1:]}", file=sys.stderr)


def _normalize_system_exit_code(code: object) -> int:
    if isinstance(code, int):
        return code
    if code is None:
        return 0
    return 1
