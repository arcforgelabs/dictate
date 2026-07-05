from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class CloudSyncVolumeSmokeTests(unittest.TestCase):
    def test_volume_smoke_passes_for_current_repo(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/cloud_sync_volume_smoke.py"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cloud sync volume smoke passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
