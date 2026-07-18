"""Desktop client for the Dictate Pro control plane."""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dictate.api_keys import (
    ApiKeyStorageError,
    clear_pro_refresh_token,
    read_pro_refresh_token,
    save_pro_refresh_token,
)
from dictate.platform_paths import user_data_dir
from dictate.pro.hosted_result import (
    ExpectedHostedResult,
    HostedResultError,
    HostedResultKey,
    HostedResultKeyStore,
    HostedResultPendingStore,
    decrypt_hosted_result,
)
from dictate.pro.platform_state import (
    build_convergence_state,
    classify_pro_client_error,
    should_clear_session_on_error,
)
from dictate.pro.browser_auth import (
    DEVICE_CODE_GRANT_TYPE,
    BrowserAuthAttempt,
    LoopbackListener,
    generate_pkce,
    generate_state,
)
from dictate.sync import EncryptedSyncRecord, SyncOutbox

DEFAULT_API_URL = "https://console.arcforge.au"
SESSION_PATH = user_data_dir() / "pro-session.json"

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _clamp_verification_uri(uri: str) -> str:
    """Only allow https, or http on a loopback host (dev/reference server).

    verification_uri(_complete) come verbatim from the gateway's device-code
    response -- unlike authorize_url (client-constructed, see _start_loopback),
    these are attacker-controlled if the gateway is compromised or MITM'd. A
    javascript:/file:/custom-scheme value here would otherwise reach
    webbrowser.open()/window.open() unfiltered. Blanking degrades gracefully:
    the user still has the user_code to enter manually.
    """
    if not uri:
        return ""
    try:
        parsed = urllib.parse.urlparse(uri)
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    if scheme == "https":
        return uri
    if scheme == "http" and (parsed.hostname or "").lower() in _LOOPBACK_HOSTS:
        return uri
    logger.warning("Discarding unsafe verification_uri scheme from gateway: %r", uri)
    return ""


@dataclass(slots=True)
class ProSession:
    account_id: str
    device_id: str
    access_token: str
    refresh_token: str
    access_expires_at: str
    refresh_expires_at: str


class ProClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        session_path: Path = SESSION_PATH,
        hosted_result_keys: HostedResultKeyStore | None = None,
        hosted_result_pending: HostedResultPendingStore | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("DICTATE_PRO_API_URL") or DEFAULT_API_URL
        ).rstrip("/")
        self.session_path = session_path
        self.hosted_result_pending = hosted_result_pending or HostedResultPendingStore()
        self.hosted_result_keys = hosted_result_keys or HostedResultKeyStore(
            purge_pending=self.hosted_result_pending.purge_recipient
        )
        self._pending_email: str = ""
        self._desktop_capabilities: dict[str, Any] | None = None
        self._desktop_capabilities_probed: bool = False
        self._browser_attempt: BrowserAuthAttempt | None = None
        self._browser_listener: LoopbackListener | None = None

    def load_session(self) -> ProSession | None:
        if not self.session_path.is_file():
            return None
        try:
            raw = json.loads(self.session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        refresh_token = self._load_refresh_token(raw)
        required = (
            "account_id",
            "device_id",
            "access_token",
            "access_expires_at",
            "refresh_expires_at",
        )
        if not refresh_token or not all(raw.get(key) for key in required):
            return None
        return ProSession(
            account_id=str(raw["account_id"]),
            device_id=str(raw["device_id"]),
            access_token=str(raw["access_token"]),
            refresh_token=refresh_token,
            access_expires_at=str(raw["access_expires_at"]),
            refresh_expires_at=str(raw["refresh_expires_at"]),
        )

    def save_session(self, session: ProSession) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, str] = {
            "account_id": session.account_id,
            "device_id": session.device_id,
            "access_token": session.access_token,
            "access_expires_at": session.access_expires_at,
            "refresh_expires_at": session.refresh_expires_at,
        }
        if self._save_refresh_token(session.refresh_token):
            payload.pop("refresh_token", None)
        elif _plaintext_tokens_allowed():
            logger.warning(
                "OS secret store unavailable; persisting refresh token in plaintext %s",
                self.session_path,
            )
            payload["refresh_token"] = session.refresh_token
        else:
            raise ProClientError(
                503,
                "OS secret store unavailable and plaintext token fallback is disabled. "
                "Set DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS=1 for development only.",
            )
        self.session_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(self.session_path, 0o600)
        except OSError:
            pass

    def clear_session(self) -> None:
        self._clear_refresh_token()
        try:
            self.session_path.unlink(missing_ok=True)
        except OSError:
            pass

    def signed_in(self) -> bool:
        return self.load_session() is not None

    def start_sign_in(self, email: str) -> dict[str, Any]:
        email = email.strip().lower()
        self._pending_email = email
        if self._uses_arcforge_gateway():
            response = self._request("POST", "/api/account/auth/login-code", {"email": email})
            return {**response, "challenge_id": email, "email": email}
        return self._request("POST", "/v1/auth/start", {"email": email})

    def complete_sign_in(
        self,
        *,
        challenge_id: str,
        code: str,
        device_label: str = "Desktop",
        device_public_key: str | None = None,
    ) -> ProSession:
        session_data = self.load_session()
        payload = {
            "challenge_id": challenge_id,
            "code": code,
            "device_label": device_label,
        }
        if session_data:
            payload["device_id"] = session_data.device_id
        if device_public_key:
            payload["device_public_key"] = device_public_key
        if self._uses_arcforge_gateway():
            email = (self._pending_email or challenge_id).strip().lower()
            response = self._request("POST", "/api/account/auth/verify-code", {"email": email, "code": code})
            session = self._session_from_arcforge_auth_response(response)
            if device_public_key:
                session = self._register_gateway_device(
                    session,
                    device_label=device_label,
                    device_public_key=device_public_key,
                )
        else:
            response = self._request("POST", "/v1/auth/complete", payload)
            session = ProSession(
                account_id=str(response["account_id"]),
                device_id=str(response["device_id"]),
                access_token=str(response["access_token"]),
                refresh_token=str(response["refresh_token"]),
                access_expires_at=str(response["access_expires_at"]),
                refresh_expires_at=str(response["refresh_expires_at"]),
            )
        self.save_session(session)
        return session

    def desktop_auth_capabilities(self) -> dict[str, Any] | None:
        """Probe the browser sign-in discovery endpoint; cache the result for the process.

        Governed purely by the capability probe (not a gateway-vs-legacy mode gate): a
        404/405/501 means "email code only" regardless of whether we're pointed at the
        Arc Forge gateway or a local/legacy server that simply hasn't shipped it.
        """
        if self._desktop_capabilities_probed:
            return self._desktop_capabilities
        try:
            capabilities = self._request("GET", self._auth_path("desktop"))
        except ProClientError as exc:
            if exc.status in {404, 405, 501}:
                self._desktop_capabilities = None
                self._desktop_capabilities_probed = True
                return None
            raise
        self._desktop_capabilities = capabilities
        self._desktop_capabilities_probed = True
        return capabilities

    def start_browser_sign_in(self, *, device_label: str = "Desktop", prefer: str = "auto") -> dict[str, Any]:
        """Fallback ladder: prefer="loopback"/"device_code" forces that flow (raising 501 if
        the server doesn't advertise it); prefer="auto" tries loopback first (best UX when
        binding succeeds), then device-code, then 501 (caller falls back to email).
        """
        capabilities = self.desktop_auth_capabilities()
        if capabilities is None:
            raise ProClientError(501, "Browser sign-in is unavailable on this Dictate Pro server")
        self.cancel_browser_sign_in()  # one attempt at a time
        grants = capabilities.get("grant_types_supported") or []
        supports_loopback = "authorization_code" in grants
        supports_device_code = DEVICE_CODE_GRANT_TYPE in grants

        if prefer == "loopback":
            if not supports_loopback:
                raise ProClientError(501, "Loopback sign-in is not advertised by this server")
            return self._start_loopback(device_label)
        if prefer == "device_code":
            if not supports_device_code:
                raise ProClientError(501, "Device-code sign-in is not advertised by this server")
            return self._start_device_code(device_label)

        # prefer == "auto" (or anything else): loopback -> device_code -> 501.
        if supports_loopback:
            try:
                return self._start_loopback(device_label)
            except ProClientError:
                if not supports_device_code:
                    raise
        if supports_device_code:
            return self._start_device_code(device_label)
        raise ProClientError(501, "Browser sign-in is unavailable on this Dictate Pro server")

    def _start_loopback(self, device_label: str) -> dict[str, Any]:
        code_verifier, code_challenge = generate_pkce()
        state = generate_state()
        try:
            listener = LoopbackListener(state=state)
        except OSError as exc:
            raise ProClientError(503, f"Could not bind a local loopback listener: {exc}") from exc
        self._browser_listener = listener
        redirect_uri = listener.redirect_uri
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": "dictate-desktop",
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "scope": "dictate",
                "device_label": device_label,
            }
        )
        authorize_url = f"{self.base_url}{self._auth_path('authorize')}?{query}"
        self._browser_attempt = BrowserAuthAttempt(
            flow="loopback",
            state=state,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            authorize_url=authorize_url,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
        )
        return {"flow": "loopback", "authorize_url": authorize_url, "expires_in": 300}

    def _start_device_code(self, device_label: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            self._auth_path("device-code"),
            {"client_id": "dictate-desktop", "scope": "dictate", "device_label": device_label},
        )
        device_code = str(response["device_code"])
        user_code = str(response["user_code"])
        interval = int(response.get("interval") or 5)
        expires_in = int(response.get("expires_in") or 900)
        verification_uri = _clamp_verification_uri(str(response.get("verification_uri") or ""))
        verification_uri_complete = _clamp_verification_uri(str(response.get("verification_uri_complete") or ""))
        self._browser_attempt = BrowserAuthAttempt(
            flow="device_code",
            state="",
            code_verifier="",
            redirect_uri="",
            authorize_url="",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            interval=interval,
        )
        return {
            "flow": "device_code",
            "user_code": user_code,
            "verification_uri": verification_uri,
            "verification_uri_complete": verification_uri_complete,
            "expires_in": expires_in,
            "interval": interval,
        }

    def poll_browser_sign_in(
        self,
        *,
        device_public_key: str | None = None,
        device_label: str = "Desktop",
    ) -> dict[str, Any]:
        attempt = self._browser_attempt
        if attempt is None:
            return {"status": "error", "reason": "no_pending_attempt"}
        if attempt.flow == "device_code":
            return self._poll_device_code(attempt, device_public_key=device_public_key, device_label=device_label)

        listener = self._browser_listener
        if listener is None:
            return {"status": "error", "reason": "no_pending_attempt"}
        outcome = listener.result()
        if outcome["status"] == "pending":
            return {"status": "pending"}
        if outcome["status"] == "error":
            self.cancel_browser_sign_in()
            return {"status": "error", "reason": outcome.get("reason", "unknown")}
        code = outcome["code"]
        payload: dict[str, Any] = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": attempt.code_verifier,
            "redirect_uri": attempt.redirect_uri,
            "client_id": "dictate-desktop",
        }
        uses_gateway = self._uses_arcforge_gateway()
        if not uses_gateway:
            # Legacy/reference servers register the device as part of the grant itself
            # (mirrors complete_sign_in's /v1/auth/complete payload) rather than via a
            # separate gateway-only device-register call.
            existing_session = self.load_session()
            if existing_session:
                payload["device_id"] = existing_session.device_id
            if device_public_key:
                payload["device_public_key"] = device_public_key
        try:
            response = self._request("POST", self._auth_path("token"), payload)
            session = self._session_from_token_response(response)
            if device_public_key and uses_gateway:
                session = self._register_gateway_device(
                    session,
                    device_label=device_label,
                    device_public_key=device_public_key,
                )
            self.save_session(session)
        except ProClientError as exc:
            return {"status": "error", "reason": exc.message or "token_exchange_failed"}
        finally:
            self.cancel_browser_sign_in()
        return {"status": "complete", "account_id": session.account_id, "device_id": session.device_id}

    def _poll_device_code(
        self,
        attempt: BrowserAuthAttempt,
        *,
        device_public_key: str | None,
        device_label: str,
    ) -> dict[str, Any]:
        if datetime.now(timezone.utc) > attempt.expires_at:
            # Local deadline, independent of the server: the 429/5xx -> "pending" mapping
            # has no TTL bound on its own, so a persistently unreachable server would
            # otherwise make poll_browser_sign_in() return "pending" forever. Bound it to
            # the 900s device-code TTL so the caller's poll loop (Episode 3's UI) always
            # terminates.
            self.cancel_browser_sign_in()
            return {"status": "error", "reason": "expired_token"}
        interval = attempt.interval or 5
        now = time.monotonic()
        if attempt.last_poll is not None and (now - attempt.last_poll) < interval:
            # Self-throttle: don't hit the server faster than the (possibly slow_down-bumped)
            # interval: the caller polls on its own cadence (e.g. every second) but we only
            # forward to the server at most once per `interval`.
            return {"status": "pending"}
        attempt.last_poll = now
        payload: dict[str, Any] = {
            "grant_type": DEVICE_CODE_GRANT_TYPE,
            "device_code": attempt.device_code,
            "client_id": "dictate-desktop",
        }
        uses_gateway = self._uses_arcforge_gateway()
        if not uses_gateway:
            existing_session = self.load_session()
            if existing_session:
                payload["device_id"] = existing_session.device_id
            if device_public_key:
                payload["device_public_key"] = device_public_key
        try:
            response = self._request("POST", self._auth_path("token"), payload)
        except ProClientError as exc:
            reason = (exc.message or "").strip()
            if reason == "authorization_pending":
                return {"status": "pending"}
            if reason == "slow_down":
                attempt.interval = interval + 5
                return {"status": "pending"}
            if reason in {"expired_token", "access_denied"}:
                self.cancel_browser_sign_in()
                return {"status": "error", "reason": reason}
            if exc.status == 429 or exc.status >= 500:
                # Transient/transport-level hiccup (rate limit, momentary 5xx, or the
                # "service unreachable" 503 _request synthesizes for a URLError) -- don't
                # fail the whole sign-in attempt over one blip. Keep the attempt alive and
                # let the caller's poll loop naturally retry on its own cadence.
                return {"status": "pending"}
            raise
        session = self._session_from_token_response(response)
        if device_public_key and uses_gateway:
            session = self._register_gateway_device(
                session,
                device_label=device_label,
                device_public_key=device_public_key,
            )
        self.save_session(session)
        self.cancel_browser_sign_in()
        return {"status": "complete", "account_id": session.account_id, "device_id": session.device_id}

    def cancel_browser_sign_in(self) -> None:
        if self._browser_listener is not None:
            self._browser_listener.close()
        self._browser_listener = None
        self._browser_attempt = None

    def refresh_if_needed(self) -> ProSession | None:
        session = self.load_session()
        if session is None:
            return None
        expires_at = datetime.fromisoformat(session.access_expires_at)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < expires_at - timedelta(minutes=1):
            return session
        response = self._request(
            "POST",
            "/api/account/auth/token" if self._uses_arcforge_gateway() else "/v1/auth/refresh",
            {"grant_type": "refresh_token", "refresh_token": session.refresh_token}
            if self._uses_arcforge_gateway()
            else {"refresh_token": session.refresh_token},
        )
        refreshed = (
            self._session_from_arcforge_auth_response(response, fallback=session)
            if self._uses_arcforge_gateway()
            else ProSession(
                account_id=str(response["account_id"]),
                device_id=str(response["device_id"]),
                access_token=str(response["access_token"]),
                refresh_token=str(response["refresh_token"]),
                access_expires_at=str(response["access_expires_at"]),
                refresh_expires_at=str(response["refresh_expires_at"]),
            )
        )
        self.save_session(refreshed)
        return refreshed

    def get_state(self) -> dict[str, Any]:
        session = self.refresh_if_needed()
        if session is None:
            return {
                "signedIn": False,
                "entitlements": None,
                "usage": None,
                "account": None,
                "commerce": None,
                "convergence": build_convergence_state(
                    signed_in=False,
                    entitlements=None,
                    provider_mode="private",
                    sync_enabled=False,
                ),
            }
        try:
            if self._uses_arcforge_gateway():
                account = {"account_id": session.account_id, "device_id": session.device_id}
                commerce = self._request("GET", "/api/account/commerce", auth=session.access_token)
                entitlements = self._request("GET", "/api/dictate/entitlement", auth=session.access_token)
                usage = None
                if entitlements.get("active"):
                    usage = self._request("GET", "/api/dictate/usage", auth=session.access_token)
            else:
                account = self._request("GET", "/v1/me", auth=session.access_token)
                commerce = None
                entitlements = self._request("GET", "/v1/entitlements", auth=session.access_token)
                usage = self._request("GET", "/v1/usage/current", auth=session.access_token)
        except ProClientError as exc:
            error_code = classify_pro_client_error(exc.status, exc.message)
            if should_clear_session_on_error(error_code):
                self.clear_session()
                return {
                    "signedIn": False,
                    "entitlements": None,
                    "usage": None,
                    "account": None,
                    "commerce": None,
                    "lastError": error_code,
                    "convergence": build_convergence_state(
                        signed_in=False,
                        entitlements=None,
                        provider_mode="private",
                        sync_enabled=False,
                        last_error=error_code,
                    ),
                }
            return {
                "signedIn": True,
                "account": {"account_id": session.account_id, "device_id": session.device_id},
                "commerce": None,
                "entitlements": None,
                "usage": None,
                "apiUrl": self.base_url,
                "lastError": error_code,
                "convergence": build_convergence_state(
                    signed_in=True,
                    entitlements=None,
                    provider_mode="private",
                    sync_enabled=False,
                    last_error=error_code,
                ),
            }
        return {
            "signedIn": True,
            "account": account,
            "commerce": commerce,
            "entitlements": entitlements,
            "usage": usage,
            "apiUrl": self.base_url,
            "convergence": build_convergence_state(
                signed_in=True,
                entitlements=entitlements if isinstance(entitlements, dict) else None,
                provider_mode="online" if self._uses_arcforge_gateway() else "private",
                sync_enabled=bool(entitlements.get("active")) if isinstance(entitlements, dict) else False,
                sync_state="enabled" if isinstance(entitlements, dict) and entitlements.get("active") else "disabled",
            ),
        }

    def create_meeting(
        self,
        *,
        language: str | None = None,
        audio_duration_seconds: float | None = None,
        capability: str | None = None,
        requested_diarization: bool | None = None,
        mode: str = "batch_meeting",
    ) -> dict[str, Any]:
        session = self._require_session()
        if self._uses_arcforge_gateway():
            if audio_duration_seconds is None or audio_duration_seconds <= 0:
                raise ProClientError(400, "audio_duration_seconds is required for hosted Dictate jobs")
            payload: dict[str, Any] = {
                "device_id": session.device_id,
                "audio_duration_seconds": audio_duration_seconds,
            }
            if mode != "batch_meeting":
                payload["mode"] = mode
            if language:
                payload["language"] = language
            if capability:
                payload["capability"] = capability
            if requested_diarization is not None:
                payload["requested_diarization"] = requested_diarization
            return self._request("POST", "/api/dictate/jobs", payload, auth=session.access_token)
        payload = {}
        if mode != "batch_meeting":
            payload["mode"] = mode
        if language:
            payload["language"] = language
        return self._request("POST", "/v1/meetings", payload, auth=session.access_token)

    def upload_meeting_audio(self, job_id: str, audio_path: Path) -> dict[str, Any]:
        session = self._require_session()
        data = audio_path.read_bytes()
        if self._uses_arcforge_gateway():
            try:
                return self._upload_meeting_audio_signed(job_id, data, auth=session.access_token)
            except ProClientError as exc:
                if exc.status not in {404, 405, 409, 501}:
                    raise
                logger.info("Dictate signed upload unavailable; falling back to gateway body upload")
        return self._request(
            "POST",
            self._dictate_job_path(job_id, suffix="/audio"),
            data,
            content_type="audio/wav",
            auth=session.access_token,
        )

    def _upload_meeting_audio_signed(self, job_id: str, data: bytes, *, auth: str) -> dict[str, Any]:
        signed = self._request(
            "POST",
            self._dictate_job_path(job_id, suffix="/audio-upload-url"),
            {"byte_size": len(data)},
            auth=auth,
        )
        upload = signed.get("upload")
        upload_id = str(upload.get("upload_id") if isinstance(upload, dict) else "").strip()
        upload_url = str(signed.get("url") or "").strip()
        if not upload_id or not upload_url:
            raise ProClientError(502, "Arc Forge signed upload response was incomplete")
        self._put_signed_upload(upload_url, data, content_type="audio/wav")
        return self._request(
            "POST",
            self._dictate_job_path(job_id, suffix="/audio-upload-complete"),
            {"upload_id": upload_id, "byte_size": len(data)},
            auth=auth,
        )

    def _put_signed_upload(self, url: str, data: bytes, *, content_type: str) -> None:
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": content_type},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProClientError(exc.code, detail or "Signed upload failed") from exc
        except urllib.error.URLError as exc:
            raise ProClientError(503, f"Signed upload unreachable: {exc.reason}") from exc

    def get_meeting(self, job_id: str) -> dict[str, Any]:
        session = self._require_session()
        return self._request("GET", self._dictate_job_path(job_id), auth=session.access_token)

    def get_transcript(self, job_id: str) -> dict[str, Any]:
        session = self._require_session()
        return self._request("GET", self._dictate_job_path(job_id, suffix="/transcript"), auth=session.access_token)

    def get_result(self, job_id: str) -> dict[str, Any]:
        session = self._require_session()
        return self._request("GET", self._dictate_job_path(job_id, suffix="/result"), auth=session.access_token)

    def ensure_hosted_result_key(self, *, rotate: bool = False) -> HostedResultKey:
        """Register the device's active result key without exposing its private half."""
        if not self._uses_arcforge_gateway():
            raise ProClientError(400, "hosted result keys are only available through the Arc Forge gateway")
        session = self._require_session()
        try:
            key = None if rotate else self.hosted_result_keys.active()
            if key is None:
                key = self.hosted_result_keys.create_or_rotate()
        except (HostedResultError, ApiKeyStorageError) as exc:
            raise ProClientError(503, str(exc)) from exc
        self._request(
            "POST",
            f"/api/dictate/devices/{session.device_id}/result-key",
            {
                "recipient_key_id": key.recipient_key_id,
                "recipient_key_version": key.version,
                "public_key": key.public_key,
            },
            auth=session.access_token,
        )
        return key

    def get_decrypted_result(
        self,
        job_id: str,
        *,
        request_id: str,
        correlation_id: str,
        artifact_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch and strictly decrypt a managed result; there is no plaintext fallback."""
        session = self._require_session()
        try:
            pending = self.hosted_result_pending.get(job_id)
        except HostedResultError as exc:
            raise ProClientError(503, str(exc)) from exc
        if pending is not None:
            if (
                pending.get("request_id") != request_id
                or pending.get("correlation_id") != correlation_id
            ):
                raise ProClientError(
                    422, "Hosted result pending journal identity does not match the request"
                )
            envelope = pending.get("envelope")
        else:
            response = self._request(
                "GET",
                self._dictate_job_path(job_id, suffix="/result"),
                auth=session.access_token,
            )
            envelope = response.get("artifact")
            if isinstance(envelope, dict):
                try:
                    self.hosted_result_pending.put(
                        job_id=job_id,
                        request_id=request_id,
                        correlation_id=correlation_id,
                        envelope=envelope,
                    )
                except HostedResultError as exc:
                    raise ProClientError(503, str(exc)) from exc
        if not isinstance(envelope, dict):
            raise ProClientError(
                502, "Arc Forge hosted result response did not contain an encrypted artifact"
            )
        key_id = envelope.get("recipient_key_id")
        key_version = envelope.get("recipient_key_version")
        if not isinstance(key_id, str) or type(key_version) is not int:
            raise ProClientError(502, "Arc Forge hosted result recipient key reference was invalid")
        resolved_artifact_id = str(artifact_id or envelope.get("artifact_id") or "").strip()
        if not resolved_artifact_id:
            raise ProClientError(502, "Arc Forge hosted result artifact id was missing")
        try:
            _metadata, private_key = self.hosted_result_keys.resolve(key_id, key_version)
            payload = decrypt_hosted_result(
                envelope,
                expected=ExpectedHostedResult(
                    account_id=session.account_id,
                    device_id=session.device_id,
                    job_id=job_id,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    artifact_id=resolved_artifact_id,
                ),
                private_key=private_key,
            )
            return {
                "result": payload,
                "artifact_id": resolved_artifact_id,
                "request_id": request_id,
                "correlation_id": correlation_id,
                "acknowledged": bool(pending and pending.get("acknowledged")),
            }
        except HostedResultError as exc:
            raise ProClientError(422, str(exc)) from exc

    def consume_hosted_result(
        self,
        job_id: str,
        *,
        request_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """Decrypt and acknowledge one managed result without any plaintext route fallback."""
        decrypted = self.get_decrypted_result(
            job_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        artifact_id = str(decrypted["artifact_id"])
        digest = hashlib.sha256(
            f"{job_id}|{artifact_id}|{correlation_id}".encode("utf-8")
        ).hexdigest()[:32]
        acknowledgement_id = f"dictate_ack_{digest}"
        if not decrypted.get("acknowledged"):
            self.ack_result(
                job_id,
                artifact_id=artifact_id,
                acknowledgement_id=acknowledgement_id,
                idempotency_key=acknowledgement_id,
                correlation_id=correlation_id,
            )
            try:
                self.hosted_result_pending.mark_acknowledged(job_id, acknowledgement_id)
            except HostedResultError as exc:
                raise ProClientError(503, str(exc)) from exc
        result = decrypted.get("result")
        if not isinstance(result, dict):
            raise ProClientError(502, "Decrypted Dictate result was invalid")
        return result

    def accept_hosted_result(self, job_id: str) -> None:
        """Remove the encrypted replay journal only after application-level acceptance."""
        try:
            self.hosted_result_pending.accept(job_id)
        except HostedResultError as exc:
            raise ProClientError(503, str(exc)) from exc

    def ack_result(
        self,
        job_id: str,
        *,
        artifact_id: str,
        acknowledgement_id: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        session = self._require_session()
        payload = {
            "artifact_id": artifact_id,
            "acknowledgement_id": acknowledgement_id,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
        }
        return self._request(
            "POST",
            self._dictate_job_path(job_id, suffix="/result/ack"),
            payload,
            auth=session.access_token,
            headers={"Idempotency-Key": idempotency_key},
        )

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        session = self._require_session()
        return self._request("POST", self._dictate_job_path(job_id, suffix="/cancel"), {}, auth=session.access_token)

    def push_sync_records(self, records: list[EncryptedSyncRecord]) -> dict[str, Any]:
        session = self._require_session()
        payload = {"device_id": session.device_id, "records": [asdict(record) for record in records]}
        return self._request("POST", self._sync_path("push"), payload, auth=session.access_token)

    def get_sync_changes(self, *, since: int = 0, limit: int = 500) -> dict[str, Any]:
        session = self._require_session()
        path = f"{self._sync_path('changes')}?since={max(0, int(since))}&limit={max(1, int(limit))}"
        return self._request("GET", path, auth=session.access_token)

    def update_sync_cursor(self, *, last_seq: int) -> dict[str, Any]:
        session = self._require_session()
        return self._request(
            "POST",
            self._sync_path("cursor"),
            {"device_id": session.device_id, "last_seq": max(0, int(last_seq))},
            auth=session.access_token,
        )

    def save_key_envelope(
        self,
        *,
        envelope_kind: str,
        envelope: dict[str, Any],
        account_key_commitment: str | None = None,
    ) -> dict[str, Any]:
        session = self._require_session()
        payload: dict[str, Any] = {
            "device_id": session.device_id,
            "envelope_kind": envelope_kind,
            "envelope": envelope,
        }
        if account_key_commitment:
            payload["account_key_commitment"] = account_key_commitment
        return self._request(
            "POST",
            self._sync_path("key-envelopes"),
            payload,
            auth=session.access_token,
        )

    def list_key_envelopes(self, *, envelope_kind: str | None = None) -> dict[str, Any]:
        session = self._require_session()
        path = self._sync_path("key-envelopes")
        if envelope_kind:
            path = f"{path}?kind={urllib.parse.quote(envelope_kind.strip())}"
        return self._request("GET", path, auth=session.access_token)

    def list_devices(self) -> dict[str, Any]:
        session = self._require_session()
        return self._request("GET", self._account_path("devices"), auth=session.access_token)

    def register_device(self, *, device_label: str, device_public_key: str) -> dict[str, Any]:
        session = self._require_session()
        payload = {
            "device_id": session.device_id,
            "device_label": device_label,
            "device_public_key": device_public_key,
        }
        return self._request("POST", self._account_path("devices/register"), payload, auth=session.access_token)

    def revoke_device(self, device_id: str) -> dict[str, Any]:
        session = self._require_session()
        target = device_id.strip()
        if not target:
            raise ProClientError(400, "device_id is required")
        return self._request("POST", self._account_path(f"devices/{target}/revoke"), {}, auth=session.access_token)

    def approve_device(self, device_id: str, *, envelope: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self._require_session()
        target = device_id.strip()
        if not target:
            raise ProClientError(400, "device_id is required")
        payload: dict[str, Any] = {}
        if envelope is not None:
            payload["envelope"] = envelope
        return self._request("POST", self._account_path(f"devices/{target}/approve"), payload, auth=session.access_token)

    def approve_current_device_with_recovery(
        self,
        *,
        recovery_key_envelope: dict[str, Any] | None = None,
        account_key_commitment: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        session = self._require_session()
        envelope = recovery_key_envelope
        if envelope is None:
            listed = self.list_key_envelopes(envelope_kind="recovery").get("envelopes", [])
            for item in listed:
                if isinstance(item, dict) and isinstance(item.get("envelope"), dict):
                    envelope = item["envelope"]
                    break
        if envelope is None:
            raise ProClientError(400, "recovery_key_envelope is required")
        commitment = str(account_key_commitment or "").strip()
        if not commitment:
            raise ProClientError(400, "account_key_commitment is required")
        key = idempotency_key or secrets.token_urlsafe(16)
        return self._request(
            "POST",
            self._account_path("devices/current/approve-with-recovery"),
            {
                "recovery_key_envelope": envelope,
                "account_key_commitment": commitment,
            },
            auth=session.access_token,
            headers={
                "X-Dictate-Device-Id": session.device_id,
                "Idempotency-Key": key,
            },
        )

    def export_cloud_data(self) -> dict[str, Any]:
        session = self._require_session()
        headers = {"X-Dictate-Device-Id": session.device_id} if self._uses_arcforge_gateway() else None
        return self._request(
            "GET",
            self._account_path("account/export"),
            auth=session.access_token,
            headers=headers,
        )

    def delete_cloud_data(self, *, idempotency_key: str | None = None) -> dict[str, Any]:
        session = self._require_session()
        key = idempotency_key or secrets.token_urlsafe(16)
        headers = {
            "Idempotency-Key": key,
        }
        if self._uses_arcforge_gateway():
            headers["X-Dictate-Device-Id"] = session.device_id
        return self._request(
            "DELETE",
            self._account_path("account/cloud-data"),
            {"confirmation": "delete_cloud_data"},
            auth=session.access_token,
            headers=headers,
        )

    def drain_sync_outbox(self, outbox: SyncOutbox) -> dict[str, Any]:
        pending = outbox.pending()
        if not pending:
            return {"pushed": 0, "remaining": 0, "results": []}
        response = self.push_sync_records(pending)
        results = response.get("results")
        if not isinstance(results, list):
            return {"pushed": 0, "remaining": len(pending), "results": []}
        accepted = {
            (str(item.get("record", {}).get("collection")), str(item.get("record", {}).get("record_id")))
            for item in results
            if isinstance(item, dict) and item.get("status") == "accepted" and isinstance(item.get("record"), dict)
        }
        remaining = [
            record
            for record in pending
            if (record.collection, record.record_id) not in accepted
        ]
        outbox.replace_pending(remaining)
        return {"pushed": len(pending) - len(remaining), "remaining": len(remaining), "results": results}

    def _dictate_job_path(self, job_id: str, *, suffix: str = "") -> str:
        if self._uses_arcforge_gateway():
            return f"/api/dictate/jobs/{job_id}{suffix}"
        return f"/v1/meetings/{job_id}{suffix}"

    def _sync_path(self, action: str) -> str:
        if action not in {"push", "changes", "cursor", "key-envelopes"}:
            raise ValueError("unknown sync action")
        if self._uses_arcforge_gateway():
            return f"/api/dictate/sync/{action}"
        return f"/v1/sync/{action}"

    def _account_path(self, path: str) -> str:
        clean = path.strip("/")
        if self._uses_arcforge_gateway():
            return f"/api/dictate/{clean}"
        return f"/v1/{clean}"

    def _register_gateway_device(
        self,
        session: ProSession,
        *,
        device_label: str,
        device_public_key: str,
    ) -> ProSession:
        try:
            response = self._request(
                "POST",
                "/api/dictate/devices/register",
                {
                    "device_id": session.device_id,
                    "device_label": device_label,
                    "device_public_key": device_public_key,
                },
                auth=session.access_token,
            )
        except ProClientError as exc:
            if exc.status in {404, 405, 501}:
                logger.info("Arc Forge Dictate device registration is unavailable on this gateway")
                return session
            raise
        device = response.get("device") if isinstance(response.get("device"), dict) else response
        device_id = str(device.get("device_id") or device.get("deviceId") or "").strip() if isinstance(device, dict) else ""
        account_id = str(device.get("account_id") or device.get("accountId") or "").strip() if isinstance(device, dict) else ""
        if not device_id:
            return session
        return ProSession(
            account_id=account_id or session.account_id,
            device_id=device_id,
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            access_expires_at=session.access_expires_at,
            refresh_expires_at=session.refresh_expires_at,
        )

    def _auth_path(self, name: str) -> str:
        """Auth endpoint path, switched by the same gateway/legacy rule as everything else.

        Deliberately governed by desktop_auth_capabilities()'s 404/405/501 probe rather
        than a hard gateway-only gate: this lets the browser flow be exercised against
        the local /v1 reference server while a real legacy self-host that hasn't shipped
        the endpoint still falls back to email code (probe -> None -> 501).
        """
        if self._uses_arcforge_gateway():
            return f"/api/account/auth/{name}"
        return f"/v1/auth/{name}"

    def _session_from_token_response(self, response: dict[str, Any]) -> ProSession:
        if self._uses_arcforge_gateway():
            return self._session_from_arcforge_auth_response(response)
        return ProSession(
            account_id=str(response["account_id"]),
            device_id=str(response["device_id"]),
            access_token=str(response["access_token"]),
            refresh_token=str(response["refresh_token"]),
            access_expires_at=str(response["access_expires_at"]),
            refresh_expires_at=str(response["refresh_expires_at"]),
        )

    def _uses_arcforge_gateway(self) -> bool:
        mode = os.environ.get("DICTATE_PRO_API_MODE", "").strip().lower()
        if mode in {"arcforge", "gateway", "hosted"}:
            return True
        if mode in {"legacy", "local"}:
            return False
        return not _is_local_api_url(self.base_url)

    def _session_from_arcforge_auth_response(
        self,
        response: dict[str, Any],
        *,
        fallback: ProSession | None = None,
    ) -> ProSession:
        access_token = str(response["access_token"])
        refresh_token = str(response["refresh_token"])
        now = datetime.now(timezone.utc)
        expires_in = int(response.get("expires_in") or 3600)
        account_id = _jwt_subject(access_token) or (fallback.account_id if fallback else "")
        if not account_id:
            raise ProClientError(502, "Arc Forge auth response did not include an account subject")
        return ProSession(
            account_id=account_id,
            device_id=fallback.device_id if fallback else "dictate-desktop",
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=(now + timedelta(seconds=expires_in)).isoformat(),
            refresh_expires_at=(now + timedelta(days=30)).isoformat(),
        )

    def _save_refresh_token(self, token: str) -> bool:
        try:
            save_pro_refresh_token(token)
        except ApiKeyStorageError:
            return False
        except OSError:
            return False
        return True

    def _load_refresh_token(self, raw: dict[str, Any]) -> str | None:
        stored = read_pro_refresh_token()
        if stored:
            return stored
        file_token = raw.get("refresh_token")
        return str(file_token).strip() if file_token else None

    def _clear_refresh_token(self) -> None:
        try:
            clear_pro_refresh_token()
        except (ApiKeyStorageError, OSError):
            pass

    def _require_session(self) -> ProSession:
        session = self.refresh_if_needed()
        if session is None:
            raise ProClientError(401, "not signed in")
        return session

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | bytes | None = None,
        *,
        auth: str | None = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if auth:
            request_headers["Authorization"] = f"Bearer {auth}"
        data: bytes | None
        if isinstance(payload, dict):
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = content_type
        elif isinstance(payload, (bytes, bytearray)):
            data = bytes(payload)
            request_headers["Content-Type"] = content_type
        else:
            data = None
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = detail
            try:
                parsed = json.loads(detail)
                if isinstance(parsed, dict) and parsed.get("error"):
                    message = str(parsed["error"])
            except json.JSONDecodeError:
                pass
            raise ProClientError(exc.code, message) from exc
        except urllib.error.URLError as exc:
            raise ProClientError(503, f"Dictate Pro service unreachable: {exc.reason}") from exc
        if not body:
            return {}
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else {"data": parsed}


class ProClientError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _plaintext_tokens_allowed() -> bool:
    return os.environ.get("DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS", "").strip() == "1"


def _is_local_api_url(base_url: str) -> bool:
    normalized = base_url.strip().lower()
    return (
        normalized.startswith("http://127.0.0.1")
        or normalized.startswith("http://localhost")
        or normalized.startswith("http://[::1]")
    )


def _jwt_subject(token: str) -> str:
    parts = token.split(".")
    if len(parts) < 2:
        return ""
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        parsed = json.loads(decoded.decode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError):
        return ""
    return str(parsed.get("sub") or "").strip()
