"""Single-instance lock for Dictate daemon modes."""

from __future__ import annotations

import os
import signal
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


def stop_running_daemon(*, timeout: float = 10.0) -> tuple[bool, str]:
    """Stop a running Dictate daemon found via its single-instance lock.

    Returns ``(stopped, message)``. ``stopped`` is True when no live daemon
    remains afterwards — either none was running, or it was signalled to exit.
    Used by installers/updaters so a new engine can claim the lock cleanly
    instead of colliding with a stale one. Targets the engine daemon (the lock
    holder); the desktop shell is handled separately by the package scripts.
    """
    pid = _read_pid(daemon_lock_path() / "pid")
    if pid is None or not _pid_is_running(pid):
        return (True, "no running Dictate daemon")

    if sys.platform == "win32":
        import subprocess

        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return (True, "daemon already exited")
        except OSError as exc:
            return (False, f"could not signal Dictate daemon (pid {pid}): {exc}")
        deadline = time.time() + timeout
        while time.time() < deadline and _pid_is_running(pid):
            time.sleep(0.2)
        if _pid_is_running(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            time.sleep(0.3)

    if _pid_is_running(pid):
        return (False, f"Dictate daemon (pid {pid}) did not stop")
    return (True, f"stopped Dictate daemon (pid {pid})")


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
    if sys.platform == "win32":
        return _pid_is_running_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_is_running_windows(pid: int) -> bool:
    """Liveness probe for Windows that never sends a console control signal.

    ``os.kill(pid, 0)`` is unsafe here: on Windows ``signal 0`` is
    ``CTRL_C_EVENT``, so it delivers a Ctrl+C to the console process group
    instead of probing — which crashes anything sharing the console (notably
    the test runner). Use OpenProcess + GetExitCodeProcess via ctypes instead.
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access-denied means the process exists but we cannot query it.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return code.value == STILL_ACTIVE
        return True
    finally:
        kernel32.CloseHandle(handle)


def _lock_age_seconds(path: Path) -> float:
    try:
        started = float(path.read_text().strip())
    except (OSError, ValueError):
        return float("inf")
    return max(0.0, time.time() - started)
