"""Tests for Dictate Pro desktop client."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate.pro.client import ProClient, ProSession


class ProClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.session_path = Path(self._tmp.name) / "pro-session.json"
        self.client = ProClient(session_path=self.session_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_session_warns_on_plaintext_refresh_token_fallback(self) -> None:
        session = ProSession(
            account_id="acct_test",
            device_id="dev_test",
            access_token="access",
            refresh_token="refresh_secret",
            access_expires_at="2026-01-01T00:00:00+00:00",
            refresh_expires_at="2027-01-01T00:00:00+00:00",
        )
        with patch.object(self.client, "_save_refresh_token", return_value=False):
            with self.assertLogs("dictate.pro.client", level="WARNING") as logs:
                self.client.save_session(session)
        self.assertTrue(any("plaintext" in message for message in logs.output))
        payload = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["refresh_token"], "refresh_secret")


if __name__ == "__main__":
    unittest.main()
