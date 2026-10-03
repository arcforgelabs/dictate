"""Startup logging helpers for GUI/launcher-friendly diagnostics."""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dictate.platform_paths import fallback_log_dir, is_windows, user_data_dir

LOG_DIR = user_data_dir() / "logs"
LATEST_LOG_PATH = LOG_DIR / "latest.log"
LAST_FAILURE_LOG_PATH = LOG_DIR / "last_failure.log"
FALLBACK_LOG_DIR = fallback_log_dir()

# Where Dictate wrote logs before platform_paths existed (before May 2026). An
# old install can have left logs there even when today's dirs differ because
# XDG_DATA_HOME or TMPDIR is set.
if is_windows():
    LEGACY_LOG_DIRS: tuple[Path, ...] = (Path.home() / ".local" / "share" / "dictate" / "logs",)
else:
    LEGACY_LOG_DIRS = (
        Path.home() / ".local" / "share" / "dictate" / "logs",
        Path("/tmp") / "dictate-logs",
    )
LOG_FILE_NAMES = ("latest.log", "last_failure.log")

# Up to 2026.9.27 a finished dictation or note went to stderr, and so into
# latest.log, as "Typed: <words>" or "Saved note: <words>". Everything after the
# label up to the end of the line is dictated text.
_DICTATED_LINE = re.compile(
    r"\b(?P<label>Typed|Saved note): (?P<text>[^\n]*?)(?P<eol>\r?)(?=\n|\Z)"
)
_REDACTED_TEXT = re.compile(r"\[\d+ characters, not logged\]")


def _redacted(text: str) -> str:
    """What a log holds in place of dictated text: its length, never the words."""
    return f"[{len(text)} characters, not logged]"


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

    def close(self) -> None:
        # Libraries sometimes close sys.stderr at exit. The terminal stream and
        # the log file belong to their owners (run_with_startup_logging closes
        # the log), so only flush.
        self.flush()

    def isatty(self) -> bool:
        return bool(self.primary is not None and getattr(self.primary, "isatty", lambda: False)())


def echo_dictated_text(label: str, text: str) -> None:
    """Show dictated text on an interactive terminal, but never write it to a log.

    stderr is mirrored into ``latest.log``, and when the app is launched from a
    desktop session it is usually captured by the system journal as well. Only a
    real terminal gets the words; everything else gets the length.
    """
    stream = sys.stderr
    if stream is None:
        return
    full = f"\r  {label}: {text}\n"
    redacted = f"\r  {label}: {_redacted(text)}\n"
    if isinstance(stream, _TeeStderr):
        if stream.primary is not None:
            stream.primary.write(full if _is_tty(stream.primary) else redacted)
            stream.primary.flush()
        stream.secondary.write(redacted)
        stream.secondary.flush()
        return
    stream.write(full if _is_tty(stream) else redacted)
    stream.flush()


def _is_tty(stream: Any) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001
        return False


def run_with_startup_logging(main_fn: Callable[[], int]) -> int:
    """Run CLI entrypoint with stderr mirrored to a persistent log file."""
    original_stderr = sys.stderr
    log_paths = resolve_log_paths()
    if log_paths is None:
        return _run_main(main_fn)

    latest_log_path, last_failure_log_path = log_paths
    # Opening latest.log for writing below discards its old contents, so the
    # active one is skipped; every other Dictate log is scrubbed first.
    scrub_warnings = scrub_dictated_text_from_logs(skip=(latest_log_path,))

    with latest_log_path.open("w", encoding="utf-8", buffering=1) as log_file:
        sys.stderr = _TeeStderr(original_stderr, log_file)
        _write_header()
        for warning in scrub_warnings:
            print(warning, file=sys.stderr)
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


def scrub_dictated_text_from_logs(skip: tuple[Path, ...] = ()) -> list[str]:
    """Redact dictated text left in logs by Dictate 2026.9.27 and earlier.

    Rewrites ``Typed: <words>`` and ``Saved note: <words>`` in Dictate's own log
    files to the ``[N characters, not logged]`` form. Redacted lines are left
    alone and a clean file is not rewritten, so this runs on every start and is
    a no-op after the first. Never raises; returns warnings that name the file
    but never quote it.
    """
    warnings: list[str] = []
    seen = {_normalized(path) for path in skip}
    for log_dir in (LOG_DIR, FALLBACK_LOG_DIR, *LEGACY_LOG_DIRS):
        for name in LOG_FILE_NAMES:
            path = log_dir / name
            key = _normalized(path)
            if key in seen:
                continue
            seen.add(key)
            try:
                _scrub_log_file(path)
            except Exception as exc:  # noqa: BLE001
                # Name the failure, never its message: a decode error quotes the bytes.
                if isinstance(exc, OSError) and exc.strerror:
                    reason = exc.strerror
                else:
                    reason = type(exc).__name__
                warnings.append(
                    f"dictate: could not remove dictated text from older log {path}: {reason}"
                )
    return warnings


def redact_dictated_text(content: str) -> str:
    """Return ``content`` with old-format dictated text replaced by its length."""

    def _replace(match: re.Match[str]) -> str:
        text = match.group("text")
        if not text or _REDACTED_TEXT.fullmatch(text):
            return match.group(0)
        return f"{match.group('label')}: {_redacted(text)}{match.group('eol')}"

    return _DICTATED_LINE.sub(_replace, content)


def _scrub_log_file(path: Path) -> bool:
    """Redact one log file in place. Returns True if it was rewritten."""
    try:
        dir_info = os.lstat(path.parent)
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    # Only regular files we own, in a real directory we own. The fallback dir
    # sits in a shared temp dir; following a planted symlink would read, and
    # copy, a file outside Dictate's logs.
    if not stat.S_ISDIR(dir_info.st_mode) or not stat.S_ISREG(info.st_mode):
        return False
    getuid = getattr(os, "getuid", None)
    if getuid is not None and (info.st_uid != getuid() or dir_info.st_uid != getuid()):
        return False

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    # surrogateescape round-trips any non-UTF-8 bytes unchanged.
    read_fd = os.open(path, flags)
    with os.fdopen(read_fd, "r", encoding="utf-8", errors="surrogateescape", newline="") as handle:
        content = handle.read()
    scrubbed = redact_dictated_text(content)
    if scrubbed == content:
        return False

    # Write a sibling and swap it in, so a crash never leaves a half-written log.
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=".scrub-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(
            tmp_fd, "w", encoding="utf-8", errors="surrogateescape", newline=""
        ) as handle:
            handle.write(scrubbed)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return True


def _normalized(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


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
