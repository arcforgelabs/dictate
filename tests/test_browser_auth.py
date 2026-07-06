"""Tests for the Dictate Pro browser sign-in (Authorization Code + PKCE, loopback)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from dictate.pro.client import ProClient, ProClientError
from dictate.pro.server import ProRequestHandler
from dictate.pro.service import ProService, ProSettings


class _NoFollowRedirect(urllib.request.HTTPRedirectHandler):
    """Disables automatic redirect-following for the authorize 302 so the test can inspect it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def _add_query(url: str, extra: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key, value in extra.items():
        query[key] = [value]
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode(query, doseq=True)}"


class BrowserAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DICTATE_PRO_DEV_AUTH"] = "1"
        os.environ["DICTATE_PRO_DEV_AUTO_APPROVE"] = "1"
        # Test environments have no OS keyring; allow the plaintext session fallback
        # (same opt-in save_session already offers for local/dev use).
        os.environ["DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS"] = "1"
        settings = ProSettings(data_dir=Path(self._tmp.name))
        self.service = ProService(settings)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ProRequestHandler)
        self.httpd.service = self.service  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.session_path = Path(self._tmp.name) / "pro-session.json"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self._tmp.cleanup()
        os.environ.pop("DICTATE_PRO_DEV_AUTH", None)
        os.environ.pop("DICTATE_PRO_DEV_AUTO_APPROVE", None)
        os.environ.pop("DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS", None)

    def _new_client(self) -> ProClient:
        return ProClient(base_url=self.base_url, session_path=self.session_path)

    def _drive_authorize(self, authorize_url: str, *, dev_email: str) -> str:
        """GET the authorize URL (auto-approve hook resolves dev_email); return the Location.

        urllib.request follows redirects by default, so a plain urlopen() would silently
        chase the 302 straight into the loopback listener. A no-op HTTPRedirectHandler
        stops that -- on CPython's redirect handling, refusing to follow (returning None
        from redirect_request) surfaces as HTTPError(302), not a 302 response object --
        catch that and read the Location header off it.
        """
        url = _add_query(authorize_url, {"dev_email": dev_email})
        opener = urllib.request.build_opener(_NoFollowRedirect)
        request = urllib.request.Request(url, method="GET")
        try:
            opener.open(request, timeout=10)
            self.fail("expected the authorize endpoint to redirect (302)")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 302)
            location = exc.headers.get("Location")
        self.assertIsNotNone(location)
        return location

    def test_loopback_sign_in_completes_and_persists_session(self) -> None:
        client = self._new_client()
        start = client.start_browser_sign_in(device_label="Test Desktop")
        self.assertEqual(start["flow"], "loopback")
        self.assertIn("authorize_url", start)

        location = self._drive_authorize(start["authorize_url"], dev_email="browser@example.com")

        # The loopback listener is a real HTTP server bound in start_browser_sign_in();
        # hitting it is exactly what the OS browser would do after the gateway 302s.
        with urllib.request.urlopen(location, timeout=10) as callback_response:  # noqa: S310
            self.assertEqual(callback_response.status, 200)
            html = callback_response.read().decode("utf-8")
        self.assertIn("Signed in", html)

        result = client.poll_browser_sign_in()
        self.assertEqual(result["status"], "complete")
        self.assertTrue(client.signed_in())

        account = self.service.store.get_account_by_email("browser@example.com")
        assert account is not None
        session = client.load_session()
        assert session is not None
        self.assertEqual(session.account_id, account.account_id)
        self.assertEqual(result["account_id"], account.account_id)

    def test_pkce_mismatch_is_rejected_and_no_session_saved(self) -> None:
        client = self._new_client()
        start = client.start_browser_sign_in(device_label="Test Desktop")
        location = self._drive_authorize(start["authorize_url"], dev_email="pkce@example.com")
        urllib.request.urlopen(location, timeout=10).read()  # noqa: S310

        # Corrupt the in-memory verifier so the token exchange's SHA-256 check fails.
        assert client._browser_attempt is not None
        client._browser_attempt.code_verifier = "wrong-verifier-" + "x" * 64

        with self.assertRaises(ProClientError) as ctx:
            client.poll_browser_sign_in()
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("invalid_grant", ctx.exception.message)

        self.assertFalse(client.signed_in())
        self.assertFalse(self.session_path.exists())
        # The failed attempt is still cleared (idempotent cleanup), not left dangling.
        self.assertIsNone(client._browser_attempt)

    def test_state_mismatch_errors_without_token_exchange(self) -> None:
        client = self._new_client()
        client.start_browser_sign_in(device_label="Test Desktop")
        listener = client._browser_listener
        assert listener is not None
        redirect_uri = listener.redirect_uri

        # Simulate a spliced-in callback with the wrong state (session-fixation attempt).
        bad_callback = f"{redirect_uri}?code=whatever-code&state=not-the-real-state"
        with urllib.request.urlopen(bad_callback, timeout=10) as response:  # noqa: S310
            self.assertEqual(response.status, 200)

        calls: list[tuple] = []
        original_request = client._request

        def _spy(*args, **kwargs):
            calls.append((args, kwargs))
            return original_request(*args, **kwargs)

        client._request = _spy  # type: ignore[method-assign]

        result = client.poll_browser_sign_in()
        self.assertEqual(result["status"], "error")
        self.assertIn("state", result["reason"])
        self.assertEqual(calls, [])  # no token POST was attempted
        self.assertFalse(client.signed_in())

    def test_capability_probe_404_raises_501_for_email_fallback(self) -> None:
        class _NoDesktopClient(ProClient):
            def _request(self, method, path, payload=None, *, auth=None, content_type="application/json"):
                if path.endswith("/auth/desktop"):
                    raise ProClientError(404, "no route for GET /v1/auth/desktop")
                raise AssertionError(f"unexpected request during capability fallback: {method} {path}")

        client = _NoDesktopClient(base_url=self.base_url, session_path=self.session_path)
        capabilities = client.desktop_auth_capabilities()
        self.assertIsNone(capabilities)

        with self.assertRaises(ProClientError) as ctx:
            client.start_browser_sign_in()
        self.assertEqual(ctx.exception.status, 501)

    def test_authorize_rejects_bad_redirect_uri_with_error_page_not_redirect(self) -> None:
        url = (
            f"{self.base_url}/v1/auth/authorize?response_type=code&client_id=dictate-desktop"
            "&redirect_uri=http://localhost:9999/callback&state=s&code_challenge=c"
            "&code_challenge_method=S256"
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url, timeout=10)  # noqa: S310
        self.assertEqual(ctx.exception.code, 400)
        body = ctx.exception.read().decode("utf-8")
        self.assertIn("Invalid client_id or redirect_uri", body)

    def test_discovery_endpoint_advertises_pkce_s256(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/v1/auth/desktop", timeout=10) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["code_challenge_methods_supported"], ["S256"])
        self.assertIn("authorization_code", payload["grant_types_supported"])


if __name__ == "__main__":
    unittest.main()
