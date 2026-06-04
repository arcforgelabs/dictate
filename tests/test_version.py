from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import date

from dictate.version import PACKAGE_VERSION, RELEASE_VERSION


class VersionTests(unittest.TestCase):
    def test_release_and_package_versions_are_calver(self) -> None:
        self.assertRegex(RELEASE_VERSION, r"^\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?$")
        date_part, _, sequence = RELEASE_VERSION.partition("-")
        year, month, day = [int(part) for part in date_part.split(".")]

        self.assertEqual(date(year, month, day).isoformat(), f"{year:04d}-{month:02d}-{day:02d}")
        self.assertEqual(PACKAGE_VERSION, RELEASE_VERSION)
        if sequence:
            self.assertGreaterEqual(int(sequence), 1)

    def test_calver_script_generates_release_and_pep440_versions(self) -> None:
        date_part, separator, sequence = RELEASE_VERSION.partition("-")
        year, month, day = [int(part) for part in date_part.split(".")]
        iso_date = f"{year:04d}-{month:02d}-{day:02d}"
        sequence_value = sequence if separator else "0"
        release = subprocess.check_output(
            [
                sys.executable,
                "scripts/calver.py",
                "--date",
                iso_date,
                "--sequence",
                sequence_value,
            ],
            text=True,
        ).strip()
        pep440 = subprocess.check_output(
            [
                sys.executable,
                "scripts/calver.py",
                "--date",
                iso_date,
                "--sequence",
                sequence_value,
                "--format",
                "pep440",
            ],
            text=True,
        ).strip()

        self.assertEqual(release, RELEASE_VERSION)
        self.assertEqual(pep440, PACKAGE_VERSION)

    def test_sync_release_version_accepts_current_version(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/sync_release_version.py",
                RELEASE_VERSION,
                "--check",
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

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
