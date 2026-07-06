"""Loopback Authorization Code + PKCE (S256) helpers for Dictate Pro browser sign-in.

Stdlib only, no new dependencies (matches the codebase's existing style). See
docs/desktop-browser-signin-architecture.md sections 3 and 5 for the design and
security rationale.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.server
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

CALLBACK_PATH = "/callback"
LISTENER_TIMEOUT_SECONDS = 300.0
DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

_SIGNED_IN_HTML = (
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>Dictate</title></head>"
    "<body style=\"font-family: sans-serif; text-align: center; padding-top: 4rem;\">"
    "<h1>Signed in</h1><p>You can close this tab and return to Dictate.</p>"
    "</body></html>"
)

_ERROR_HTML = (
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>Dictate</title></head>"
    "<body style=\"font-family: sans-serif; text-align: center; padding-top: 4rem;\">"
    "<h1>Sign-in failed</h1><p>You can close this tab and return to Dictate.</p>"
    "</body></html>"
)

_NOT_FOUND_HTML = "<!doctype html><html><body>Not found</body></html>"


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636, S256 only."""
    verifier = secrets.token_urlsafe(96)[:128]
    if len(verifier) < 43:  # extremely unlikely, but keep within the RFC bounds
        verifier = (verifier + secrets.token_urlsafe(32))[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    """High-entropy opaque CSRF token for the authorize round-trip."""
    return secrets.token_urlsafe(32)


@dataclass(slots=True)
class BrowserAuthAttempt:
    flow: str
    state: str
    code_verifier: str
    redirect_uri: str
    authorize_url: str
    expires_at: datetime
    # Device-code (RFC 8628) fields; unused (None) for a "loopback" flow attempt.
    device_code: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None
    interval: int | None = None
    # Monotonic timestamp of the last actual server poll (device-code only); lets the
    # client self-throttle to `interval` without hitting the server every call.
    last_poll: float | None = None


class LoopbackListener:
    """Single-use loopback HTTP listener for the OAuth authorization callback.

    Binds 127.0.0.1:0 (ephemeral port, chosen before the authorize URL exists) and
    serves exactly one GET /callback. All other paths 404. Idempotent close().
    """

    def __init__(self, *, state: str, timeout: float = LISTENER_TIMEOUT_SECONDS) -> None:
        self._state = state
        self._lock = threading.Lock()
        self._code: str | None = None
        self._error: str | None = None
        self._done = False
        self._closed = False
        self._deadline = time.monotonic() + timeout

        listener = self
        attempt_state = state

        class _Handler(http.server.BaseHTTPRequestHandler):
            server_version = "DictateLoopback/1.0"

            def log_message(self, fmt: str, *args: Any) -> None:  # noqa: N802
                return  # keep test/CLI output quiet; nothing sensitive is logged either way

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != CALLBACK_PATH:
                    self._reply(404, _NOT_FOUND_HTML)
                    return
                query = parse_qs(parsed.query)
                state_value = (query.get("state") or [""])[0]
                # Compare bytes, not str: hmac.compare_digest(str, str) requires ASCII-only
                # operands and raises TypeError otherwise -- a non-ASCII `state` query value
                # must fail the comparison cleanly, not blow up the request handler.
                if not hmac.compare_digest(state_value.encode("utf-8"), attempt_state.encode("utf-8")):
                    # A foreign/mismatched hit (stray local process, drive-by <img> probe, or
                    # an attacker who doesn't know the real state) must never be terminal --
                    # otherwise anyone who can reach this loopback port could kill a pending
                    # sign-in with e.g. GET /callback?error=x. Reply generically and keep
                    # serving; the real callback (correct state) can still arrive after this.
                    self._reply(200, _ERROR_HTML)
                    return
                error = (query.get("error") or [""])[0]
                code = (query.get("code") or [""])[0]
                if error:
                    listener._record_error(error)
                    self._reply(200, _ERROR_HTML)
                elif not code:
                    listener._record_error("invalid_request")
                    self._reply(200, _ERROR_HTML)
                else:
                    listener._record_code(code)
                    self._reply(200, _SIGNED_IN_HTML)

            def _reply(self, status: int, html: str) -> None:
                data = html.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

        self._httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.timeout = 0.2
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            while not self._closed and not self._done and time.monotonic() < self._deadline:
                try:
                    self._httpd.handle_request()
                except OSError:
                    break
        finally:
            with self._lock:
                if not self._done:
                    self._error = self._error or "timeout"
                    self._done = True

    @property
    def port(self) -> int:
        return self._port

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self._port}{CALLBACK_PATH}"

    def _record_code(self, code: str) -> None:
        with self._lock:
            if self._done:
                return
            self._code = code
            self._done = True

    def _record_error(self, error: str) -> None:
        with self._lock:
            if self._done:
                return
            self._error = error
            self._done = True

    def result(self) -> dict[str, Any]:
        """Non-blocking snapshot: {"status": "pending" | "code" | "error", ...}."""
        with self._lock:
            if self._code is not None:
                return {"status": "code", "code": self._code}
            if self._error is not None:
                return {"status": "error", "reason": self._error}
            if time.monotonic() >= self._deadline:
                return {"status": "error", "reason": "timeout"}
            return {"status": "pending"}

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._lock:
            if not self._done:
                self._done = True
                if self._error is None and self._code is None:
                    self._error = "cancelled"
        try:
            self._httpd.server_close()
        except OSError:
            pass
        self._thread.join(timeout=1.0)
