"""Single-instance lock for Dictate daemon modes."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from dictate.platform_paths import user_data_dir

_STALE_GRACE_SECONDS = 30.0


class ProcessLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._owned = False

    def acquire(self) -> bool:
        try:
            self.path.mkdir(parents=True)
        except OSError:
            if self._is_live_lock():
                return False
            self._break_stale_lock()
            try:
                self.path.mkdir(parents=True)
            except OSError:
                return False
        try:
            (self.path / "pid").write_text(str(os.getpid()))
            (self.path / "started").write_text(str(time.time()))
        except OSError:
            pass
        self._owned = True
        return True

    def release(self) -> None:
        if not self._owned:
            return
        self._break_stale_lock()
        self._owned = False

    def _is_live_lock(self) -> bool:
        pid = _read_pid(self.path / "pid")
        if pid is not None and _pid_is_running(pid):
            return True
        return _lock_age_seconds(self.path / "started") < _STALE_GRACE_SECONDS

    def _break_stale_lock(self) -> None:
        for child in ("pid", "started"):
            try:
                (self.path / child).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        try:
            self.path.rmdir()
        except OSError:
            pass


def daemon_lock_path() -> Path:
    if sys.platform.startswith("win"):
        return user_data_dir() / "dictate-daemon.lockdir"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "dictate-daemon.lockdir"
    return Path(tempfile.gettempdir()) / f"dictate-daemon-{os.getuid()}.lockdir"


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
        return int(text)
    except (OSError, ValueError):
        return None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_age_seconds(path: Path) -> float:
    try:
        started = float(path.read_text().strip())
    except (OSError, ValueError):
        return float("inf")
    return max(0.0, time.time() - started)
