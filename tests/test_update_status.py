from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from dictate.update_status import check_update_status, is_newer_version, parse_calver


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

        with patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen):
            status = check_update_status()

        self.assertTrue(status.checked)
        self.assertEqual(status.latest_version, "2099.1.2")
        self.assertTrue(status.update_available)
        self.assertIsNone(status.error)

    def test_check_update_status_falls_back_to_tags(self) -> None:
        def fake_urlopen(request, timeout):  # noqa: ANN001, ARG001
            if str(request.full_url).endswith("/releases/latest"):
                raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO())
            return _FakeResponse([{"name": "v2026.5.18"}])

        with patch("dictate.update_status.urllib.request.urlopen", side_effect=fake_urlopen):
            status = check_update_status()

        self.assertTrue(status.checked)
        self.assertEqual(status.latest_version, "2026.5.18")
        self.assertFalse(status.update_available)

    def test_check_update_status_reports_error_gracefully(self) -> None:
        with patch(
            "dictate.update_status.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            status = check_update_status()

        self.assertFalse(status.checked)
        self.assertIsNotNone(status.error)
        self.assertFalse(status.update_available)


if __name__ == "__main__":
    unittest.main()
