from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
import importlib.util
import sys

from dictate.version import PACKAGE_VERSION, RELEASE_VERSION


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


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
        sequence_value = int(sequence) if separator else 0
        calver = _load_script("calver")
        release = calver.release_version(date(year, month, day), sequence=sequence_value)
        pep440 = calver.pep440_version(date(year, month, day), sequence=sequence_value)

        self.assertEqual(release, RELEASE_VERSION)
        self.assertEqual(pep440, PACKAGE_VERSION)

    def test_sync_release_version_accepts_current_version(self) -> None:
        sync_release_version = _load_script("sync_release_version")
        stale = [
            str(path.relative_to(ROOT))
            for path, before, after in sync_release_version._planned_changes(RELEASE_VERSION)
            if before != after
        ]

        self.assertEqual(stale, [])

    def test_release_check_accepts_current_tag(self) -> None:
        release_check = _load_script("release_check")
        expected = release_check._normalize_tag(f"v{RELEASE_VERSION}")
        repo_root = ROOT
        pyproject_version = release_check._read_pyproject_version(repo_root / "pyproject.toml")
        npm_version = release_check._read_package_json_version(repo_root / "package.json")
        version_values = release_check._read_version_module(
            repo_root / "src" / "dictate" / "version.py"
        )

        self.assertEqual(expected, RELEASE_VERSION)
        self.assertEqual(pyproject_version, expected)
        self.assertEqual(npm_version, expected)
        self.assertEqual(version_values["RELEASE_VERSION"], expected)
        self.assertEqual(version_values["PACKAGE_VERSION"], expected)


if __name__ == "__main__":
    unittest.main()
