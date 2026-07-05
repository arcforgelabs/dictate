"""Authentication helpers for the Dictate Pro control plane."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dictate.pro.email_delivery import AuthDeliveryError, send_auth_code
from dictate.pro.store import ProStore, iso, utcnow


ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
CHALLENGE_TTL = timedelta(minutes=10)
MAX_CHALLENGE_ATTEMPTS = 5


@dataclass(slots=True)
class AuthSession:
    account_id: str
    device_id: str
    access_token: str
    refresh_token: str
    access_expires_at: str
    refresh_expires_at: str


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


class ProAuth:
    def __init__(self, store: ProStore, *, dev_expose_code: bool | None = None) -> None:
        self._store = store
        self._dev_expose_code = (
            dev_expose_code
            if dev_expose_code is not None
            else os.environ.get("DICTATE_PRO_DEV_AUTH", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )

    def start_sign_in(self, email: str) -> dict[str, str]:
        account = self._store.get_or_create_account(email)
        challenge_id = f"ch_{secrets.token_urlsafe(16)}"
        code = _generate_code()
        expires_at = (utcnow() + CHALLENGE_TTL).replace(microsecond=0).isoformat()
        self._store.save_auth_challenge(
            challenge_id=challenge_id,
            email=account.email,
            code_hash=_hash_code(code),
            expires_at=expires_at,
            attempts_remaining=MAX_CHALLENGE_ATTEMPTS,
        )
        payload = {
            "challenge_id": challenge_id,
            "expires_at": expires_at,
            "account_id": account.account_id,
        }
        if self._dev_expose_code:
            payload["dev_code"] = code
            return payload
        send_auth_code(to_address=account.email, code=code)
        return payload

    def complete_sign_in(
        self,
        *,
        challenge_id: str,
        code: str,
        device_id: str | None = None,
        device_label: str = "Desktop",
        device_public_key: str | None = None,
    ) -> AuthSession:
        challenge = self._store.get_auth_challenge(challenge_id)
        if challenge is None:
            raise ValueError("invalid challenge")
        expires_at = datetime.fromisoformat(challenge["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if utcnow() > expires_at:
            self._store.delete_auth_challenge(challenge_id)
            raise ValueError("challenge expired")
        attempts = int(challenge["attempts_remaining"])
        if attempts <= 0:
            self._store.delete_auth_challenge(challenge_id)
            raise ValueError("challenge locked")
        if not hmac.compare_digest(_hash_code(code.strip()), challenge["code_hash"]):
            self._store.save_auth_challenge(
                challenge_id=challenge_id,
                email=challenge["email"],
                code_hash=challenge["code_hash"],
                expires_at=challenge["expires_at"],
                attempts_remaining=attempts - 1,
            )
            raise ValueError("invalid code")
        account = self._store.get_account_by_email(challenge["email"])
        if account is None:
            raise ValueError("account not found")
        device = self._store.register_device(
            account_id=account.account_id,
            device_id=device_id,
            label=device_label,
            public_key=device_public_key,
        )
        if not self._store.device_is_known(account_id=account.account_id, device_id=device):
            raise ValueError("device revoked")
        self._store.delete_auth_challenge(challenge_id)
        return self._issue_session(account.account_id, device)

    def refresh_session(self, refresh_token: str) -> AuthSession:
        row = self._store.get_auth_token(_hash_token(refresh_token))
        if row is None or row.get("revoked_at"):
            raise ValueError("invalid refresh token")
        if row.get("token_type") != "refresh":
            raise ValueError("invalid refresh token")
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if utcnow() > expires_at:
            raise ValueError("refresh token expired")
        device_id = row.get("device_id") or ""
        if device_id and not self._store.device_is_known(account_id=row["account_id"], device_id=device_id):
            raise ValueError("device revoked")
        self._store.revoke_auth_token(_hash_token(refresh_token))
        return self._issue_session(row["account_id"], device_id)

    def resolve_access_token(self, access_token: str) -> tuple[str, str | None]:
        row = self._store.get_auth_token(_hash_token(access_token))
        if row is None or row.get("revoked_at"):
            raise ValueError("unauthorized")
        if row.get("token_type") != "access":
            raise ValueError("unauthorized")
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if utcnow() > expires_at:
            raise ValueError("access token expired")
        device_id = row.get("device_id")
        if device_id and not self._store.device_is_known(account_id=row["account_id"], device_id=device_id):
            raise ValueError("device revoked")
        if device_id:
            self._store.touch_device(device_id)
        return row["account_id"], device_id

    def revoke_access_token(self, access_token: str) -> None:
        self._store.revoke_auth_token(_hash_token(access_token))

    def _issue_session(self, account_id: str, device_id: str) -> AuthSession:
        access_token = _generate_token()
        refresh_token = _generate_token()
        access_expires = utcnow() + ACCESS_TOKEN_TTL
        refresh_expires = utcnow() + REFRESH_TOKEN_TTL
        self._store.save_auth_token(
            token_hash=_hash_token(access_token),
            account_id=account_id,
            device_id=device_id,
            token_type="access",
            expires_at=iso(access_expires),
        )
        self._store.save_auth_token(
            token_hash=_hash_token(refresh_token),
            account_id=account_id,
            device_id=device_id,
            token_type="refresh",
            expires_at=iso(refresh_expires),
        )
        return AuthSession(
            account_id=account_id,
            device_id=device_id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=iso(access_expires),
            refresh_expires_at=iso(refresh_expires),
        )
