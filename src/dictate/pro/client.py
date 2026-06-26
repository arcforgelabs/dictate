"""Desktop client for the Dictate Pro control plane."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dictate.api_keys import (
    ApiKeyStorageError,
    clear_pro_refresh_token,
    read_pro_refresh_token,
    save_pro_refresh_token,
)
from dictate.platform_paths import user_data_dir

DEFAULT_API_URL = "http://127.0.0.1:18765"
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
        else:
            logger.warning(
                "OS secret store unavailable; persisting refresh token in plaintext %s",
                self.session_path,
            )
            payload["refresh_token"] = session.refresh_token
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
        if datetime.now(timezone.utc) < expires_at - __import__("datetime").timedelta(minutes=1):
            return session
        response = self._request(
            "POST",
            "/v1/auth/refresh",
            {"refresh_token": session.refresh_token},
        )
        refreshed = ProSession(
            account_id=str(response["account_id"]),
            device_id=str(response["device_id"]),
            access_token=str(response["access_token"]),
            refresh_token=str(response["refresh_token"]),
            access_expires_at=str(response["access_expires_at"]),
            refresh_expires_at=str(response["refresh_expires_at"]),
        )
        self.save_session(refreshed)
        return refreshed

    def get_state(self) -> dict[str, Any]:
        session = self.refresh_if_needed()
        if session is None:
            return {"signedIn": False, "entitlements": None, "usage": None, "account": None}
        try:
            account = self._request("GET", "/v1/me", auth=session.access_token)
            entitlements = self._request("GET", "/v1/entitlements", auth=session.access_token)
            usage = self._request("GET", "/v1/usage/current", auth=session.access_token)
        except ProClientError:
            self.clear_session()
            return {"signedIn": False, "entitlements": None, "usage": None, "account": None}
        return {
            "signedIn": True,
            "account": account,
            "entitlements": entitlements,
            "usage": usage,
            "apiUrl": self.base_url,
        }

    def create_meeting(self, *, language: str | None = None) -> dict[str, Any]:
        session = self._require_session()
        return self._request(
            "POST",
            "/v1/meetings",
            {"language": language} if language else {},
            auth=session.access_token,
        )

    def upload_meeting_audio(self, job_id: str, audio_path: Path) -> dict[str, Any]:
        session = self._require_session()
        data = audio_path.read_bytes()
        return self._request(
            "POST",
            f"/v1/meetings/{job_id}/audio",
            body=data,
            content_type="audio/wav",
            auth=session.access_token,
        )

    def get_meeting(self, job_id: str) -> dict[str, Any]:
        session = self._require_session()
        return self._request("GET", f"/v1/meetings/{job_id}", auth=session.access_token)

    def get_transcript(self, job_id: str) -> dict[str, Any]:
        session = self._require_session()
        return self._request("GET", f"/v1/meetings/{job_id}/transcript", auth=session.access_token)

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
