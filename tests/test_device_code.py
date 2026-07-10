"""Tests for the Dictate Pro RFC 8628 device authorization grant (browser sign-in fallback)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from dictate.pro import auth as auth_module
from dictate.pro import server as server_module
from dictate.pro.client import ProClient, ProClientError
from dictate.pro.server import ProRequestHandler, _RateLimiter
from dictate.pro.service import ProService, ProSettings


def _post_json(base_url: str, path: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class DeviceCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        # Every swap below is registered via addCleanup *immediately* after it's made, so
        # restoration is unconditional -- it still runs even if a later line in setUp
        # raises (e.g. the HTTP server failing to bind), rather than only in tearDown
        # (which unittest skips entirely if setUp doesn't complete).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        os.environ["DICTATE_PRO_DEV_AUTH"] = "1"
        self.addCleanup(os.environ.pop, "DICTATE_PRO_DEV_AUTH", None)
        os.environ["DICTATE_PRO_DEV_AUTO_APPROVE"] = "1"
        self.addCleanup(os.environ.pop, "DICTATE_PRO_DEV_AUTO_APPROVE", None)
        # Test environment has no OS keyring; allow the plaintext session fallback.
        os.environ["DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS"] = "1"
        self.addCleanup(os.environ.pop, "DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS", None)

        # The server-side rate limiter is a module-level singleton shared across every
        # ThreadingHTTPServer instance in the process, including other test files' servers
        # running in the same pytest session. Device-code flows make several extra requests
        # per test (issue, poll x N, approve); swap in a generous limiter for this class so
        # it doesn't eat into (or get tripped by) other files' budget, and restore whatever
        # was there afterward so we don't mask a real rate-limit regression elsewhere.
        self.addCleanup(setattr, server_module, "_rate_limiter", server_module._rate_limiter)
        server_module._rate_limiter = _RateLimiter(rpm=100_000)

        settings = ProSettings(data_dir=Path(self._tmp.name))
        self.service = ProService(settings)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ProRequestHandler)
        self.httpd.service = self.service  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._shutdown_httpd)
        self.session_path = Path(self._tmp.name) / "pro-session.json"

    def _shutdown_httpd(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def _new_client(self) -> ProClient:
        return ProClient(base_url=self.base_url, session_path=self.session_path)

    def _approve(self, user_code: str, dev_email: str) -> None:
        status, body = _post_json(
            self.base_url,
            "/v1/auth/device/approve",
            {"user_code": user_code, "dev_email": dev_email},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["approved"])

    # --- Criteria 1 & 2: full sign-in, pending before approval, complete after, session works ---

    def test_polling_before_approval_returns_pending(self) -> None:
        # Isolated from the completion test below: this test's only poll is the device
        # code's first-ever poll, so it can't collide with the server's own interval gate
        # (which would otherwise turn a too-soon second poll into slow_down instead of the
        # authorization_pending this test is pinning).
        client = self._new_client()
        client.start_browser_sign_in(prefer="device_code", device_label="Test Desktop")
        pending = client.poll_browser_sign_in()
        self.assertEqual(pending["status"], "pending")
        self.assertFalse(client.signed_in())

    def test_device_code_sign_in_completes_and_session_works(self) -> None:
        client = self._new_client()
        start = client.start_browser_sign_in(prefer="device_code", device_label="Test Desktop")
        self.assertEqual(start["flow"], "device_code")
        self.assertRegex(start["user_code"], r"^[A-Z]{4}-[A-Z]{4}$")
        self.assertTrue(start["verification_uri"])
        self.assertIn(start["user_code"], start["verification_uri_complete"])
        self.assertEqual(start["interval"], 5)

        self._approve(start["user_code"], "devicecode@example.com")

        # Criterion 2 (after approval): poll now returns complete. This is the device code's
        # first-ever poll (see test_polling_before_approval_returns_pending for the pending
        # case), so it isn't subject to the server's interval throttle either.
        result = client.poll_browser_sign_in()
        self.assertEqual(result["status"], "complete")
        self.assertTrue(client.signed_in())

        account = self.service.store.get_account_by_email("devicecode@example.com")
        assert account is not None
        session = client.load_session()
        assert session is not None
        self.assertEqual(session.account_id, account.account_id)
        self.assertEqual(result["account_id"], account.account_id)

        # Criterion 1: identical downstream to email/loopback -- resolve_access_token()
        # succeeds and a refresh round-trip works (device registration parity with Episode 1).
        resolved_account_id, resolved_device_id = self.service.auth.resolve_access_token(session.access_token)
        self.assertEqual(resolved_account_id, account.account_id)
        self.assertEqual(resolved_device_id, session.device_id)

        stored = json.loads(self.session_path.read_text(encoding="utf-8"))
        stored["access_expires_at"] = "2000-01-01T00:00:00+00:00"
        self.session_path.write_text(json.dumps(stored), encoding="utf-8")
        refreshed = client.refresh_if_needed()
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.account_id, account.account_id)

    # --- Criterion 3: slow_down bumps the client's interval; expired/denied error out ---

    def test_slow_down_increases_client_interval(self) -> None:
        client = self._new_client()
        start = client.start_browser_sign_in(prefer="device_code", device_label="Test Desktop")
        self.assertEqual(start["interval"], 5)

        first = client.poll_browser_sign_in()
        self.assertEqual(first["status"], "pending")
        self.assertEqual(client._browser_attempt.interval, 5)

        # Force an immediate second poll (bypassing the client's own throttle) while the
        # server still remembers the very-recent last poll -- it must answer slow_down.
        client._browser_attempt.last_poll = None
        second = client.poll_browser_sign_in()
        self.assertEqual(second["status"], "pending")
        self.assertEqual(client._browser_attempt.interval, 10)  # bumped by 5 per RFC 8628 §3.5
        self.assertIsNotNone(client._browser_attempt)  # attempt survives slow_down

    def test_local_deadline_expires_pending_attempt_without_contacting_server(self) -> None:
        # P3 regression: the 429/5xx -> "pending" mapping has no TTL bound of its own, so a
        # persistently unreachable server would otherwise make poll_browser_sign_in()
        # return "pending" forever. The client must enforce its own deadline (the device
        # code's 900s TTL) independent of ever hearing back from the server.
        client = self._new_client()
        client.start_browser_sign_in(prefer="device_code", device_label="Test Desktop")
        client._browser_attempt.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        calls: list[tuple] = []
        original_request = client._request

        def _spy(*args, **kwargs):
            calls.append((args, kwargs))
            return original_request(*args, **kwargs)

        client._request = _spy  # type: ignore[method-assign]

        result = client.poll_browser_sign_in()
        self.assertEqual(result, {"status": "error", "reason": "expired_token"})
        self.assertEqual(calls, [])  # no token POST was attempted
        self.assertIsNone(client._browser_attempt)  # cleared on terminal error

    def test_expired_device_code_returns_error_status(self) -> None:
        # Seed an already-expired device_code directly (per the round's guidance) rather
        # than waiting out the real 900s TTL.
        payload = self.service.auth.create_device_code(client_id="dictate-desktop")
        device_code_hash = auth_module._hash_code(payload["device_code"])
        row = self.service.store.get_device_code(device_code_hash)
        assert row is not None
        with self.service.store._conn() as conn:  # noqa: SLF001
            conn.execute(
                "UPDATE device_codes SET expires_at = '2000-01-01T00:00:00+00:00' WHERE device_code_hash = ?",
                (device_code_hash,),
            )

        with self.assertRaises(ValueError) as ctx:
            self.service.auth.poll_device_code(device_code=payload["device_code"], client_id="dictate-desktop")
        self.assertEqual(str(ctx.exception), "expired_token")

        # P2 regression: poll_device_code discards the row immediately on expiry rather
        # than waiting for a future issuance's sweep to catch it.
        self.assertIsNone(self.service.store.get_device_code(device_code_hash))

    def test_device_code_issuance_purges_expired_rows(self) -> None:
        # P2 regression: the opportunistic purge must be reachable purely via issuance
        # (unauthenticated, ungated, attacker-controlled), since on a server with no
        # DICTATE_PRO_DEV_AUTO_APPROVE nothing can ever be approved/consumed -- the
        # consume_device_code purge path would never run at all. Unset the flag here so
        # this test matches that exact locked-down threat model rather than relying on
        # setUp's default (create_device_code itself was never gated by the flag either
        # way, so the proven code path is identical -- this just makes the scenario exact).
        os.environ.pop("DICTATE_PRO_DEV_AUTO_APPROVE", None)
        expired_hashes = []
        for _ in range(3):
            payload = self.service.auth.create_device_code(client_id="dictate-desktop")
            expired_hashes.append(auth_module._hash_code(payload["device_code"]))
        live_payload = self.service.auth.create_device_code(client_id="dictate-desktop")
        live_hash = auth_module._hash_code(live_payload["device_code"])

        with self.service.store._conn() as conn:  # noqa: SLF001
            conn.executemany(
                "UPDATE device_codes SET expires_at = '2000-01-01T00:00:00+00:00' WHERE device_code_hash = ?",
                [(h,) for h in expired_hashes],
            )
            count_before = conn.execute("SELECT COUNT(*) FROM device_codes").fetchone()[0]
        self.assertEqual(count_before, 4)

        # A fresh issuance must sweep the 3 now-expired rows before inserting its own --
        # this is the ONLY reachable purge point when nothing can ever be approved.
        newest_payload = self.service.auth.create_device_code(client_id="dictate-desktop")
        newest_hash = auth_module._hash_code(newest_payload["device_code"])

        with self.service.store._conn() as conn:  # noqa: SLF001
            remaining = {row[0] for row in conn.execute("SELECT device_code_hash FROM device_codes").fetchall()}
        for expired_hash in expired_hashes:
            self.assertNotIn(expired_hash, remaining)
        self.assertIn(live_hash, remaining)
        self.assertIn(newest_hash, remaining)
        self.assertEqual(len(remaining), 2)

    def test_access_denied_returns_error_status_via_http(self) -> None:
        client = self._new_client()
        start = client.start_browser_sign_in(prefer="device_code", device_label="Test Desktop")

        denied = self.service.auth.deny_device_code(user_code=start["user_code"])
        self.assertTrue(denied)

        client._browser_attempt.last_poll = None
        result = client.poll_browser_sign_in()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "access_denied")
        self.assertFalse(client.signed_in())
        self.assertIsNone(client._browser_attempt)  # cleared on terminal error

    # --- Criterion 4: discovery re-advertises device-code, still gated by dev-auto-approve ---
    # (covered in tests/test_browser_auth.py::test_discovery_endpoint_advertises_pkce_s256
    # and ::test_desktop_discovery_501s_without_dev_auto_approve, which this episode updated.)

    def test_device_code_approve_hook_501s_without_dev_auto_approve(self) -> None:
        # Only the headless dev-approve *shortcut* is gated -- issuing a device/user code
        # pair is real RFC 8628 behavior a client can request regardless (it just stays
        # "authorization_pending" forever without a portal or this shortcut to approve it).
        os.environ.pop("DICTATE_PRO_DEV_AUTO_APPROVE", None)
        try:
            status, issued = _post_json(
                self.base_url,
                "/v1/auth/device-code",
                {"client_id": "dictate-desktop", "scope": "dictate", "device_label": "Test Desktop"},
            )
            self.assertEqual(status, 200)
            self.assertIn("user_code", issued)

            status, body = _post_json(
                self.base_url,
                "/v1/auth/device/approve",
                {"user_code": issued["user_code"], "dev_email": "nobody@example.com"},
            )
            self.assertEqual(status, 501)
        finally:
            os.environ["DICTATE_PRO_DEV_AUTO_APPROVE"] = "1"

    def test_verification_uri_is_a_real_page_not_a_404(self) -> None:
        # P3 regression: RFC 8628 requires verification_uri to be retrievable.
        client = self._new_client()
        start = client.start_browser_sign_in(prefer="device_code", device_label="Test Desktop")
        with urllib.request.urlopen(start["verification_uri"], timeout=10) as response:  # noqa: S310
            self.assertEqual(response.status, 200)
            html = response.read().decode("utf-8")
        self.assertIn("Enter your code", html)

    # --- Criterion 5: prefer ladder ---

    def test_prefer_device_code_forces_device_code_flow(self) -> None:
        client = self._new_client()
        start = client.start_browser_sign_in(prefer="device_code", device_label="Test Desktop")
        self.assertEqual(start["flow"], "device_code")

    def test_prefer_auto_uses_loopback_when_it_can_bind(self) -> None:
        client = self._new_client()
        start = client.start_browser_sign_in(prefer="auto", device_label="Test Desktop")
        self.assertEqual(start["flow"], "loopback")

    def test_prefer_auto_falls_back_to_device_code_when_loopback_cannot_bind(self) -> None:
        client = self._new_client()
        with patch("dictate.pro.client.LoopbackListener", side_effect=OSError("no loopback ports available")):
            start = client.start_browser_sign_in(prefer="auto", device_label="Test Desktop")
        self.assertEqual(start["flow"], "device_code")

    def test_prefer_loopback_raises_501_when_capabilities_lack_authorization_code(self) -> None:
        class _DeviceCodeOnlyClient(ProClient):
            def _request(self, method, path, payload=None, *, auth=None, content_type="application/json"):
                if path.endswith("/auth/desktop"):
                    return {
                        "authorization_endpoint": "http://x/authorize",
                        "token_endpoint": "http://x/token",
                        "device_authorization_endpoint": "http://x/device-code",
                        "grant_types_supported": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
                        "code_challenge_methods_supported": ["S256"],
                    }
                raise AssertionError(f"unexpected request: {method} {path}")

        client = _DeviceCodeOnlyClient(base_url=self.base_url, session_path=self.session_path)
        with self.assertRaises(ProClientError) as ctx:
            client.start_browser_sign_in(prefer="loopback")
        self.assertEqual(ctx.exception.status, 501)


if __name__ == "__main__":
    unittest.main()
