from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from dictate.update_status import (
    RELEASES_URL,
    check_update_status,
    is_newer_version,
    parse_calver,
    start_update_flow,
)


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
            patch("dictate.update_status.sys.platform", "linux"),
        ):
            status = check_update_status()

        self.assertTrue(status.checked)
        self.assertEqual(status.latest_version, "2099.1.2")
        self.assertTrue(status.update_available)
        self.assertIsNone(status.error)
        self.assertEqual(status.platform, "linux")
        self.assertEqual(status.install_kind, "linux-package")
        self.assertEqual(status.phase, "available")
        self.assertIn("open_release", status.actions or [])
        self.assertEqual(status.engine["current"], "2026.6.20")

    def test_check_update_status_falls_back_to_tags(self) -> None:
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            if str(request.full_url).endswith("/releases/latest"):
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO())
            return _FakeResponse([{"name": "v2026.5.18"}])

        with (
            patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("dictate.update_status._find_source_root", return_value=None),
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
                    with patch("dictate.update_status.subprocess.Popen", side_effect=fake_popen):
                        flow = start_update_flow()

        self.assertEqual(flow.mode, "command")
        self.assertTrue(flow.started)
        self.assertEqual(calls, [(["bash", str(root / "update.sh")], str(root))])

    def test_linux_package_update_falls_back_to_releases(self) -> None:
        with patch("dictate.update_status.sys.platform", "linux"):
            with patch("dictate.update_status._candidate_source_roots", return_value=[]):
                with patch("dictate.update_status.subprocess.Popen") as popen:
                    flow = start_update_flow()

        self.assertEqual(flow.mode, "release")
        self.assertFalse(flow.started)
        self.assertEqual(flow.url, RELEASES_URL)
        self.assertEqual(flow.platform, "linux")
        self.assertEqual(flow.install_kind, "linux-package")
        self.assertEqual(flow.phase, "manual")
        popen.assert_not_called()

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
        self.assertEqual(calls[0][0][-1], str(root / "update-windows.ps1"))
        self.assertEqual(calls[0][1], str(root))

    def test_windows_package_update_opens_release_guidance(self) -> None:
        with patch("dictate.update_status.sys.platform", "win32"):
            with patch("dictate.update_status._candidate_source_roots", return_value=[]):
                with patch("dictate.update_status.subprocess.Popen") as popen:
                    flow = start_update_flow()

        self.assertEqual(flow.mode, "release")
        self.assertFalse(flow.started)
        self.assertEqual(flow.url, RELEASES_URL)
        self.assertEqual(flow.platform, "windows")
        self.assertEqual(flow.install_kind, "windows-package")
        self.assertIn("signed Windows installer", flow.message)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
