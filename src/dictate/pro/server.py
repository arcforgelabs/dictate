"""HTTP server for the Dictate Pro control plane."""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from dictate.pro.auth import AuthDeliveryError
from dictate.pro.service import ProService, ProServiceError, ProSettings
from dictate.pro.stripe_handler import load_stripe_settings, verify_stripe_signature
from dictate.version import RELEASE_VERSION

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_UPLOAD_MAX_BYTES = 524_288_000  # 500 MB
DEFAULT_PORT = 18765

# Loopback-only redirect URIs per RFC 8252 §7.3 / §8.3: literal 127.0.0.1 or [::1],
# any port, path exactly "/callback". "localhost" is deliberately rejected (resolver
# hijack risk).
_LOOPBACK_REDIRECT_RE = re.compile(r"^http://(127\.0\.0\.1|\[::1\]):(\d{1,5})/callback$")
_DEV_AUTO_APPROVE_ENV = "DICTATE_PRO_DEV_AUTO_APPROVE"


def _dev_auto_approve_enabled() -> bool:
    return os.environ.get(_DEV_AUTO_APPROVE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _authorize_error_page(message: str) -> str:
    safe = (
        message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Sign-in error</title></head>"
        "<body style=\"font-family: sans-serif; text-align: center; padding-top: 4rem;\">"
        f"<h1>Sign-in error</h1><p>{safe}</p></body></html>"
    )


class _RateLimiter:
    def __init__(self, rpm: int) -> None:
        self._rpm = rpm
        self._lock = threading.Lock()
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        if self._rpm <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            cutoff = now - 60.0
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._rpm:
                return False
            self._timestamps.append(now)
            return True


_rate_limiter: _RateLimiter | None = None
_rate_limiter_lock = threading.Lock()


def _get_rate_limiter() -> _RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                rpm = int(os.environ.get("DICTATE_PRO_RPM", "120"))
                _rate_limiter = _RateLimiter(rpm)
    return _rate_limiter


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(slots=True)
class _Response:
    status: int
    body: Any


class ProRequestHandler(BaseHTTPRequestHandler):
    server_version = "DictateProServer/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("pro-server %s - %s", self.address_string(), fmt % args)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _read_json(self) -> dict[str, Any]:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(400, f"invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "JSON body must be an object")
        return payload

    def _send_json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _bearer_token(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip() or None
        return None

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path not in {"/healthz", "/v1/webhooks/stripe"} and not _get_rate_limiter().allow():
            self._send_json(429, {"error": "rate limit exceeded"})
            return
        service: ProService = self.server.service  # type: ignore[attr-defined]

        try:
            if path == "/healthz" and method == "GET":
                self._send_json(200, {"status": "ok", "version": RELEASE_VERSION})
                return
            response = self._route(service, method, path, parse_qs(parsed.query))
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
            return
        except ProServiceError as exc:
            self._send_json(exc.status, {"error": exc.message})
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("pro-server route failed")
            self._send_json(500, {"error": str(exc)})
            return
        if response is None:
            # The route already wrote a non-JSON response (redirect / HTML error page).
            return
        self._send_json(response.status, response.body)

    def _send_html(self, status: int, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _discovery_payload(self) -> dict[str, Any]:
        # Device-code (RFC 8628) is a later episode -- don't advertise the endpoint/grant
        # until it's actually implemented, or a discovery-honoring client would 404 on it.
        host = self.headers.get("Host") or f"{DEFAULT_HOST}:{DEFAULT_PORT}"
        base = f"http://{host}"
        return {
            "authorization_endpoint": f"{base}/v1/auth/authorize",
            "token_endpoint": f"{base}/v1/auth/token",
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
        }

    def _handle_authorize(self, service: ProService, query: dict[str, list[str]]) -> None:
        def first(name: str) -> str:
            values = query.get(name) or []
            return values[0].strip() if values else ""

        client_id = first("client_id")
        redirect_uri = first("redirect_uri")
        if client_id != "dictate-desktop" or not _LOOPBACK_REDIRECT_RE.match(redirect_uri):
            # Never redirect on redirect_uri/client_id validation failure (open-redirect guard).
            self._send_html(400, _authorize_error_page("Invalid client_id or redirect_uri."))
            return

        state = first("state")
        response_type = first("response_type")
        code_challenge = first("code_challenge")
        code_challenge_method = first("code_challenge_method")
        scope = first("scope") or "dictate"
        device_label = first("device_label") or "Desktop"

        def deny(error: str) -> None:
            params = {"error": error}
            if state:
                params["state"] = state
            self._send_redirect(f"{redirect_uri}?{urlencode(params)}")

        if response_type != "code" or not state or not code_challenge or code_challenge_method != "S256":
            deny("invalid_request")
            return

        if not _dev_auto_approve_enabled():
            self._send_html(
                501,
                _authorize_error_page(
                    "Interactive sign-in approval is not implemented on the reference server. "
                    f"Set {_DEV_AUTO_APPROVE_ENV}=1 for local development/testing only."
                ),
            )
            return

        dev_email = first("dev_email")
        if not dev_email:
            deny("invalid_request")
            return

        account = service.store.get_or_create_account(dev_email)
        code = service.auth.create_authorization_code(
            account_id=account.account_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            device_label=device_label,
        )
        self._send_redirect(f"{redirect_uri}?{urlencode({'code': code, 'state': state})}")

    def _handle_token_grant(self, service: ProService) -> _Response:
        body = self._read_json()
        grant_type = str(body.get("grant_type", "")).strip()
        if grant_type == "authorization_code":
            code = str(body.get("code", "")).strip()
            code_verifier = str(body.get("code_verifier", "")).strip()
            redirect_uri = str(body.get("redirect_uri", "")).strip()
            client_id = str(body.get("client_id", "")).strip()
            if not code or not code_verifier or not redirect_uri or not client_id:
                raise ApiError(400, "invalid_request")
            device_id = str(body.get("device_id") or "").strip() or None
            device_public_key = str(body.get("device_public_key") or "").strip() or None
            try:
                session = service.auth.exchange_authorization_code(
                    code=code,
                    code_verifier=code_verifier,
                    redirect_uri=redirect_uri,
                    client_id=client_id,
                    device_id=device_id,
                    device_public_key=device_public_key,
                )
            except ValueError as exc:
                raise ApiError(400, str(exc)) from exc
        elif grant_type == "refresh_token":
            refresh_token = str(body.get("refresh_token", "")).strip()
            if not refresh_token:
                raise ApiError(400, "invalid_request")
            try:
                session = service.auth.refresh_session(refresh_token)
            except ValueError as exc:
                raise ApiError(400, str(exc)) from exc
        else:
            raise ApiError(400, "unsupported_grant_type")
        return _Response(
            200,
            {
                "account_id": session.account_id,
                "device_id": session.device_id,
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "access_expires_at": session.access_expires_at,
                "refresh_expires_at": session.refresh_expires_at,
            },
        )

    def _route(self, service: ProService, method: str, path: str, query: dict[str, list[str]]) -> _Response | None:
        if path == "/v1/auth/start" and method == "POST":
            body = self._read_json()
            email = str(body.get("email", "")).strip()
            if not email:
                raise ApiError(400, "email is required")
            try:
                payload = service.auth.start_sign_in(email)
            except AuthDeliveryError as exc:
                raise ApiError(503, str(exc)) from exc
            return _Response(200, payload)

        if path == "/v1/auth/complete" and method == "POST":
            body = self._read_json()
            challenge_id = str(body.get("challenge_id", "")).strip()
            code = str(body.get("code", "")).strip()
            if not challenge_id or not code:
                raise ApiError(400, "challenge_id and code are required")
            try:
                session = service.auth.complete_sign_in(
                    challenge_id=challenge_id,
                    code=code,
                    device_id=str(body.get("device_id") or "").strip() or None,
                    device_label=str(body.get("device_label") or "Desktop"),
                    device_public_key=str(body.get("device_public_key") or "").strip() or None,
                )
            except ValueError as exc:
                raise ApiError(401, str(exc)) from exc
            return _Response(
                200,
                {
                    "account_id": session.account_id,
                    "device_id": session.device_id,
                    "access_token": session.access_token,
                    "refresh_token": session.refresh_token,
                    "access_expires_at": session.access_expires_at,
                    "refresh_expires_at": session.refresh_expires_at,
                },
            )

        if path == "/v1/auth/refresh" and method == "POST":
            body = self._read_json()
            refresh_token = str(body.get("refresh_token", "")).strip()
            if not refresh_token:
                raise ApiError(400, "refresh_token is required")
            try:
                session = service.auth.refresh_session(refresh_token)
            except ValueError as exc:
                raise ApiError(401, str(exc)) from exc
            return _Response(
                200,
                {
                    "account_id": session.account_id,
                    "device_id": session.device_id,
                    "access_token": session.access_token,
                    "refresh_token": session.refresh_token,
                    "access_expires_at": session.access_expires_at,
                    "refresh_expires_at": session.refresh_expires_at,
                },
            )

        if path == "/v1/auth/desktop" and method == "GET":
            if not _dev_auto_approve_enabled():
                # Advertising this endpoint when /v1/auth/authorize can't actually complete
                # (no portal on the reference server) would make the client bind a listener,
                # open a browser, and hang to the 300s timeout instead of falling back to
                # email code. Mirrors the real gateway, which only advertises once it can
                # complete authorize.
                raise ApiError(501, "browser sign-in is not available on this reference server")
            return _Response(200, self._discovery_payload())

        if path == "/v1/auth/authorize" and method == "GET":
            self._handle_authorize(service, query)
            return None

        if path == "/v1/auth/token" and method == "POST":
            return self._handle_token_grant(service)

        if path == "/v1/webhooks/stripe" and method == "POST":
            return self._handle_stripe_webhook(service)

        if path == "/v1/admin/grant-subscription" and method == "POST":
            self._require_admin()
            body = self._read_json()
            email = str(body.get("email", "")).strip()
            if not email:
                raise ApiError(400, "email is required")
            return _Response(
                200,
                service.grant_subscription_for_testing(
                    email=email,
                    status=str(body.get("status") or "active"),
                ),
            )

        if path == "/v1/admin/grant-access" and method == "POST":
            self._require_admin()
            body = self._read_json()
            email = str(body.get("email", "")).strip()
            if not email:
                raise ApiError(400, "email is required")
            expires_at = body.get("expires_at")
            return _Response(
                200,
                service.grant_access(
                    email=email,
                    plan_id=str(body.get("plan_id") or "dictate_pro_monthly"),
                    source=str(body.get("source") or "internal"),
                    status=str(body.get("status") or "active"),
                    expires_at=str(expires_at).strip() if expires_at else None,
                    note=str(body.get("note") or "").strip() or None,
                ),
            )

        if path == "/v1/admin/revoke-access" and method == "POST":
            self._require_admin()
            body = self._read_json()
            email = str(body.get("email", "")).strip()
            if not email:
                raise ApiError(400, "email is required")
            plan_id = str(body.get("plan_id") or "").strip() or None
            return _Response(200, service.revoke_access(email=email, plan_id=plan_id))

        account_id, device_id = self._require_account(service)
        if path == "/v1/me" and method == "GET":
            return _Response(200, service.get_me(account_id))
        if path == "/v1/entitlements" and method == "GET":
            return _Response(200, service.get_entitlements(account_id))
        if path == "/v1/usage/current" and method == "GET":
            return _Response(200, service.get_current_usage(account_id))
        if path == "/v1/devices" and method == "GET":
            return _Response(200, service.list_devices(account_id))
        if path == "/v1/devices/register" and method == "POST":
            body = self._read_json()
            return _Response(
                200,
                service.register_device(
                    account_id,
                    device_id,
                    device_id=str(body.get("device_id") or "").strip() or None,
                    device_label=str(body.get("device_label") or "Desktop"),
                    device_public_key=str(body.get("device_public_key") or "").strip(),
                ),
            )
        device_match = re.fullmatch(r"/v1/devices/([^/]+)/revoke", path)
        if device_match and method == "POST":
            return _Response(200, service.revoke_device(account_id, device_id, device_match.group(1)))
        device_approve_match = re.fullmatch(r"/v1/devices/([^/]+)/approve", path)
        if device_approve_match and method == "POST":
            body = self._read_json()
            envelope = body.get("envelope")
            if envelope is not None and not isinstance(envelope, dict):
                raise ApiError(400, "envelope must be a JSON object")
            return _Response(
                200,
                service.approve_device(
                    account_id,
                    device_id,
                    device_approve_match.group(1),
                    envelope=envelope,
                ),
            )
        if path == "/v1/devices/current/approve-with-recovery" and method == "POST":
            return _Response(200, service.approve_current_device_with_recovery(account_id, device_id))
        if path == "/v1/account/export" and method == "GET":
            return _Response(200, service.export_account_cloud_data(account_id, device_id))
        if path == "/v1/account/cloud-data" and method == "DELETE":
            return _Response(200, service.delete_account_cloud_data(account_id, device_id))
        if path == "/v1/sync/push" and method == "POST":
            body = self._read_json()
            records = body.get("records")
            if not isinstance(records, list):
                raise ApiError(400, "records must be a list")
            return _Response(200, service.push_sync_records(account_id, device_id, records))
        if path == "/v1/sync/changes" and method == "GET":
            since = _query_int(query, "since", 0)
            limit = _query_int(query, "limit", 500)
            return _Response(200, service.get_sync_changes(account_id, device_id, since=since, limit=limit))
        if path == "/v1/sync/cursor" and method == "POST":
            body = self._read_json()
            return _Response(200, service.update_sync_cursor(account_id, device_id, last_seq=int(body.get("last_seq") or 0)))
        if path == "/v1/sync/key-envelopes" and method == "GET":
            kind = query.get("kind", [""])[0].strip() or None
            return _Response(200, service.list_key_envelopes(account_id, device_id, envelope_kind=kind))
        if path == "/v1/sync/key-envelopes" and method == "POST":
            body = self._read_json()
            envelope = body.get("envelope")
            if not isinstance(envelope, dict):
                raise ApiError(400, "envelope must be a JSON object")
            return _Response(
                200,
                service.save_key_envelope(
                    account_id,
                    device_id,
                    envelope_kind=str(body.get("envelope_kind") or body.get("kind") or ""),
                    envelope=envelope,
                ),
            )
        if path == "/v1/meetings" and method == "POST":
            body = self._read_json()
            return _Response(
                200,
                service.create_meeting_job(
                    account_id=account_id,
                    device_id=device_id or "",
                    language=str(body.get("language") or "").strip() or None,
                    mode=str(body.get("mode") or "batch_meeting"),
                ),
            )

        meeting_match = re.fullmatch(r"/v1/meetings/([^/]+)(/audio|/transcript)?", path)
        if meeting_match:
            job_id = meeting_match.group(1)
            suffix = meeting_match.group(2)
            if suffix == "/audio" and method == "POST":
                return _Response(200, self._handle_audio_upload(service, account_id, job_id))
            if suffix == "/transcript" and method == "GET":
                return _Response(200, service.get_meeting_transcript(account_id, job_id))
            if suffix is None and method == "GET":
                return _Response(200, service.get_meeting_job(account_id, job_id))

        raise ApiError(404, f"no route for {method} {path}")

    def _require_account(self, service: ProService) -> tuple[str, str | None]:
        token = self._bearer_token()
        if not token:
            raise ApiError(401, "unauthorized")
        try:
            return service.auth.resolve_access_token(token)
        except ValueError as exc:
            raise ApiError(401, "unauthorized") from exc

    def _require_admin(self) -> None:
        expected = os.environ.get("DICTATE_PRO_ADMIN_TOKEN", "").strip()
        if not expected:
            raise ApiError(503, "admin token is not configured")
        supplied = self._bearer_token() or ""
        if supplied != expected:
            raise ApiError(401, "unauthorized")

    def _handle_stripe_webhook(self, service: ProService) -> _Response:
        max_bytes = int(os.environ.get("DICTATE_PRO_WEBHOOK_MAX_BYTES", "1000000"))
        content_length = int(self.headers.get("Content-Length") or "0")
        if content_length > max_bytes:
            raise ApiError(413, "webhook payload too large")
        settings = load_stripe_settings()
        payload = self._read_body()
        signature = self.headers.get("Stripe-Signature", "")
        dev_mode = os.environ.get("DICTATE_PRO_STRIPE_DEV", "").strip() == "1"
        if not settings.webhook_secret and not dev_mode:
            raise ApiError(503, "stripe webhook secret not configured")
        if settings.webhook_secret and not verify_stripe_signature(payload, signature, settings.webhook_secret):
            raise ApiError(400, "invalid stripe signature")
        try:
            event = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(400, "invalid stripe payload") from exc
        if not isinstance(event, dict):
            raise ApiError(400, "invalid stripe payload")
        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        data = event.get("data")
        object_payload = data.get("object") if isinstance(data, dict) else None
        if not event_id or not event_type or not isinstance(object_payload, dict):
            raise ApiError(400, "invalid stripe event")
        event_created_raw = event.get("created")
        event_created = event_created_raw if isinstance(event_created_raw, int) else None
        result = service.stripe.handle(
            event_id=event_id,
            event_type=event_type,
            payload=object_payload,
            event_created=event_created,
        )
        return _Response(200, result)

    def _handle_audio_upload(self, service: ProService, account_id: str, job_id: str) -> dict[str, Any]:
        max_bytes = int(os.environ.get("DICTATE_PRO_UPLOAD_MAX_BYTES", str(DEFAULT_UPLOAD_MAX_BYTES)))
        content_length = int(self.headers.get("Content-Length") or "0")
        if content_length > max_bytes:
            raise ApiError(413, "audio upload too large")
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            raise ApiError(400, "use raw audio body uploads for now")
        payload = self._read_body()
        if not payload:
            raise ApiError(400, "audio body is required")
        suffix = _audio_suffix(content_type)
        path = service.save_uploaded_audio(suffix, payload)
        try:
            return service.upload_meeting_audio(account_id=account_id, job_id=job_id, audio_path=path)
        finally:
            try:
                path.unlink(missing_ok=True)
                path.parent.rmdir()
            except OSError:
                pass

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")


def _audio_suffix(content_type: str) -> str:
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip() or "audio/wav")
    return guessed or ".wav"


def _query_int(query: dict[str, list[str]], key: str, default: int) -> int:
    values = query.get(key) or []
    if not values:
        return default
    try:
        return int(values[0])
    except (TypeError, ValueError):
        raise ApiError(400, f"{key} must be an integer")


def serve(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    data_dir: Path | None = None,
) -> None:
    root = data_dir or Path(os.environ.get("DICTATE_PRO_DATA_DIR", "")).expanduser()
    if not str(root):
        from dictate.platform_paths import user_data_dir

        root = user_data_dir() / "pro-server"
    settings = ProSettings(data_dir=root, stripe_settings=load_stripe_settings())
    service = ProService(settings)
    httpd = ThreadingHTTPServer((host, port), ProRequestHandler)
    httpd.service = service  # type: ignore[attr-defined]
    logger.info("Dictate Pro server listening on http://%s:%s", host, port)
    httpd.serve_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    host = os.environ.get("DICTATE_PRO_HOST", DEFAULT_HOST)
    port = int(os.environ.get("DICTATE_PRO_PORT", str(DEFAULT_PORT)))
    serve(host=host, port=port)
