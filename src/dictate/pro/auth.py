"""Authentication helpers for the Dictate Pro control plane."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from dictate.pro.email_delivery import AuthDeliveryError, send_auth_code
from dictate.pro.store import ProStore, iso, utcnow


ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
CHALLENGE_TTL = timedelta(minutes=10)
MAX_CHALLENGE_ATTEMPTS = 5
AUTHORIZATION_CODE_TTL = timedelta(seconds=120)
# RFC 7636 §4.1: code_verifier = 43*128unreserved; unreserved = ALPHA / DIGIT / "-" / "." / "_" / "~"
_CODE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
DEVICE_CODE_TTL = timedelta(seconds=900)
DEVICE_CODE_INTERVAL = 5
# RFC 8628 §6.1 recommends a confusion-free alphabet for the user-entered code (no 0/O/1/I etc).
_USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"


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


def _generate_auth_code() -> str:
    return secrets.token_urlsafe(32)


def _generate_device_code() -> str:
    return secrets.token_urlsafe(32)


def _generate_user_code() -> str:
    chars = [secrets.choice(_USER_CODE_ALPHABET) for _ in range(8)]
    return f"{''.join(chars[:4])}-{''.join(chars[4:])}"


def _b64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _compare_str(a: str, b: str) -> bool:
    """hmac.compare_digest, tolerant of non-ASCII input.

    hmac.compare_digest(str, str) requires both operands to be ASCII-only and raises
    TypeError otherwise -- which would surface as an uncaught 500 instead of the intended
    400 invalid_grant for a malicious/malformed non-ASCII client_id or redirect_uri.
    """
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


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

    def create_authorization_code(
        self,
        *,
        account_id: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        scope: str = "dictate",
        device_label: str = "Desktop",
    ) -> str:
        if code_challenge_method != "S256":
            raise ValueError("invalid_request")
        if not code_challenge:
            raise ValueError("invalid_request")
        code = _generate_auth_code()
        expires_at = utcnow() + AUTHORIZATION_CODE_TTL
        self._store.save_auth_code(
            code_hash=_hash_code(code),
            account_id=account_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            device_label=device_label,
            expires_at=iso(expires_at),
        )
        return code

    def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        client_id: str,
        device_id: str | None = None,
        device_public_key: str | None = None,
    ) -> AuthSession:
        code_hash = _hash_code(code)
        row = self._store.get_auth_code(code_hash)
        if row is None:
            raise ValueError("invalid_grant")
        # Consume immediately, before any validation. Per the OAuth Security BCP (RFC 9700),
        # an authorization code is single-use regardless of whether the exchange that
        # consumes it succeeds -- a code that fails PKCE/client/redirect validation must not
        # remain valid for a second attempt. consume_auth_code() also catches replay of an
        # already-consumed code (returns False), which is what maps that case to invalid_grant.
        if not self._store.consume_auth_code(code_hash):
            raise ValueError("invalid_grant")
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if utcnow() > expires_at:
            raise ValueError("invalid_grant")
        if not _compare_str(row["client_id"], client_id):
            raise ValueError("invalid_grant")
        if not _compare_str(row["redirect_uri"], redirect_uri):
            raise ValueError("invalid_grant")
        if not _CODE_VERIFIER_RE.match(code_verifier):
            # RFC 7636 §4.1: code_verifier must be 43-128 chars of [A-Za-z0-9-._~]. No
            # exploit today (the challenge only ever binds the requester's own verifier),
            # but the reference contract should enforce the spec before arc-forge-console
            # copies it.
            raise ValueError("invalid_grant")
        expected_challenge = _b64url_sha256(code_verifier)
        if not _compare_str(expected_challenge, row["code_challenge"]):
            raise ValueError("invalid_grant")
        # Mirror complete_sign_in: register (or update) the device and issue a session the
        # same way the email-code path does, so the returned session isn't dead on arrival --
        # resolve_access_token()/refresh_session() both gate on device_is_known().
        try:
            device = self._store.register_device(
                account_id=row["account_id"],
                device_id=device_id,
                label=row.get("device_label") or "Desktop",
                public_key=device_public_key,
            )
        except ValueError as exc:
            # device_id supplied by the caller belongs to a different account
            # (store.register_device rejects the cross-account write). Surface this as
            # the standard OAuth invalid_grant, same as every other rejection here.
            raise ValueError("invalid_grant") from exc
        if not self._store.device_is_known(account_id=row["account_id"], device_id=device):
            raise ValueError("invalid_grant")
        return self._issue_session(row["account_id"], device)

    def create_device_code(
        self,
        *,
        client_id: str,
        scope: str = "dictate",
        device_label: str = "Desktop",
    ) -> dict[str, Any]:
        device_code = _generate_device_code()
        user_code = _generate_user_code()
        expires_at = utcnow() + DEVICE_CODE_TTL
        self._store.save_device_code(
            device_code_hash=_hash_code(device_code),
            user_code=user_code,
            client_id=client_id,
            scope=scope,
            device_label=device_label,
            expires_at=iso(expires_at),
            interval=DEVICE_CODE_INTERVAL,
        )
        return {
            "device_code": device_code,
            "user_code": user_code,
            "expires_in": int(DEVICE_CODE_TTL.total_seconds()),
            "interval": DEVICE_CODE_INTERVAL,
        }

    def approve_device_code(self, *, user_code: str, account_id: str) -> bool:
        """Dev/test-only approval hook (no portal on the reference server this episode)."""
        return self._store.approve_device_code(user_code=user_code, account_id=account_id)

    def deny_device_code(self, *, user_code: str) -> bool:
        """Dev/test-only denial hook, mirroring approve_device_code."""
        return self._store.deny_device_code(user_code=user_code)

    def poll_device_code(
        self,
        *,
        device_code: str,
        client_id: str,
        device_id: str | None = None,
        device_public_key: str | None = None,
    ) -> AuthSession:
        """RFC 8628 §3.5 polling. Raises ValueError with one of:
        "authorization_pending", "slow_down", "expired_token", "access_denied", "invalid_grant".
        """
        device_code_hash = _hash_code(device_code)
        row = self._store.get_device_code(device_code_hash)
        if row is None:
            raise ValueError("invalid_grant")
        if not _compare_str(row["client_id"], client_id):
            raise ValueError("invalid_grant")
        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if utcnow() > expires_at:
            raise ValueError("expired_token")
        now = utcnow()
        last_polled_raw = row.get("last_polled_at")
        interval = int(row.get("interval") or DEVICE_CODE_INTERVAL)
        if last_polled_raw:
            last_polled = datetime.fromisoformat(last_polled_raw)
            if last_polled.tzinfo is None:
                last_polled = last_polled.replace(tzinfo=timezone.utc)
            if (now - last_polled).total_seconds() < interval:
                # Client polled faster than the last-assigned interval: per RFC 8628 §3.5,
                # tell it to slow down and increase the interval by 5s for next time.
                self._store.touch_device_code_poll(device_code_hash, last_polled_at=iso(now), interval=interval + 5)
                raise ValueError("slow_down")
        self._store.touch_device_code_poll(device_code_hash, last_polled_at=iso(now), interval=interval)
        status = row.get("status")
        if status == "denied":
            raise ValueError("access_denied")
        if status == "pending":
            raise ValueError("authorization_pending")
        if status != "approved":
            raise ValueError("invalid_grant")
        if not self._store.consume_device_code(device_code_hash):
            raise ValueError("invalid_grant")
        account_id = row.get("account_id")
        if not account_id:
            raise ValueError("invalid_grant")
        # Mirror exchange_authorization_code / complete_sign_in: register the device and
        # issue a session the same way every other grant does, so the session isn't dead
        # on arrival -- resolve_access_token()/refresh_session() both gate on device_is_known().
        try:
            device = self._store.register_device(
                account_id=account_id,
                device_id=device_id,
                label=row.get("device_label") or "Desktop",
                public_key=device_public_key,
            )
        except ValueError as exc:
            raise ValueError("invalid_grant") from exc
        if not self._store.device_is_known(account_id=account_id, device_id=device):
            raise ValueError("invalid_grant")
        return self._issue_session(account_id, device)

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
