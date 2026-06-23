from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from dictate.process_lock import ProcessLock


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


if __name__ == "__main__":
    unittest.main()
