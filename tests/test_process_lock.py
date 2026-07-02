from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate.process_lock import ProcessLock, _pid_is_running, stop_running_daemon


class ProcessLockTests(unittest.TestCase):
    def test_second_lock_fails_until_first_releases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dictate.lock"
            first = ProcessLock(path)
            second = ProcessLock(path)

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())

            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_recent_stale_lock_still_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dictate.lockdir"
            path.mkdir()
            (path / "pid").write_text("999999999")
            (path / "started").write_text(str(time.time()))

            self.assertFalse(ProcessLock(path).acquire())


class PidLivenessTests(unittest.TestCase):
    def test_current_process_is_running(self) -> None:
        import os

        from dictate.process_lock import _pid_is_running

        self.assertTrue(_pid_is_running(os.getpid()))

    def test_nonpositive_pid_not_running(self) -> None:
        from dictate.process_lock import _pid_is_running

        self.assertFalse(_pid_is_running(0))
        self.assertFalse(_pid_is_running(-1))

    def test_windows_liveness_never_calls_os_kill(self) -> None:
        """Regression: os.kill(pid, 0) on Windows sends CTRL_C_EVENT to the
        console process group (signal 0 == CTRL_C_EVENT), crashing anything
        sharing the console. The Windows path must use OpenProcess instead."""
        from unittest.mock import patch

        import dictate.process_lock as pl

        with patch.object(pl.sys, "platform", "win32"), patch.object(
            pl.os, "kill", side_effect=AssertionError("os.kill must not run on Windows")
        ) as killer, patch.object(pl, "_pid_is_running_windows", return_value=True) as winprobe:
            self.assertTrue(pl._pid_is_running(1234))
            winprobe.assert_called_once_with(1234)
            killer.assert_not_called()


class StopRunningDaemonTests(unittest.TestCase):
    def test_no_lock_reports_nothing_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lockdir = Path(tmp) / "dictate-daemon.lockdir"
            with patch("dictate.process_lock.daemon_lock_path", return_value=lockdir):
                stopped, message = stop_running_daemon()
            self.assertTrue(stopped)
            self.assertIn("no running", message)

    def test_dead_pid_is_treated_as_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lockdir = Path(tmp) / "dictate-daemon.lockdir"
            lockdir.mkdir()
            (lockdir / "pid").write_text("999999999")
            with patch("dictate.process_lock.daemon_lock_path", return_value=lockdir):
                stopped, _ = stop_running_daemon()
            self.assertTrue(stopped)

    @unittest.skipIf(
        sys.platform.startswith("win"),
        "double-fork daemon liveness test is POSIX-only (uses os.fork/os.setsid)",
    )
    def test_live_process_is_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lockdir = Path(tmp) / "dictate-daemon.lockdir"
            lockdir.mkdir()
            pidfile = lockdir / "pid"
            # Spawn a process reparented to init via a double-fork, so when it is
            # signalled it is reaped by init — matching the real daemon, which is
            # never a child of the installer. A direct child of this test would
            # linger as a zombie and falsely read as "still running".
            script = (
                "import os, time\n"
                f"pidfile = {str(pidfile)!r}\n"
                "if os.fork() > 0:\n"
                "    os._exit(0)\n"
                "os.setsid()\n"
                "open(pidfile, 'w').write(str(os.getpid()))\n"
                "time.sleep(30)\n"
            )
            subprocess.run([sys.executable, "-c", script], check=True)

            pid = None
            for _ in range(50):
                try:
                    text = pidfile.read_text().strip()
                except FileNotFoundError:
                    text = ""
                if text:
                    pid = int(text)
                    break
                time.sleep(0.1)
            self.assertIsNotNone(pid, "grandchild never recorded its pid")
            self.addCleanup(self._force_kill, pid)

            with patch("dictate.process_lock.daemon_lock_path", return_value=lockdir):
                stopped, message = stop_running_daemon(timeout=5.0)
            self.assertTrue(stopped, message)
            self.assertFalse(_pid_is_running(pid))

    @staticmethod
    def _force_kill(pid: int) -> None:
        import os
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
