from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class CloudSyncPrivacyAuditTests(unittest.TestCase):
    def test_audit_script_passes_for_current_repo(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "scripts/cloud_sync_privacy_audit.py"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cloud sync privacy audit passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
