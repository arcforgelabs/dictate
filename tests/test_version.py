from __future__ import annotations

import subprocess
import sys
import unittest

from dictate.version import PACKAGE_VERSION, RELEASE_VERSION


class VersionTests(unittest.TestCase):
    def test_release_and_package_versions_are_calver(self) -> None:
        self.assertEqual(RELEASE_VERSION, "2026.6.2")
        self.assertEqual(PACKAGE_VERSION, "2026.6.2")

    def test_calver_script_generates_release_and_pep440_versions(self) -> None:
        release = subprocess.check_output(
            [
                sys.executable,
                "scripts/calver.py",
                "--date",
                "2026-06-02",
                "--sequence",
                "0",
            ],
            text=True,
        ).strip()
        pep440 = subprocess.check_output(
            [
                sys.executable,
                "scripts/calver.py",
                "--date",
                "2026-06-02",
                "--sequence",
                "0",
                "--format",
                "pep440",
            ],
            text=True,
        ).strip()

        self.assertEqual(release, RELEASE_VERSION)
        self.assertEqual(pep440, PACKAGE_VERSION)

    def test_release_check_accepts_current_tag(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/release_check.py",
                "--tag",
                f"v{RELEASE_VERSION}",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
