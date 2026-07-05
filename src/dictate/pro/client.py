"""Desktop client for the Dictate Pro control plane."""

from __future__ import annotations

import base64
import json
import logging
import os
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
from dictate.sync import EncryptedSyncRecord, SyncOutbox

DEFAULT_API_URL = "https://console.arcforge.au"
SESSION_PATH = user_data_dir() / "pro-session.json"

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.base_url = (base_url or os.environ.get("DICTATE_PRO_API_URL") or DEFAULT_API_URL).rstrip("/")
        self.session_path = session_path
        self._pending_email: str = ""

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

    def complete_sign_in(self, *, challenge_id: str, code: str, device_label: str = "Desktop") -> ProSession:
        session_data = self.load_session()
        payload = {
            "challenge_id": challenge_id,
            "code": code,
            "device_label": device_label,
        }
        if session_data:
            payload["device_id"] = session_data.device_id
        if self._uses_arcforge_gateway():
            email = (self._pending_email or challenge_id).strip().lower()
            response = self._request("POST", "/api/account/auth/verify-code", {"email": email, "code": code})
            session = self._session_from_arcforge_auth_response(response)
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
            return {"signedIn": False, "entitlements": None, "usage": None, "account": None, "commerce": None}
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
        except ProClientError:
            self.clear_session()
            return {"signedIn": False, "entitlements": None, "usage": None, "account": None, "commerce": None}
        return {
            "signedIn": True,
            "account": account,
            "commerce": commerce,
            "entitlements": entitlements,
            "usage": usage,
            "apiUrl": self.base_url,
        }

    def create_meeting(
        self,
        *,
        language: str | None = None,
        audio_duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        session = self._require_session()
        if self._uses_arcforge_gateway():
            if audio_duration_seconds is None or audio_duration_seconds <= 0:
                raise ProClientError(400, "audio_duration_seconds is required for hosted Dictate jobs")
            payload: dict[str, Any] = {
                "device_id": session.device_id,
                "audio_duration_seconds": audio_duration_seconds,
            }
            if language:
                payload["language"] = language
            return self._request("POST", "/api/dictate/jobs", payload, auth=session.access_token)
        return self._request(
            "POST",
            "/v1/meetings",
            {"language": language} if language else {},
            auth=session.access_token,
        )

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

    def push_sync_records(self, records: list[EncryptedSyncRecord]) -> dict[str, Any]:
        session = self._require_session()
        payload = {"device_id": session.device_id, "records": [asdict(record) for record in records]}
        return self._request("POST", self._sync_path("push"), payload, auth=session.access_token)

    def get_sync_changes(self, *, since: int = 0, limit: int = 500) -> dict[str, Any]:
        session = self._require_session()
        path = f"{self._sync_path('changes')}?since={max(0, int(since))}&limit={max(1, int(limit))}"
        return self._request("GET", path, auth=session.access_token)

    def save_key_envelope(self, *, envelope_kind: str, envelope: dict[str, Any]) -> dict[str, Any]:
        session = self._require_session()
        return self._request(
            "POST",
            self._sync_path("key-envelopes"),
            {"device_id": session.device_id, "envelope_kind": envelope_kind, "envelope": envelope},
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

    def revoke_device(self, device_id: str) -> dict[str, Any]:
        session = self._require_session()
        target = device_id.strip()
        if not target:
            raise ProClientError(400, "device_id is required")
        return self._request("POST", self._account_path(f"devices/{target}/revoke"), {}, auth=session.access_token)

    def export_cloud_data(self) -> dict[str, Any]:
        session = self._require_session()
        return self._request("GET", self._account_path("account/export"), auth=session.access_token)

    def delete_cloud_data(self) -> dict[str, Any]:
        session = self._require_session()
        return self._request("DELETE", self._account_path("account/cloud-data"), auth=session.access_token)

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
        if action not in {"push", "changes", "key-envelopes"}:
            raise ValueError("unknown sync action")
        if self._uses_arcforge_gateway():
            return f"/api/dictate/sync/{action}"
        return f"/v1/sync/{action}"

    def _account_path(self, path: str) -> str:
        clean = path.strip("/")
        if self._uses_arcforge_gateway():
            return f"/api/dictate/{clean}"
        return f"/v1/{clean}"

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
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {auth}"
        data: bytes | None
        if isinstance(payload, dict):
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = content_type
        elif isinstance(payload, (bytes, bytearray)):
            data = bytes(payload)
            headers["Content-Type"] = content_type
        else:
            data = None
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
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
