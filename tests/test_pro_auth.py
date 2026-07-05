"""Tests for Dictate Pro authentication and sign-in code delivery."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from email.message import EmailMessage
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dictate.pro.auth import ProAuth
from dictate.pro.email_delivery import AuthDeliveryError, SmtpSettings, send_auth_code
from dictate.pro.server import ProRequestHandler
from dictate.pro.service import ProService, ProSettings
from dictate.pro.store import ProStore


def _request(base_url: str, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    url = f"{base_url}{path}"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return exc.code, body


class _FakeSMTP:
    sent_messages: list[EmailMessage] = []

    def __init__(self, host: str, port: int, timeout: float = 10) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self, *, context: object | None = None) -> None:
        return None

    def login(self, username: str, password: str) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        self.sent_messages.append(message)


class ProAuthDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ProStore(Path(self._tmp.name) / "auth.sqlite3")
        self._smtp_env_keys = (
            "DICTATE_PRO_SMTP_HOST",
            "DICTATE_PRO_SMTP_PORT",
            "DICTATE_PRO_SMTP_USERNAME",
            "DICTATE_PRO_SMTP_PASSWORD",
            "DICTATE_PRO_SMTP_FROM",
            "DICTATE_PRO_SMTP_TLS",
            "DICTATE_PRO_SMTP_TIMEOUT",
        )

    def tearDown(self) -> None:
        os.environ.pop("DICTATE_PRO_DEV_AUTH", None)
        for key in self._smtp_env_keys:
            os.environ.pop(key, None)
        self._tmp.cleanup()

    def _configure_smtp_env(self) -> None:
        os.environ["DICTATE_PRO_SMTP_HOST"] = "smtp.example.com"
        os.environ["DICTATE_PRO_SMTP_PORT"] = "587"
        os.environ["DICTATE_PRO_SMTP_FROM"] = "Dictate Pro <noreply@example.com>"

    def test_dev_mode_exposes_dev_code_without_smtp(self) -> None:
        os.environ["DICTATE_PRO_DEV_AUTH"] = "1"
        auth = ProAuth(self.store, dev_expose_code=True)
        start = auth.start_sign_in("dev@example.com")
        self.assertIn("dev_code", start)
        self.assertRegex(start["dev_code"], r"^\d{6}$")
        session = auth.complete_sign_in(
            challenge_id=start["challenge_id"],
            code=start["dev_code"],
            device_label="Dev Desktop",
            device_public_key="public_key_1",
        )
        self.assertTrue(session.access_token)
        device = self.store.get_device(account_id=session.account_id, device_id=session.device_id)
        assert device is not None
        self.assertEqual(device.public_key, "public_key_1")

    def test_production_without_smtp_fails_closed(self) -> None:
        auth = ProAuth(self.store, dev_expose_code=False)
        with self.assertRaises(AuthDeliveryError) as ctx:
            auth.start_sign_in("prod@example.com")
        self.assertIn("not configured", str(ctx.exception).lower())

    def test_production_without_smtp_returns_503_from_server(self) -> None:
        settings = ProSettings(data_dir=Path(self._tmp.name) / "server-data")
        service = ProService(settings)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), ProRequestHandler)
        httpd.service = service  # type: ignore[attr-defined]
        port = httpd.server_address[1]
        base_url = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = _request(base_url, "POST", "/v1/auth/start", {"email": "prod@example.com"})
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
        self.assertEqual(status, 503)
        self.assertIn("not configured", body["error"].lower())

    def test_production_with_smtp_sends_email_and_completes_sign_in(self) -> None:
        self._configure_smtp_env()
        _FakeSMTP.sent_messages = []
        auth = ProAuth(self.store, dev_expose_code=False)
        settings = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username=None,
            password=None,
            from_address="noreply@example.com",
            use_tls=True,
            timeout=10,
        )
        with patch("dictate.pro.email_delivery.smtplib.SMTP", _FakeSMTP):
            start = auth.start_sign_in("smtp@example.com")
        self.assertNotIn("dev_code", start)
        self.assertEqual(len(_FakeSMTP.sent_messages), 1)
        message = _FakeSMTP.sent_messages[0]
        self.assertEqual(message["To"], "smtp@example.com")
        body = message.get_content()
        match = re.search(r"\b(\d{6})\b", body)
        self.assertIsNotNone(match)
        code = match.group(1)  # type: ignore[union-attr]
        session = auth.complete_sign_in(
            challenge_id=start["challenge_id"],
            code=code,
            device_label="SMTP Desktop",
        )
        self.assertTrue(session.access_token)

    def test_smtp_send_failure_raises_auth_delivery_error(self) -> None:
        settings = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username="user",
            password="secret",
            from_address="noreply@example.com",
            use_tls=True,
            timeout=10,
        )

        class _BrokenSMTP(_FakeSMTP):
            def send_message(self, message: EmailMessage) -> None:
                raise OSError("connection reset")

        with patch("dictate.pro.email_delivery.smtplib.SMTP", _BrokenSMTP):
            with self.assertRaises(AuthDeliveryError) as ctx:
                send_auth_code(to_address="fail@example.com", code="123456", settings=settings)
        self.assertIn("failed to deliver", str(ctx.exception).lower())

    def test_send_auth_code_does_not_log_code(self) -> None:
        settings = SmtpSettings(
            host="smtp.example.com",
            port=587,
            username=None,
            password=None,
            from_address="noreply@example.com",
            use_tls=False,
            timeout=10,
        )

        class _BrokenSMTP(_FakeSMTP):
            def send_message(self, message: EmailMessage) -> None:
                raise OSError("connection reset")

        with patch("dictate.pro.email_delivery.smtplib.SMTP", _BrokenSMTP):
            with self.assertLogs("dictate.pro.email_delivery", level="WARNING") as logs:
                with self.assertRaises(AuthDeliveryError):
                    send_auth_code(to_address="quiet@example.com", code="654321", settings=settings)
        joined = "\n".join(logs.output)
        self.assertNotIn("654321", joined)


if __name__ == "__main__":
    unittest.main()
