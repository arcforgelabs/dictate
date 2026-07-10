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

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        """Raw HTTP POST bypassing ProClient -- lets a test forge fields an honest client
        would never send (e.g. an attacker-supplied device_id or a non-ASCII client_id)."""
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def _get_pending_code(self, client: ProClient) -> tuple:
        """Drive a real loopback callback and return (attempt, code) without clearing state,
        so the test can forge its own token-exchange POST instead of calling poll_browser_sign_in."""
        attempt = client._browser_attempt
        listener = client._browser_listener
        assert attempt is not None and listener is not None
        outcome = listener.result()
        self.assertEqual(outcome["status"], "code")
        return attempt, outcome["code"]

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

        # Regression for a P1 finding: exchange_authorization_code() must register the
        # device (like complete_sign_in does for email code), or the session is dead on
        # arrival -- resolve_access_token()/refresh_session() both gate on device_is_known()
        # and would raise "device revoked" on the very first authenticated call.
        resolved_account_id, resolved_device_id = self.service.auth.resolve_access_token(session.access_token)
        self.assertEqual(resolved_account_id, account.account_id)
        self.assertEqual(resolved_device_id, session.device_id)

        stored = json.loads(self.session_path.read_text(encoding="utf-8"))
        stored["access_expires_at"] = "2000-01-01T00:00:00+00:00"
        self.session_path.write_text(json.dumps(stored), encoding="utf-8")
        refreshed = client.refresh_if_needed()
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.account_id, account.account_id)

    def test_device_public_key_is_registered_in_legacy_mode(self) -> None:
        # Regression for a P2 finding: poll_browser_sign_in() must thread device_public_key
        # into the authorization_code grant for legacy/reference servers (not call the
        # gateway-only device-register endpoint, which 404s under /v1).
        client = self._new_client()
        start = client.start_browser_sign_in(device_label="Keyed Desktop")
        location = self._drive_authorize(start["authorize_url"], dev_email="keyed@example.com")
        urllib.request.urlopen(location, timeout=10).read()  # noqa: S310

        result = client.poll_browser_sign_in(device_public_key="pubkey-loopback-1", device_label="Keyed Desktop")
        self.assertEqual(result["status"], "complete")

        account = self.service.store.get_account_by_email("keyed@example.com")
        assert account is not None
        device = self.service.store.get_device(account_id=account.account_id, device_id=result["device_id"])
        assert device is not None
        self.assertEqual(device.public_key, "pubkey-loopback-1")

    def test_register_device_rejects_cross_account_device_id_collision(self) -> None:
        # Regression for a P2 finding (store.register_device, A01 broken access control):
        # device_id is a global primary key, but a caller completing the authorization_code
        # grant for account A can supply an arbitrary device_id in the request body. Without
        # an account-scoped check, that would silently overwrite account B's device row
        # (label/public_key), even though device_is_known(A, B) still correctly blocks the
        # resulting session. The exchange must reject outright and leave B's row untouched.
        victim = self.service.store.get_or_create_account("victim@example.com")
        victim_device_id = self.service.store.register_device(
            account_id=victim.account_id,
            device_id="shared-device-id",
            label="Victim Laptop",
            public_key="victim-public-key",
        )
        before = self.service.store.get_device(account_id=victim.account_id, device_id=victim_device_id)
        assert before is not None

        client = self._new_client()
        start = client.start_browser_sign_in(device_label="Attacker Desktop")
        location = self._drive_authorize(start["authorize_url"], dev_email="attacker@example.com")
        urllib.request.urlopen(location, timeout=10).read()  # noqa: S310
        attempt, code = self._get_pending_code(client)

        status, body = self._post_json(
            "/v1/auth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": attempt.code_verifier,
                "redirect_uri": attempt.redirect_uri,
                "client_id": "dictate-desktop",
                "device_id": "shared-device-id",  # attacker-supplied; belongs to the victim
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("invalid_grant", body["error"])

        after = self.service.store.get_device(account_id=victim.account_id, device_id=victim_device_id)
        self.assertEqual(after, before)  # byte-for-byte untouched: label, public_key, signature

        client.cancel_browser_sign_in()

    def test_non_ascii_client_id_yields_400_invalid_grant_not_500(self) -> None:
        # Regression for a P3 finding: hmac.compare_digest(str, str) requires ASCII-only
        # operands and raises TypeError on non-ASCII input, which would otherwise bypass the
        # ValueError -> ApiError(400, "invalid_grant") mapping and surface as a bare 500.
        client = self._new_client()
        start = client.start_browser_sign_in(device_label="Test Desktop")
        location = self._drive_authorize(start["authorize_url"], dev_email="nonascii@example.com")
        urllib.request.urlopen(location, timeout=10).read()  # noqa: S310
        attempt, code = self._get_pending_code(client)

        status, body = self._post_json(
            "/v1/auth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": attempt.code_verifier,
                "redirect_uri": attempt.redirect_uri,
                "client_id": "dictate-desktopé",  # non-ASCII, must not raise TypeError server-side
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("invalid_grant", body["error"])

        client.cancel_browser_sign_in()

    def test_authorization_code_is_single_use_replay_returns_400_invalid_grant(self) -> None:
        # Pins RFC 9700 single-use behavior directly (previously only covered transitively
        # via the store's consume_auth_code plumbing): exchange a valid code once (succeeds),
        # then replay the exact same code -- it must be rejected, not silently re-issue a
        # second session.
        client = self._new_client()
        start = client.start_browser_sign_in(device_label="Test Desktop")
        location = self._drive_authorize(start["authorize_url"], dev_email="replay@example.com")
        urllib.request.urlopen(location, timeout=10).read()  # noqa: S310
        attempt, code = self._get_pending_code(client)

        token_payload = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": attempt.code_verifier,
            "redirect_uri": attempt.redirect_uri,
            "client_id": "dictate-desktop",
        }
        status, body = self._post_json("/v1/auth/token", token_payload)
        self.assertEqual(status, 200)
        self.assertIn("access_token", body)

        status, body = self._post_json("/v1/auth/token", token_payload)
        self.assertEqual(status, 400)
        self.assertIn("invalid_grant", body["error"])

        client.cancel_browser_sign_in()

    def test_code_verifier_outside_rfc7636_bounds_yields_400_invalid_grant(self) -> None:
        # Regression for enforcing RFC 7636 §4.1 code_verifier bounds (43-128 chars of
        # [A-Za-z0-9-._~]) server-side, ahead of arc-forge-console copying this contract.
        client = self._new_client()
        start = client.start_browser_sign_in(device_label="Test Desktop")
        location = self._drive_authorize(start["authorize_url"], dev_email="verifier-bounds@example.com")
        urllib.request.urlopen(location, timeout=10).read()  # noqa: S310
        attempt, code = self._get_pending_code(client)

        status, body = self._post_json(
            "/v1/auth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": "too-short",  # well under the 43-char RFC 7636 minimum
                "redirect_uri": attempt.redirect_uri,
                "client_id": "dictate-desktop",
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("invalid_grant", body["error"])

        client.cancel_browser_sign_in()

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

    def test_state_mismatch_is_ignored_without_token_exchange_and_real_callback_still_works(self) -> None:
        # Regression for a P3 finding: a state-mismatched hit (spliced-in code, or a foreign
        # local process/drive-by probe) must never be terminal -- otherwise anyone who can
        # reach the loopback port kills the attempt without knowing the real (secret) state.
        # The listener should ignore it and keep serving for the real callback.
        client = self._new_client()
        start = client.start_browser_sign_in(device_label="Test Desktop")
        listener = client._browser_listener
        assert listener is not None
        redirect_uri = listener.redirect_uri

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
        self.assertEqual(result["status"], "pending")
        self.assertEqual(calls, [])  # no token POST was attempted
        self.assertIsNotNone(client._browser_attempt)  # attempt survives the foreign hit
        self.assertFalse(client.signed_in())

        # The real callback (correct state) still completes normally afterwards.
        location = self._drive_authorize(start["authorize_url"], dev_email="state@example.com")
        urllib.request.urlopen(location, timeout=10).read()  # noqa: S310
        result = client.poll_browser_sign_in()
        self.assertEqual(result["status"], "complete")
        self.assertTrue(client.signed_in())

    def test_error_param_with_wrong_state_does_not_terminate_attempt(self) -> None:
        # Specifically the P3 DoS scenario: GET /callback?error=x from a process that
        # doesn't know the real state must not kill a pending sign-in.
        client = self._new_client()
        client.start_browser_sign_in(device_label="Test Desktop")
        listener = client._browser_listener
        assert listener is not None

        foreign_hit = f"{listener.redirect_uri}?error=access_denied&state=not-the-real-state"
        with urllib.request.urlopen(foreign_hit, timeout=10) as response:  # noqa: S310
            self.assertEqual(response.status, 200)

        result = client.poll_browser_sign_in()
        self.assertEqual(result["status"], "pending")

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
        # Episode 2: device-code (RFC 8628) is now real, so discovery advertises it again
        # (Episode 1 deliberately omitted it while unimplemented).
        self.assertIn("urn:ietf:params:oauth:grant-type:device_code", payload["grant_types_supported"])
        self.assertIn("device_authorization_endpoint", payload)

    def test_desktop_discovery_501s_without_dev_auto_approve(self) -> None:
        # Regression for a P2 finding: advertising capability the server can't actually
        # complete (authorize hard-501s without the dev flag) would strand the client
        # waiting on a browser tab that can never finish, instead of falling back to email.
        os.environ.pop("DICTATE_PRO_DEV_AUTO_APPROVE", None)
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"{self.base_url}/v1/auth/desktop", timeout=10)  # noqa: S310
            self.assertEqual(ctx.exception.code, 501)
        finally:
            os.environ["DICTATE_PRO_DEV_AUTO_APPROVE"] = "1"


if __name__ == "__main__":
    unittest.main()
