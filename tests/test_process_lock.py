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


if __name__ == "__main__":
    unittest.main()
