"""A beta .deb must sort before its final in dpkg (docs/release-versioning.md).

dpkg sorts YYYY.M.N-beta.B after YYYY.M.N, so apt would refuse the stable
release over a beta as a downgrade. The .deb carries YYYY.M.N~beta.B instead.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate.update_status import _linux_installed_package_version, is_newer_version, public_version_from_deb


ROOT = Path(__file__).resolve().parents[1]
ORDER = [
    "2026.10.1-beta.1",
    "2026.10.1-beta.2",
    "2026.10.1-beta.10",
    "2026.10.1",
    "2026.10.1-1",
    "2026.10.1-2",
    "2026.10.2-beta.1",
    "2026.10.2",
    "2026.11.1-beta.1",
]


def _calver():
    path = ROOT / "scripts" / "calver.py"
    spec = importlib.util.spec_from_file_location("calver_deb_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _debian(version: str) -> str:
    return _calver().parse_release(version).debian


def _dpkg_lt(left: str, right: str) -> bool:
    return subprocess.run(["dpkg", "--compare-versions", left, "lt", right], check=False).returncode == 0


class DebianVersionMappingTests(unittest.TestCase):
    def test_mapping(self) -> None:
        self.assertEqual(_debian("2026.10.3-beta.1"), "2026.10.3~beta.1")
        self.assertEqual(_debian("2026.10.3-beta.12"), "2026.10.3~beta.12")
        self.assertEqual(_debian("2026.10.3"), "2026.10.3")
        self.assertEqual(_debian("2026.10.3-1"), "2026.10.3-1")

    def test_the_cli_prints_the_mapping(self) -> None:
        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "calver.py"), "debian-version", "2026.10.3-beta.2"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        self.assertEqual(out, "2026.10.3~beta.2")

    def test_the_app_reads_a_deb_version_back_as_the_release_version(self) -> None:
        for version in ORDER:
            with self.subTest(version=version):
                self.assertEqual(public_version_from_deb(_debian(version)), version)
        self.assertEqual(public_version_from_deb("2026.10.3~beta.x"), "2026.10.3~beta.x")

    def test_dpkg_query_answer_is_the_release_version(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout="2026.10.3~beta.1", stderr="")
        with (
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/dpkg-query"),
            patch("dictate.update_status.subprocess.run", return_value=done),
        ):
            installed = _linux_installed_package_version()
        self.assertEqual(installed, "2026.10.3-beta.1")
        # The in-app updater then offers the final over the installed beta.
        self.assertTrue(is_newer_version("2026.10.3", installed))

    def test_pure_python_order_matches_the_release_order(self) -> None:
        # dpkg: `~` sorts before anything, so X~beta.B < X; X-C is revision C of X.
        def key(debian: str):
            upstream, _, revision = debian.partition("-")
            base, _, beta = upstream.partition("~beta.")
            numbers = tuple(int(part) for part in base.split("."))
            return numbers, (0, int(beta)) if beta else (1, 0), int(revision or 0)

        keys = [key(_debian(version)) for version in ORDER]
        self.assertEqual(keys, sorted(keys))


@unittest.skipUnless(shutil.which("dpkg"), "dpkg is not installed")
class DpkgOrderTests(unittest.TestCase):
    def test_dpkg_sorts_the_mapped_versions_in_release_order(self) -> None:
        for older, newer in zip(ORDER, ORDER[1:]):
            with self.subTest(older=older, newer=newer):
                self.assertTrue(_dpkg_lt(_debian(older), _debian(newer)))
                self.assertFalse(_dpkg_lt(_debian(newer), _debian(older)))

    def test_the_unmapped_beta_would_sort_after_its_final(self) -> None:
        # Why the mapping exists.
        self.assertTrue(_dpkg_lt("2026.10.3", "2026.10.3-beta.1"))


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb is not installed")
class RepackTests(unittest.TestCase):
    def test_set_deb_version_rewrites_the_version_and_keeps_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "root"
            (root / "DEBIAN").mkdir(parents=True)
            (root / "usr" / "bin").mkdir(parents=True)
            (root / "usr" / "bin" / "dictate-ui-shell").write_text("#!/bin/sh\n")
            (root / "DEBIAN" / "control").write_text(
                "Package: dictate\nVersion: 2026.10.3-beta.1\nArchitecture: amd64\n"
                "Maintainer: Test <t@example.test>\nDescription: test\n"
            )
            deb = Path(d) / "Dictate_2026.10.3-beta.1_amd64.deb"
            subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root), str(deb)],
                           check=True, capture_output=True)
            subprocess.run([str(ROOT / "scripts" / "set-deb-version.sh"), str(deb), "2026.10.3~beta.1"],
                           check=True, capture_output=True)
            field = subprocess.run(["dpkg-deb", "--field", str(deb), "Version"],
                                   check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(field, "2026.10.3~beta.1")
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["Dictate_2026.10.3-beta.1_amd64.deb", "root"])
            contents = subprocess.run(["dpkg-deb", "--contents", str(deb)],
                                      check=True, capture_output=True, text=True).stdout
            self.assertIn("root/root", contents)
            self.assertIn("./usr/bin/dictate-ui-shell", contents)


class BuildScriptTests(unittest.TestCase):
    def test_the_linux_build_maps_a_beta_deb_version(self) -> None:
        script = (ROOT / "scripts" / "build-linux-desktop.sh").read_text(encoding="utf-8")
        self.assertIn('scripts/calver.py debian-version "$APP_VERSION"', script)
        self.assertIn('./scripts/set-deb-version.sh "$deb" "$DEB_VERSION"', script)


if __name__ == "__main__":
    unittest.main()
