from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

from dictate.config import Config
from dictate.update_status import (
    ReleaseAsset,
    check_update_status,
    get_linux_package_update_snapshot,
    is_newer_version,
    parse_calver,
    start_update_flow,
    _clear_linux_package_operation,
    _download_release_asset_partial,
    _finalize_verified_download,
)
from dictate.version import RELEASE_VERSION


class _FakeResponse:
    def __init__(self, payload) -> None:  # noqa: ANN001
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, **kw):  # noqa: ANN001, ARG001
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self) -> None:
        if self._target:
            self._target(*self._args, **self._kwargs)

    def is_alive(self) -> bool:
        return False


class UpdateStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_linux_package_operation()

    def tearDown(self) -> None:
        _clear_linux_package_operation()
    def test_parse_calver_accepts_optional_v_prefix(self) -> None:
        self.assertEqual(parse_calver("2026.5.18"), (2026, 5, 18, 0))
        self.assertEqual(parse_calver("v2026.5.19"), (2026, 5, 19, 0))
        self.assertEqual(parse_calver("v2026.5.18-1"), (2026, 5, 18, 1))
        self.assertIsNone(parse_calver("latest"))

    def test_is_newer_version_compares_calver(self) -> None:
        self.assertTrue(is_newer_version("2026.5.19", "2026.5.18"))
        self.assertTrue(is_newer_version("2026.5.18-1", "2026.5.18"))
        self.assertFalse(is_newer_version("2026.5.18", "2026.5.18"))
        self.assertFalse(is_newer_version("2026.5.17", "2026.5.18"))

    def test_is_newer_version_treats_unstable_same_base_as_update(self) -> None:
        self.assertTrue(is_newer_version("2026.7.4-unstable.48.1", "2026.7.4"))
        self.assertTrue(
            is_newer_version("2026.7.4-unstable.49.1", "2026.7.4-unstable.48.1")
        )
        self.assertFalse(
            is_newer_version("2026.7.4-unstable.48.1", "2026.7.4-unstable.49.1")
        )

    def test_check_update_status_uses_latest_release(self) -> None:
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            return _FakeResponse(
                {
                    "tag_name": "v2099.1.2",
                    "html_url": "https://github.com/arcforgelabs/dictate/releases/tag/v2099.1.2",
                }
            )

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=None),
            patch("dictate.update_status._is_linux_user_install", return_value=False),
            patch("dictate.update_status.sys.platform", "linux"),
            patch("dictate.update_status.load_config", return_value=Config(update_channel="stable")),
        ):
            status = check_update_status()

        self.assertTrue(status.checked)
        self.assertEqual(status.latest_version, "2099.1.2")
        self.assertTrue(status.update_available)
        self.assertIsNone(status.error)
        self.assertEqual(status.platform, "linux")
        self.assertEqual(status.install_kind, "linux-package")
        self.assertEqual(status.phase, "available")
        self.assertIn("update", status.actions or [])
        self.assertEqual(status.current_version, RELEASE_VERSION)

    def test_stable_channel_resolves_via_npm_when_github_repo_is_private(self) -> None:
        """A private GitHub repo 404s its API. Stable update checks must still
        succeed from the npm registry, which stays public, and must not surface
        an error to the user."""
        seen = []

        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            url = str(request.full_url)
            seen.append(url)
            if "api.github.com" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return _FakeResponse({"dist-tags": {"latest": "2099.1.2"}})

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=None),
            patch("dictate.update_status._is_linux_user_install", return_value=False),
            patch("dictate.update_status.sys.platform", "linux"),
            patch("dictate.update_status.load_config", return_value=Config(update_channel="stable")),
        ):
            status = check_update_status()

        self.assertTrue(status.checked)
        self.assertEqual(status.latest_version, "2099.1.2")
        self.assertTrue(status.update_available)
        self.assertIsNone(status.error)
        self.assertNotEqual(status.phase, "failed")
        # npm must be consulted first, so a private repo never gates the check.
        self.assertTrue(seen and "registry.npmjs.org" in seen[0], seen)

    def test_user_facing_release_url_is_not_the_private_repository(self) -> None:
        """The repository is private, so any GitHub URL we hand the UI 404s for
        users. The open_release action must point at a public page."""
        from dictate.update_status import RELEASES_URL

        self.assertNotIn("github.com/arcforgelabs/dictate", RELEASES_URL)
        self.assertTrue(RELEASES_URL.startswith("https://"), RELEASES_URL)

    def test_check_update_status_uses_npm_unstable_dist_tag(self) -> None:
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            self.assertEqual(str(request.full_url), "https://registry.npmjs.org/@arcforgelabs%2fdictate")
            return _FakeResponse({"dist-tags": {"latest": "2026.7.4", "unstable": "2026.7.4-unstable.48.1"}})

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=None),
            patch("dictate.update_status._is_linux_user_install", return_value=True),
            patch("dictate.update_status.sys.platform", "linux"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(
                    update_channel="unstable",
                    installed_package_version="2026.7.4",
                ),
            ),
        ):
            status = check_update_status()

        self.assertTrue(status.checked)
        self.assertEqual(status.current_version, "2026.7.4")
        self.assertEqual(status.latest_version, "2026.7.4-unstable.48.1")
        self.assertTrue(status.update_available)
        self.assertEqual(status.install_kind, "linux-user")
        self.assertIn("update", status.actions or [])

    def test_unstable_channel_offers_stable_when_the_unstable_pointer_is_behind(self) -> None:
        # Unstable is upstream of stable: a stable release cut without a newer
        # unstable build is the newest thing on the Beta channel as well.
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            return _FakeResponse({"dist-tags": {"latest": "2026.9.20", "unstable": "2026.7.4-unstable.68.1"}})

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=None),
            patch("dictate.update_status._is_linux_user_install", return_value=True),
            patch("dictate.update_status.sys.platform", "linux"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(update_channel="unstable", installed_package_version="2026.7.4"),
            ),
        ):
            status = check_update_status()

        self.assertEqual(status.latest_version, "2026.9.20")
        self.assertTrue(status.update_available)

    def test_unstable_channel_prefers_a_newer_unstable_build_over_stable(self) -> None:
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            return _FakeResponse({"dist-tags": {"latest": "2026.9.20", "unstable": "2026.9.20-unstable.1.1"}})

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=None),
            patch("dictate.update_status._is_linux_user_install", return_value=True),
            patch("dictate.update_status.sys.platform", "linux"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(update_channel="unstable", installed_package_version="2026.9.20"),
            ),
        ):
            status = check_update_status()

        self.assertEqual(status.latest_version, "2026.9.20-unstable.1.1")
        self.assertTrue(status.update_available)

    def test_unstable_channel_falls_back_to_stable_when_no_unstable_tag_exists(self) -> None:
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            return _FakeResponse({"dist-tags": {"latest": "2026.9.20"}})

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=None),
            patch("dictate.update_status._is_linux_user_install", return_value=True),
            patch("dictate.update_status.sys.platform", "linux"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(update_channel="unstable", installed_package_version="2026.7.4"),
            ),
        ):
            status = check_update_status()

        self.assertEqual(status.latest_version, "2026.9.20")
        self.assertTrue(status.update_available)

    def test_source_checkout_defaults_to_unstable_update_channel(self) -> None:
        root = Path("/tmp/dictate-source")

        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            self.assertEqual(str(request.full_url), "https://registry.npmjs.org/@arcforgelabs%2fdictate")
            return _FakeResponse({"dist-tags": {"latest": "2026.7.4", "unstable": "2026.7.4-unstable.52.1"}})

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=root),
            patch("dictate.update_status._is_linux_user_install", return_value=False),
            patch("dictate.update_status.sys.platform", "linux"),
            patch("dictate.update_status.load_config", return_value=Config(installed_package_version="2026.7.4")),
        ):
            status = check_update_status()

        self.assertTrue(status.checked)
        self.assertEqual(status.latest_version, "2026.7.4-unstable.52.1")
        self.assertTrue(status.update_available)
        self.assertEqual(status.install_kind, "linux-source")

    def test_linux_user_install_wins_over_checkout_cwd(self) -> None:
        root = Path("/tmp/dictate-source")

        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            self.assertEqual(str(request.full_url), "https://registry.npmjs.org/@arcforgelabs%2fdictate")
            return _FakeResponse({"dist-tags": {"latest": "2026.7.4", "unstable": "2026.7.4-unstable.52.1"}})

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=root),
            patch("dictate.update_status._is_linux_user_install", return_value=True),
            patch("dictate.update_status.sys.platform", "linux"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(update_channel="unstable", installed_package_version="2026.7.4"),
            ),
        ):
            status = check_update_status()

        self.assertEqual(status.install_kind, "linux-user")
        self.assertEqual(status.commands, {"update": "npx -y @arcforgelabs/dictate@unstable update --user"})

    def test_check_update_status_falls_back_to_tags(self) -> None:
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            if str(request.full_url).endswith("/releases/latest"):
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO())
            return _FakeResponse([{"name": "v2026.5.18"}])

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=None),
            patch("dictate.update_status._is_linux_user_install", return_value=False),
            patch("dictate.update_status.load_config", return_value=Config(update_channel="stable")),
        ):
            status = check_update_status()

        self.assertTrue(status.checked)
        self.assertEqual(status.latest_version, "2026.5.18")
        self.assertFalse(status.update_available)

    def test_check_update_status_reports_error_gracefully(self) -> None:
        with (
            patch(
                "dictate.update_status.urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ),
            patch("dictate.update_status._find_source_root", return_value=None),
            patch("dictate.update_status._is_linux_user_install", return_value=False),
            patch("dictate.update_status.load_config", return_value=Config(update_channel="stable")),
        ):
            status = check_update_status()

        self.assertFalse(status.checked)
        self.assertIsNotNone(status.error)
        self.assertFalse(status.update_available)
        self.assertEqual(status.phase, "failed")
        self.assertEqual(status.error_code, "check_failed")

    def test_linux_source_update_runs_validated_update_script(self) -> None:
        calls = []

        def fake_popen(command, cwd):  # noqa: ANN001
            calls.append((command, cwd))
            return object()

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "update.sh").write_text("#!/usr/bin/env bash\n")
            (root / "pyproject.toml").write_text("[project]\nname='dictate'\n")
            (root / "src" / "dictate").mkdir(parents=True)
            with patch("dictate.update_status.sys.platform", "linux"):
                with patch("dictate.update_status._candidate_source_roots", return_value=[root]):
                    with patch("dictate.update_status._is_linux_user_install", return_value=False):
                        with patch("dictate.update_status.subprocess.Popen", side_effect=fake_popen):
                            flow = start_update_flow()

        self.assertEqual(flow.mode, "command")
        self.assertTrue(flow.started)
        self.assertNotIn("restart", flow.actions or [])
        self.assertEqual(calls, [(["bash", str(root / "update.sh")], str(root))])

    def _linux_package(self):  # noqa: ANN202
        # platform=linux, no source root -> install_kind == "linux-package"
        return (
            patch("dictate.update_status.sys.platform", "linux"),
            patch("dictate.update_status._candidate_source_roots", return_value=[]),
            patch("dictate.update_status._is_linux_user_install", return_value=False),
        )

    def _linux_user(self):  # noqa: ANN202
        return (
            patch("dictate.update_status.sys.platform", "linux"),
            patch("dictate.update_status._candidate_source_roots", return_value=[]),
            patch("dictate.update_status._is_linux_user_install", return_value=True),
        )

    def test_linux_user_update_runs_npm_bootstrap_without_pkexec(self) -> None:
        calls = []

        def fake_popen(command, **kwargs):  # noqa: ANN001, ARG001
            calls.append(command)
            return object()

        plat, roots, user = self._linux_user()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.load_config", return_value=Config()),
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/npx"),
            patch("dictate.update_status.subprocess.Popen", side_effect=fake_popen),
        ):
            flow = start_update_flow()

        self.assertEqual(flow.mode, "command")
        self.assertTrue(flow.started)
        self.assertEqual(flow.install_kind, "linux-user")
        self.assertNotIn("restart", flow.actions or [])
        self.assertEqual(
            calls,
            [["/usr/bin/npx", "-y", "@arcforgelabs/dictate@latest", "update", "--user"]],
        )

    def test_linux_user_update_can_target_unstable_npm_channel(self) -> None:
        calls = []

        def fake_popen(command, **kwargs):  # noqa: ANN001, ARG001
            calls.append(command)
            return object()

        plat, roots, user = self._linux_user()
        with (
            plat,
            roots,
            user,
            patch.dict("dictate.update_status.os.environ", {"DICTATE_UPDATE_CHANNEL": "unstable"}, clear=False),
            patch("dictate.update_status.load_config", return_value=Config()),
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/npx"),
            patch("dictate.update_status.subprocess.Popen", side_effect=fake_popen),
        ):
            flow = start_update_flow()

        self.assertTrue(flow.started)
        self.assertEqual(
            calls,
            [["/usr/bin/npx", "-y", "@arcforgelabs/dictate@unstable", "update", "--user"]],
        )

    def test_linux_user_update_finds_npx_from_nvm_when_desktop_path_is_minimal(self) -> None:
        calls = []

        def fake_popen(command, env):  # noqa: ANN001
            calls.append((command, env))
            return object()

        plat, roots, user = self._linux_user()
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            npx = home / ".nvm" / "versions" / "node" / "v25.8.1" / "bin" / "npx"
            npx.parent.mkdir(parents=True)
            npx.write_text("#!/bin/sh\n")
            npx.chmod(0o755)
            with (
                plat,
                roots,
                user,
                patch("dictate.update_status.Path.home", return_value=home),
                patch("dictate.update_status.shutil.which", return_value=None),
                patch("dictate.update_status.load_config", return_value=Config(update_channel="unstable")),
                patch("dictate.update_status.subprocess.Popen", side_effect=fake_popen),
            ):
                flow = start_update_flow()

        self.assertTrue(flow.started)
        self.assertEqual(calls[0][0], [str(npx), "-y", "@arcforgelabs/dictate@unstable", "update", "--user"])
        self.assertTrue(calls[0][1]["PATH"].startswith(str(npx.parent)))

    def test_invalid_update_channel_falls_back_to_latest(self) -> None:
        plat, roots, user = self._linux_user()
        with (
            plat,
            roots,
            user,
            patch.dict("dictate.update_status.os.environ", {"DICTATE_UPDATE_CHANNEL": "../../bad"}, clear=False),
            patch("dictate.update_status.load_config", return_value=Config()),
            patch(
                "dictate.update_status.urllib.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ),
        ):
            status = check_update_status(timeout=0.01)

        self.assertEqual(status.commands, {"update": "npx -y @arcforgelabs/dictate@latest update --user"})

    def test_saved_unstable_update_channel_wins_for_linux_user_update(self) -> None:
        calls = []

        def fake_popen(command, **kwargs):  # noqa: ANN001, ARG001
            calls.append(command)
            return object()

        plat, roots, user = self._linux_user()
        with (
            plat,
            roots,
            user,
            patch.dict("dictate.update_status.os.environ", {"DICTATE_UPDATE_CHANNEL": "stable"}, clear=False),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(update_channel="unstable"),
            ),
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/npx"),
            patch("dictate.update_status.subprocess.Popen", side_effect=fake_popen),
        ):
            flow = start_update_flow()

        self.assertTrue(flow.started)
        self.assertEqual(
            calls,
            [["/usr/bin/npx", "-y", "@arcforgelabs/dictate@unstable", "update", "--user"]],
        )

    def test_linux_user_update_requires_npx(self) -> None:
        plat, roots, user = self._linux_user()
        with tempfile.TemporaryDirectory() as d:
            with (
                plat,
                roots,
                user,
                patch("dictate.update_status.Path.home", return_value=Path(d)),
                patch("dictate.update_status._find_npx", return_value=None),
            ):
                flow = start_update_flow()

        self.assertEqual(flow.mode, "error")
        self.assertEqual(flow.error_code, "missing_deps")
        self.assertEqual(flow.missing_deps, ["npx"])

    def test_linux_package_update_downloads_and_installs(self) -> None:
        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        asset = ReleaseAsset(
            url="https://example.test/Dictate_2099.1.2_amd64.deb",
            name="Dictate_2099.1.2_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(update_channel="unstable", installed_package_version="2026.7.4-unstable.1.1"),
            ),
            patch(
                "dictate.update_status._fetch_latest_version",
                return_value=("2026.7.4-unstable.2.1", "https://example.test"),
            ),
            patch("dictate.update_status._find_release_asset", return_value=asset) as find,
            patch("dictate.update_status._download_release_asset_partial", return_value=Path("/tmp/x.deb.partial")) as dl,
            patch("dictate.update_status._finalize_verified_download", return_value=Path("/tmp/x.deb")) as finalize,
            patch("dictate.update_status._install_deb", return_value=ok) as install,
            patch("dictate.update_status._cleanup_download_artifacts"),
            patch("dictate.update_status.Path.unlink"),
            patch("dictate.config.set_installed_package_version") as stamp,
            patch("dictate.update_status.threading.Thread", _ImmediateThread),
        ):
            flow = start_update_flow()
            snapshot = get_linux_package_update_snapshot()

        self.assertEqual(flow.mode, "installed")
        self.assertTrue(flow.started)
        self.assertEqual(flow.phase, "installed")
        self.assertEqual(flow.install_kind, "linux-package")
        find.assert_called_once_with("_amd64.deb", release_tag="v2026.7.4-unstable.2.1")
        dl.assert_called_once()
        finalize.assert_called_once()
        install.assert_called_once()
        stamp.assert_called_once_with("2026.7.4-unstable.2.1")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["phase"], "installed")
        self.assertIn("restart", snapshot["actions"])

    def test_linux_package_update_reports_cancelled(self) -> None:
        cancelled = subprocess.CompletedProcess(args=[], returncode=126, stdout="", stderr="dismissed")
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(update_channel="stable", installed_package_version="2026.7.4"),
            ),
            patch(
                "dictate.update_status._fetch_latest_version",
                return_value=("2026.7.5", "https://example.test"),
            ),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch("dictate.update_status._download_release_asset_partial", return_value=Path("/tmp/x.deb.partial")),
            patch("dictate.update_status._finalize_verified_download", return_value=Path("/tmp/x.deb")),
            patch("dictate.update_status._install_deb", return_value=cancelled),
            patch("dictate.update_status._cleanup_download_artifacts"),
            patch("dictate.update_status.Path.unlink"),
            patch("dictate.update_status.threading.Thread", _ImmediateThread),
        ):
            flow = start_update_flow()
            snapshot = get_linux_package_update_snapshot()

        self.assertEqual(flow.mode, "error")
        self.assertFalse(flow.started)
        self.assertEqual(flow.error_code, "cancelled")
        self.assertEqual(snapshot["phase"], "failed")
        self.assertEqual(snapshot["error_code"], "cancelled")

    def test_linux_package_update_requires_pkexec(self) -> None:
        plat, roots, user = self._linux_package()
        with plat, roots, user, patch("dictate.update_status.shutil.which", return_value=None):
            flow = start_update_flow()

        self.assertEqual(flow.mode, "error")
        self.assertEqual(flow.error_code, "missing_deps")
        self.assertEqual(flow.missing_deps, ["pkexec"])

    def test_windows_source_update_runs_validated_update_script(self) -> None:
        calls = []

        def fake_popen(command, cwd):  # noqa: ANN001
            calls.append((command, cwd))
            return object()

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "update-windows.ps1").write_text("Write-Host update\n")
            (root / "pyproject.toml").write_text("[project]\nname='dictate'\n")
            (root / "src" / "dictate").mkdir(parents=True)
            with patch("dictate.update_status.sys.platform", "win32"):
                with patch("dictate.update_status._candidate_source_roots", return_value=[root]):
                    with patch("dictate.update_status.subprocess.Popen", side_effect=fake_popen):
                        flow = start_update_flow()

        self.assertEqual(flow.mode, "command")
        self.assertTrue(flow.started)
        self.assertEqual(flow.platform, "windows")
        self.assertEqual(flow.install_kind, "windows-source")
        self.assertNotIn("restart", flow.actions or [])
        self.assertEqual(calls[0][0][-1], str(root / "update-windows.ps1"))
        self.assertEqual(calls[0][1], str(root))

    def test_windows_direct_update_downloads_selected_channel_installer(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/Dictate-setup.exe",
            name="Dictate-setup.exe",
            size=None,
            sha256=None,
        )
        with (
            patch("dictate.update_status.sys.platform", "win32"),
            patch("dictate.update_status._candidate_source_roots", return_value=[]),
            patch("dictate.update_status._windows_distribution", return_value="direct"),
            patch("dictate.update_status.load_config", return_value=Config(update_channel="unstable", installed_package_version="2026.7.4-unstable.1.1")),
            patch("dictate.update_status._fetch_latest_version", return_value=("2026.7.4-unstable.2.1", "https://example.test")),
            patch("dictate.update_status._find_release_asset", return_value=asset) as find,
            patch("dictate.update_status._download_file", return_value=Path("C:/Temp/Dictate-setup.exe")),
            patch("dictate.update_status.subprocess.Popen") as popen,
        ):
            flow = start_update_flow()

        self.assertEqual(flow.mode, "installer")
        self.assertTrue(flow.started)
        self.assertEqual(flow.platform, "windows")
        self.assertEqual(flow.install_kind, "windows-direct")
        find.assert_called_once_with("-setup.exe", release_tag="v2026.7.4-unstable.2.1")
        popen.assert_called_once_with([str(Path("C:/Temp/Dictate-setup.exe")), "/S", "/UPDATE"])

    def test_download_progress_uses_content_length(self) -> None:
        payload = b"abcd"
        seen: list[int | None] = []

        class _Body:
            headers = {"Content-Length": str(len(payload))}

            def read(self, size=-1):  # noqa: ANN001
                if not hasattr(self, "_done"):
                    self._done = True
                    return payload
                return b""

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return None

        with tempfile.TemporaryDirectory() as d:
            with patch("dictate.update_status.tempfile.gettempdir", return_value=d):
                with patch("dictate.update_status.urllib.request.urlopen", return_value=_Body()):
                    partial = _download_release_asset_partial(
                        "https://example.test/pkg.deb",
                        "pkg.deb",
                        expected_size=len(payload),
                        progress_callback=seen.append,
                    )
            self.assertTrue(partial.is_file())
            self.assertEqual(seen[-1], 100)

    def test_download_rejects_byte_count_mismatch_and_cleans_partial(self) -> None:
        class _ShortBody:
            headers = {"Content-Length": "10"}

            def read(self, size=-1):  # noqa: ANN001
                if not hasattr(self, "_done"):
                    self._done = True
                    return b"abc"
                return b""

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
                return None

        with tempfile.TemporaryDirectory() as d:
            with patch("dictate.update_status.tempfile.gettempdir", return_value=d):
                with patch("dictate.update_status.urllib.request.urlopen", return_value=_ShortBody()):
                    with self.assertRaisesRegex(RuntimeError, "Download incomplete"):
                        _download_release_asset_partial(
                            "https://example.test/pkg.deb",
                            "pkg.deb",
                            expected_size=10,
                        )
            partial = Path(d) / "dictate-update" / "pkg.deb.partial"
            self.assertFalse(partial.exists())

    def test_checksum_mismatch_blocks_installation(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            partial = Path(d) / "pkg.deb.partial"
            partial.write_bytes(b"abc")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                _finalize_verified_download(
                    partial,
                    "pkg.deb",
                    expected_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                )
            self.assertFalse(partial.exists())

    def test_linux_package_update_surfaces_background_phases(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        phases: list[str] = []
        plat, roots, user = self._linux_package()
        import dictate.update_status as update_status_mod

        real_set_phase = update_status_mod._linux_package_set_phase

        def record_phase(*args, **kwargs):  # noqa: ANN002
            phases.append(args[0])
            return real_set_phase(*args, **kwargs)

        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch("dictate.update_status.load_config", return_value=Config(installed_package_version="2026.7.4")),
            patch("dictate.update_status._fetch_latest_version", return_value=("2026.7.5", "https://example.test")),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch("dictate.update_status._download_release_asset_partial", return_value=Path("/tmp/x.deb.partial")),
            patch("dictate.update_status._finalize_verified_download", return_value=Path("/tmp/x.deb")),
            patch("dictate.update_status._install_deb", return_value=ok),
            patch("dictate.update_status._cleanup_download_artifacts"),
            patch("dictate.update_status.Path.unlink"),
            patch("dictate.config.set_installed_package_version"),
            patch("dictate.update_status._linux_package_set_phase", side_effect=record_phase),
            patch("dictate.update_status.threading.Thread", _ImmediateThread),
        ):
            start = start_update_flow()
            status = check_update_status()

        self.assertEqual(start.phase, "installed")
        self.assertIn("downloading", phases)
        self.assertIn("verifying", phases)
        self.assertIn("installing", phases)
        self.assertEqual(status.phase, "installed")

    def test_linux_package_duplicate_start_is_rejected(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        plat, roots, user = self._linux_package()

        class _SlowThread:
            def __init__(self, target=None, args=(), kwargs=None, **kw):  # noqa: ANN001, ARG001
                self._target = target
                self._args = args

            def start(self) -> None:
                return

            def is_alive(self) -> bool:
                return True

        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch("dictate.update_status.load_config", return_value=Config(installed_package_version="2026.7.4")),
            patch("dictate.update_status._fetch_latest_version", return_value=("2026.7.5", "https://example.test")),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch("dictate.update_status.threading.Thread", _SlowThread),
        ):
            first = start_update_flow()
            second = start_update_flow()

        self.assertEqual(first.mode, "working")
        self.assertEqual(second.mode, "busy")
        self.assertFalse(second.started)

    def test_linux_package_concurrent_starts_launch_one_worker(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        lookup_entered = threading.Event()
        release_lookup = threading.Event()
        release_worker = threading.Event()
        worker_started = threading.Event()
        results = []

        def fetch_latest(channel, *, timeout):  # noqa: ANN001, ARG001
            lookup_entered.set()
            self.assertTrue(release_lookup.wait(timeout=2))
            return "2026.7.5", "https://example.test"

        def worker(*args):  # noqa: ANN002
            worker_started.set()
            release_worker.wait(timeout=2)

        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(installed_package_version="2026.7.4"),
            ),
            patch("dictate.update_status._fetch_latest_version", side_effect=fetch_latest),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch("dictate.update_status._linux_package_update_worker", side_effect=worker),
        ):
            first = threading.Thread(target=lambda: results.append(start_update_flow()))
            first.start()
            self.assertTrue(lookup_entered.wait(timeout=2))
            preparing = check_update_status()
            second = threading.Thread(target=lambda: results.append(start_update_flow()))
            second.start()
            second.join(timeout=2)
            release_lookup.set()
            first.join(timeout=2)
            self.assertTrue(worker_started.wait(timeout=2))
            release_worker.set()

        self.assertEqual(len(results), 2)
        self.assertEqual(preparing.phase, "preparing")
        self.assertTrue(preparing.update_available)
        self.assertIsNone(preparing.progress)
        self.assertEqual(sum(result.started for result in results), 1)
        self.assertEqual({result.mode for result in results}, {"working", "busy"})

    def test_active_linux_package_status_does_not_require_remote_lookup(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        plat, roots, user = self._linux_package()

        class _SlowThread:
            def __init__(self, target=None, args=(), kwargs=None, **kw):  # noqa: ANN001, ARG001
                pass

            def start(self) -> None:
                return

        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(installed_package_version="2026.7.4"),
            ),
            patch(
                "dictate.update_status._fetch_latest_version",
                return_value=("2026.7.5", "https://example.test"),
            ),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch("dictate.update_status.threading.Thread", _SlowThread),
        ):
            start_update_flow()
            with patch(
                "dictate.update_status._fetch_latest_version",
                side_effect=urllib.error.URLError("offline"),
            ) as fetch:
                status = check_update_status()

        fetch.assert_not_called()
        self.assertEqual(status.phase, "downloading")
        self.assertEqual(status.progress, 0)
        self.assertEqual(status.latest_version, "2026.7.5")

    def test_failed_status_lookup_rechecks_new_linux_package_operation(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        lookup_entered = threading.Event()
        release_lookup = threading.Event()
        release_worker = threading.Event()
        call_lock = threading.Lock()
        calls = 0
        statuses = []

        def fetch_latest(*args, **kwargs):  # noqa: ANN002, ANN003
            nonlocal calls
            with call_lock:
                calls += 1
                call = calls
            if call == 1:
                lookup_entered.set()
                self.assertTrue(release_lookup.wait(timeout=2))
                raise urllib.error.URLError("offline")
            return "2026.7.5", "https://example.test"

        def worker(*args, **kwargs):  # noqa: ANN002, ANN003
            release_worker.wait(timeout=2)

        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(installed_package_version="2026.7.4"),
            ),
            patch("dictate.update_status._fetch_latest_version", side_effect=fetch_latest),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch("dictate.update_status._linux_package_update_worker", side_effect=worker),
        ):
            checker = threading.Thread(target=lambda: statuses.append(check_update_status()))
            checker.start()
            self.assertTrue(lookup_entered.wait(timeout=2))
            flow = start_update_flow()
            release_lookup.set()
            checker.join(timeout=2)
            release_worker.set()

        self.assertFalse(checker.is_alive())
        self.assertEqual(flow.phase, "downloading")
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0].phase, "downloading")
        self.assertEqual(statuses[0].latest_version, "2026.7.5")
        self.assertIsNone(statuses[0].error_code)

    def test_linux_package_thread_start_failure_is_retryable(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        attempts = 0

        class _StoppedThread:
            def start(self) -> None:
                return

        def make_thread(*args, **kwargs):  # noqa: ANN002, ANN003
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("thread unavailable")
            return _StoppedThread()

        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(installed_package_version="2026.7.4"),
            ),
            patch(
                "dictate.update_status._fetch_latest_version",
                return_value=("2026.7.5", "https://example.test"),
            ),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch("dictate.update_status.threading.Thread", side_effect=make_thread),
        ):
            failed_flow = start_update_flow()
            failed = get_linux_package_update_snapshot()
            retry = start_update_flow()

        self.assertEqual(failed_flow.phase, "failed")
        self.assertEqual(failed_flow.error_code, "worker_start_failed")
        self.assertEqual(failed["phase"], "failed")
        self.assertIn("thread unavailable", failed["error_detail"])
        self.assertEqual(retry.mode, "working")
        self.assertTrue(retry.started)
        self.assertEqual(attempts, 2)

    def test_linux_package_failure_is_published_after_cleanup(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=4,
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        cleanup_entered = threading.Event()
        release_cleanup = threading.Event()
        failed_published = threading.Event()
        import dictate.update_status as update_status_mod

        real_set_failed = update_status_mod._linux_package_set_failed

        def cleanup(name):  # noqa: ANN001
            cleanup_entered.set()
            release_cleanup.wait(timeout=2)

        def publish_failed(code, detail):  # noqa: ANN001
            real_set_failed(code, detail)
            failed_published.set()

        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(installed_package_version="2026.7.4"),
            ),
            patch(
                "dictate.update_status._fetch_latest_version",
                return_value=("2026.7.5", "https://example.test"),
            ),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch(
                "dictate.update_status._download_release_asset_partial",
                side_effect=RuntimeError("network lost"),
            ),
            patch("dictate.update_status._cleanup_download_artifacts", side_effect=cleanup),
            patch("dictate.update_status._linux_package_set_failed", side_effect=publish_failed),
        ):
            started = start_update_flow()
            self.assertTrue(cleanup_entered.wait(timeout=2))
            before_cleanup = check_update_status()
            busy_retry = start_update_flow()
            release_cleanup.set()
            self.assertTrue(failed_published.wait(timeout=2))
            failed = check_update_status()
            # The retry starts a real worker thread. Wait for it inside the
            # patch context so it cannot outlive this test and hit the next
            # test's mocks (seen as a spurious second download call on slow
            # Windows runners).
            failed_published.clear()
            retry = start_update_flow()
            retry_worker = update_status_mod._linux_package_operation.thread
            self.assertTrue(failed_published.wait(timeout=2))
            if retry_worker is not None:
                retry_worker.join(timeout=2)
                self.assertFalse(retry_worker.is_alive())

        self.assertEqual(started.mode, "working")
        self.assertEqual(before_cleanup.phase, "downloading")
        self.assertEqual(busy_retry.mode, "busy")
        self.assertEqual(failed.phase, "failed")
        self.assertEqual(failed.error_code, "download_failed")
        self.assertNotEqual(retry.mode, "busy")

    def test_linux_package_asset_failure_keeps_target_version_and_retry_action(self) -> None:
        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(installed_package_version="2026.7.4"),
            ),
            patch(
                "dictate.update_status._fetch_latest_version",
                return_value=("2026.7.5", "https://example.test"),
            ),
            patch(
                "dictate.update_status._find_release_asset",
                side_effect=RuntimeError("asset missing"),
            ),
        ):
            flow = start_update_flow()
            status = check_update_status()

        self.assertEqual(flow.phase, "failed")
        self.assertIn("retry", flow.actions)
        self.assertEqual(status.phase, "failed")
        self.assertEqual(status.latest_version, "2026.7.5")
        self.assertIn("retry", status.actions)

    def test_linux_package_version_lookup_failure_has_distinct_code(self) -> None:
        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch(
                "dictate.update_status.load_config",
                return_value=Config(installed_package_version="2026.7.4"),
            ),
            patch(
                "dictate.update_status._fetch_latest_version",
                side_effect=urllib.error.URLError("offline"),
            ),
            patch("dictate.update_status._find_release_asset") as find_asset,
        ):
            flow = start_update_flow()
            status = check_update_status()

        find_asset.assert_not_called()
        self.assertEqual(flow.error_code, "lookup_failed")
        self.assertIn("look up", flow.error_detail)
        self.assertIn("retry", flow.actions)
        self.assertEqual(status.error_code, "lookup_failed")

    def test_linux_package_missing_checksum_fails_before_worker_start_and_retries(self) -> None:
        asset = ReleaseAsset(
            url="https://example.test/x_amd64.deb",
            name="x_amd64.deb",
            size=None,
            sha256=None,
        )
        plat, roots, user = self._linux_package()
        with (
            plat,
            roots,
            user,
            patch("dictate.update_status.shutil.which", return_value="/usr/bin/pkexec"),
            patch("dictate.update_status.load_config", return_value=Config(installed_package_version="2026.7.4")),
            patch("dictate.update_status._fetch_latest_version", return_value=("2026.7.5", "https://example.test")),
            patch("dictate.update_status._find_release_asset", return_value=asset),
            patch("dictate.update_status.threading.Thread") as worker,
        ):
            first = start_update_flow()
            failed = get_linux_package_update_snapshot()
            retry = start_update_flow()

        worker.assert_not_called()
        self.assertEqual(first.mode, "error")
        self.assertFalse(first.started)
        self.assertEqual(first.phase, "failed")
        self.assertEqual(first.error_code, "no_checksum")
        self.assertEqual(failed["phase"], "failed")
        self.assertEqual(failed["error_code"], "no_checksum")
        self.assertEqual(retry.mode, "error")
        self.assertFalse(retry.started)
        self.assertEqual(retry.error_code, "no_checksum")

    def test_windows_store_update_opens_store_and_ignores_unstable_channel(self) -> None:
        with (
            patch("dictate.update_status.sys.platform", "win32"),
            patch("dictate.update_status._candidate_source_roots", return_value=[]),
            patch("dictate.update_status._windows_distribution", return_value="store"),
            patch("dictate.update_status.load_config", return_value=Config(update_channel="unstable")),
            patch("dictate.update_status.os.startfile", create=True) as startfile,
        ):
            flow = start_update_flow()

        self.assertEqual(flow.mode, "store")
        self.assertEqual(flow.install_kind, "windows-store")
        startfile.assert_called_once_with("ms-windows-store://downloadsandupdates")


if __name__ == "__main__":
    unittest.main()
