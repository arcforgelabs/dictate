from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from dictate.config import Config
from dictate.update_status import (
    RELEASES_URL,
    check_update_status,
    is_newer_version,
    parse_calver,
    start_update_flow,
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


class UpdateStatusTests(unittest.TestCase):
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

    def test_check_update_status_uses_npm_unstable_dist_tag(self) -> None:
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            self.assertEqual(str(request.full_url), "https://registry.npmjs.org/@arcforgelabs%2fdictate")
            return _FakeResponse({"dist-tags": {"unstable": "2026.7.4-unstable.48.1"}})

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

    def test_source_checkout_defaults_to_unstable_update_channel(self) -> None:
        root = Path("/tmp/dictate-source")

        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            self.assertEqual(str(request.full_url), "https://registry.npmjs.org/@arcforgelabs%2fdictate")
            return _FakeResponse({"dist-tags": {"unstable": "2026.7.4-unstable.52.1"}})

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
            return _FakeResponse({"dist-tags": {"unstable": "2026.7.4-unstable.52.1"}})

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
            patch(
                "dictate.update_status._find_release_asset",
                return_value=("https://example.test/Dictate_2099.1.2_amd64.deb", "Dictate_2099.1.2_amd64.deb"),
            ) as find,
            patch("dictate.update_status._download_file", return_value=Path("/tmp/x.deb")) as dl,
            patch("dictate.update_status._install_deb", return_value=ok) as install,
            patch("dictate.update_status.Path.unlink"),
            patch("dictate.config.set_installed_package_version") as stamp,
        ):
            flow = start_update_flow()

        self.assertEqual(flow.mode, "installed")
        self.assertTrue(flow.started)
        self.assertEqual(flow.install_kind, "linux-package")
        self.assertIn("restart", flow.actions or [])
        find.assert_called_once_with("_amd64.deb", release_tag="v2026.7.4-unstable.2.1")
        dl.assert_called_once()
        install.assert_called_once()
        stamp.assert_called_once_with("2026.7.4-unstable.2.1")

    def test_linux_package_update_reports_cancelled(self) -> None:
        cancelled = subprocess.CompletedProcess(args=[], returncode=126, stdout="", stderr="dismissed")
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
            patch(
                "dictate.update_status._find_release_asset",
                return_value=("https://example.test/x_amd64.deb", "x_amd64.deb"),
            ),
            patch("dictate.update_status._download_file", return_value=Path("/tmp/x.deb")),
            patch("dictate.update_status._install_deb", return_value=cancelled),
            patch("dictate.update_status.Path.unlink"),
        ):
            flow = start_update_flow()

        self.assertEqual(flow.mode, "error")
        self.assertFalse(flow.started)
        self.assertEqual(flow.error_code, "cancelled")

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
        with (
            patch("dictate.update_status.sys.platform", "win32"),
            patch("dictate.update_status._candidate_source_roots", return_value=[]),
            patch("dictate.update_status._windows_distribution", return_value="direct"),
            patch("dictate.update_status.load_config", return_value=Config(update_channel="unstable", installed_package_version="2026.7.4-unstable.1.1")),
            patch("dictate.update_status._fetch_latest_version", return_value=("2026.7.4-unstable.2.1", "https://example.test")),
            patch("dictate.update_status._find_release_asset", return_value=("https://example.test/Dictate-setup.exe", "Dictate-setup.exe")) as find,
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
