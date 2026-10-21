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
        calver = _load_script("calver")
        self.assertIsNotNone(calver.parse_version(RELEASE_VERSION))
        self.assertEqual(PACKAGE_VERSION, RELEASE_VERSION)

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


class ReleaseNumberTests(unittest.TestCase):
    """N in YYYY.M.N is the release count in the month, not the day."""

    def setUp(self) -> None:
        self.calver = _load_script("calver")
        self.release_check = _load_script("release_check")
        self.october = date(2026, 10, 20)

    def test_tag_patterns_accept_a_count_above_31(self) -> None:
        for check in (self.calver.parse_version, self.release_check.CALVER_RE.fullmatch):
            self.assertTrue(check("2026.10.32"))
            self.assertTrue(check("2026.9.25-1"))
        self.assertEqual(self.calver.parse_version("v2026.10.32"), (2026, 10, 32, 0))

    def test_tag_patterns_refuse_zero_and_leading_zeros(self) -> None:
        for value in ("2026.10.0", "2026.01.5", "2026.13.1", "2026.10.05", "2026.10.3-0"):
            with self.subTest(value=value):
                self.assertIsNone(self.calver.parse_version(value))
                self.assertIsNone(self.release_check.CALVER_RE.fullmatch(value))

    def test_next_version_counts_releases_in_the_month(self) -> None:
        next_version = self.calver.next_version
        self.assertEqual(next_version(["v2026.10.20"], self.october), "2026.10.21")
        self.assertEqual(next_version(["v2026.10.31", "v2026.10.9"], self.october), "2026.10.32")
        self.assertEqual(next_version(["v2026.10.32"], date(2026, 11, 1)), "2026.11.1")
        self.assertEqual(next_version([], self.october), "2026.10.1")

    def test_next_version_ignores_prereleases_and_continues_old_day_numbers(self) -> None:
        tags = ["v2026.9.25", "v2026.9.25-4", "v2026.9.27", "v2026.9.25-unstable.70.1", "latest"]
        self.assertEqual(self.calver.next_version(tags, date(2026, 9, 30)), "2026.9.28")

    def test_require_next_refuses_a_skipped_number_and_the_wrong_month(self) -> None:
        tags = ["v2026.10.1", "v2026.10.2"]
        self.calver.require_next("2026.10.3", tags, self.october)
        for version in ("2026.10.4", "2026.10.2", "2026.10.20", "2026.11.3", "2026.9.3"):
            with self.subTest(version=version):
                with self.assertRaises(self.calver.ReleaseVersionError):
                    self.calver.require_next(version, tags, self.october)

    def test_require_next_allows_a_correction_of_the_latest_release_only(self) -> None:
        tags = ["v2026.10.1", "v2026.10.2", "v2026.10.2-1"]
        self.calver.require_next("2026.10.2-2", tags, self.october)
        for version in ("2026.10.2-1", "2026.10.1-1"):
            with self.subTest(version=version):
                with self.assertRaises(self.calver.ReleaseVersionError):
                    self.calver.require_next(version, tags, self.october)

    def test_versions_sort_as_numbers(self) -> None:
        tags = ["v2026.10.32", "v2026.10.9", "v2026.9.30", "v2026.10.9-1"]
        self.assertEqual(
            self.calver.stable_versions(tags),
            [(2026, 9, 30, 0), (2026, 10, 9, 0), (2026, 10, 9, 1), (2026, 10, 32, 0)],
        )

    def test_msi_version_keeps_the_count(self) -> None:
        sync_release_version = _load_script("sync_release_version")
        self.assertEqual(sync_release_version._msi_safe_version("2026.10.32"), "26.10.32.0")

    def test_msi_version_of_a_beta_and_a_correction(self) -> None:
        # A beta takes its final's MSI version; a correction goes in the
        # fourth field (docs/release-versioning.md).
        msi = _load_script("sync_release_version")._msi_safe_version
        self.assertEqual(msi("2026.10.3-beta.2"), "26.10.3.0")
        self.assertEqual(msi("2026.10.3-1"), "26.10.3.1")


class BetaVersionTests(unittest.TestCase):
    """Betas are YYYY.M.N-beta.B, pre-releases of the upcoming stable YYYY.M.N."""

    def setUp(self) -> None:
        self.calver = _load_script("calver")
        self.release_check = _load_script("release_check")
        self.october = date(2026, 10, 20)
        self.tags = ["v2026.10.1", "v2026.10.2", "v2026.10.3-unstable.71.1"]

    def test_beta_tags_parse_but_are_not_stable_versions(self) -> None:
        release = self.calver.parse_release("v2026.10.3-beta.2")
        self.assertEqual(release.base, "2026.10.3")
        self.assertEqual(release.channel, "beta")
        self.assertEqual(release.npm_dist_tag, "beta")
        self.assertEqual(release.pep440, "2026.10.3b2")
        self.assertIsNone(self.calver.parse_version("2026.10.3-beta.2"))
        self.assertTrue(self.release_check.CALVER_RE.fullmatch("2026.10.3-beta.2"))
        for value in ("2026.10.3-beta.0", "2026.10.3-beta", "2026.10.3-beta.01", "2026.10.3-rc.1"):
            with self.subTest(value=value):
                self.assertIsNone(self.calver.parse_release(value))
                self.assertIsNone(self.release_check.CALVER_RE.fullmatch(value))

    def test_corrections_keep_their_form(self) -> None:
        release = self.calver.parse_release("v2026.10.2-1")
        self.assertEqual(release.channel, "correction")
        self.assertEqual(release.npm_dist_tag, "latest")
        self.assertEqual(release.pep440, "2026.10.2.post1")

    def test_betas_do_not_count_as_releases_of_the_month(self) -> None:
        tags = self.tags + ["v2026.10.3-beta.1", "v2026.10.3-beta.2"]
        self.assertEqual(self.calver.next_version(tags, self.october), "2026.10.3")

    def test_next_beta_counts_betas_of_the_base(self) -> None:
        next_beta = self.calver.next_beta
        self.assertEqual(next_beta("2026.10.3", self.tags), "2026.10.3-beta.1")
        tags = self.tags + ["v2026.10.3-beta.1", "v2026.10.3-beta.9", "v2026.10.4-beta.12"]
        self.assertEqual(next_beta("2026.10.3", tags), "2026.10.3-beta.10")
        self.assertEqual(next_beta("2026.10.4", tags), "2026.10.4-beta.13")

    def test_plan_gives_the_next_tag_for_each_channel(self) -> None:
        plan = self.calver.plan
        tags = self.tags + ["v2026.10.3-beta.1"]
        beta = plan("beta", "2026.10.3", tags, self.october)
        self.assertEqual(beta.describe()["tag"], "v2026.10.3-beta.2")
        self.assertEqual(beta.describe()["npmDistTag"], "beta")
        self.assertTrue(beta.describe()["prerelease"])
        stable = plan("stable", "2026.10.3", tags, self.october)
        self.assertEqual(stable.describe()["tag"], "v2026.10.3")
        self.assertEqual(stable.describe()["npmDistTag"], "latest")
        correction = plan("correction", "2026.10.2", tags, self.october)
        self.assertEqual(correction.describe()["tag"], "v2026.10.2-1")
        self.assertEqual(correction.describe()["channel"], "correction")

    def test_plan_refuses_a_base_that_is_not_next(self) -> None:
        plan = self.calver.plan
        error = self.calver.ReleaseVersionError
        cases = (
            ("beta", "2026.10.2"),  # already released
            ("beta", "2026.10.5"),  # skips 2026.10.3
            ("stable", "2026.10.2"),
            ("correction", "2026.10.1"),  # not the latest release
            ("correction", "2026.10.3"),  # not released yet
            ("beta", "2026.10.3-beta.1"),  # the files hold a stable base
            ("nightly", "2026.10.3"),
        )
        for channel, base in cases:
            with self.subTest(channel=channel, base=base):
                with self.assertRaises(error):
                    plan(channel, base, self.tags, self.october)

    def test_require_next_checks_the_beta_number(self) -> None:
        tags = self.tags + ["v2026.10.3-beta.1"]
        self.calver.require_next("2026.10.3-beta.2", tags, self.october)
        for version in ("2026.10.3-beta.1", "2026.10.3-beta.3", "2026.10.4-beta.1"):
            with self.subTest(version=version):
                with self.assertRaises(self.calver.ReleaseVersionError):
                    self.calver.require_next(version, tags, self.october)

    def test_pep440_order(self) -> None:
        order = [
            "2026.10.1-beta.1",
            "2026.10.1-beta.2",
            "2026.10.1",
            "2026.10.1-1",
            "2026.10.2-beta.1",
        ]
        keys = [self.calver.parse_release(value).order_key() for value in order]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(self.calver.newest(reversed(order)), "2026.10.2-beta.1")
        self.assertEqual(self.calver.newest(["2026.10.1-beta.2", "2026.10.1-1"]), "2026.10.1-1")
        self.assertEqual(self.calver.newest(["2026.10.1-beta.10", "2026.10.1-beta.9"]), "2026.10.1-beta.10")
        self.assertIsNone(self.calver.newest(["latest", ""]))

    def test_pep440_strings_match_the_packaging_library(self) -> None:
        try:
            from packaging.version import Version
        except ImportError:  # pragma: no cover - packaging ships with the dev tools
            self.skipTest("packaging is not installed")
        order = ["2026.10.1-beta.1", "2026.10.1-beta.2", "2026.10.1", "2026.10.1-1", "2026.10.2-beta.1"]
        parsed = [Version(value) for value in order]
        self.assertEqual(parsed, sorted(parsed))
        for value in order:
            with self.subTest(value=value):
                self.assertEqual(str(Version(value)), self.calver.parse_release(value).pep440)

    def test_sync_release_version_stamps_a_beta_on_every_version_file(self) -> None:
        sync_release_version = _load_script("sync_release_version")
        changes = sync_release_version._planned_changes("2026.10.3-beta.2")
        changed = {path.relative_to(ROOT).as_posix() for path, before, after in changes if before != after}
        self.assertIn("package.json", changed)
        self.assertIn("src/dictate/version.py", changed)
        tauri = next(after for path, _, after in changes if path.name == "tauri.conf.json")
        self.assertIn('"version": "2026.10.3-beta.2"', tauri)
        self.assertIn('"version": "26.10.3.0"', tauri)


if __name__ == "__main__":
    unittest.main()
