"""Device-local key custody and strict decryption for hosted Dictate results."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from dictate.api_keys import (
    clear_hosted_result_private_key,
    read_hosted_result_private_key,
    save_hosted_result_private_key,
)
from dictate.platform_paths import user_data_dir

CONTRACT_VERSION = "dictate_litellm_worker_v1"
CRYPTO_FORMAT = "dictate_result_x25519_hkdf_aes256gcm_v1"
ALGORITHM = "X25519+AES-256-GCM"
KDF_NAME = "HKDF-SHA256"
HOSTED_RESULT_KEYS_PATH = user_data_dir() / "hosted-result-keys.json"
HOSTED_RESULT_PENDING_PATH = user_data_dir() / "hosted-result-pending.json"

KeyStatus = Literal["active", "decrypt_only", "revoked"]

_ENVELOPE_FIELDS = {
    "contract_version",
    "crypto_format",
    "crypto_version",
    "algorithm",
    "kdf",
    "kdf_salt",
    "kdf_info",
    "ephemeral_public_key",
    "nonce",
    "aad",
    "ciphertext",
    "integrity_binding",
    "recipient_key_id",
    "recipient_key_version",
    "job_id",
    "request_id",
    "correlation_id",
    "artifact_id",
    "expires_at",
    "ack_state",
}
_AAD_FIELDS = {
    "contract_version",
    "crypto_format",
    "account_id",
    "device_id",
    "job_id",
    "request_id",
    "correlation_id",
    "artifact_id",
    "recipient_key_id",
    "recipient_key_version",
    "ephemeral_public_key",
}


class HostedResultError(ValueError):
    """Raised when a hosted-result key or envelope violates the frozen contract."""


@dataclass(frozen=True, slots=True)
class HostedResultKey:
    recipient_key_id: str
    version: int
    public_key: str
    status: KeyStatus
    created_at: str


@dataclass(frozen=True, slots=True)
class ExpectedHostedResult:
    account_id: str
    device_id: str
    job_id: str
    request_id: str
    correlation_id: str
    artifact_id: str


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: object, *, field: str, length: int | None = None) -> bytes:
    if not isinstance(value, str) or not value or "=" in value:
        raise HostedResultError(f"{field} must be canonical unpadded base64url")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HostedResultError(f"{field} must be canonical unpadded base64url") from exc
    if _b64url_encode(decoded) != value:
        raise HostedResultError(f"{field} must be canonical unpadded base64url")
    if length is not None and len(decoded) != length:
        raise HostedResultError(f"{field} must decode to {length} bytes")
    return decoded


def _canonical_json(value: dict[str, str]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_hosted_result_key(*, recipient_key_id: str | None = None, version: int = 1) -> tuple[HostedResultKey, str]:
    """Generate one X25519 keypair; return public metadata and encoded private material."""
    key_id = (recipient_key_id or f"drk_{secrets.token_urlsafe(18)}").strip()
    if not key_id or version < 1:
        raise HostedResultError("recipient key id and positive version are required")
    private = X25519PrivateKey.generate()
    private_bytes = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_bytes = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return (
        HostedResultKey(
            recipient_key_id=key_id,
            version=version,
            public_key=_b64url_encode(public_bytes),
            status="active",
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
        _b64url_encode(private_bytes),
    )


class HostedResultKeyStore:
    """Non-secret lifecycle metadata plus OS-backed private key material."""

    def __init__(
        self,
        *,
        path: Path = HOSTED_RESULT_KEYS_PATH,
        save_secret: Callable[[str, int, str], None] = save_hosted_result_private_key,
        read_secret: Callable[[str, int], str | None] = read_hosted_result_private_key,
        clear_secret: Callable[[str, int], None] = clear_hosted_result_private_key,
        purge_pending: Callable[[str, int], None] | None = None,
    ) -> None:
        self.path = path
        self._save_secret = save_secret
        self._read_secret = read_secret
        self._clear_secret = clear_secret
        self._purge_pending = purge_pending

    def list(self) -> list[HostedResultKey]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HostedResultError("hosted result key metadata is unreadable") from exc
        if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("keys"), list):
            raise HostedResultError("hosted result key metadata has an unsupported format")
        keys: list[HostedResultKey] = []
        try:
            for item in raw["keys"]:
                key = HostedResultKey(**item)
                if key.version < 1 or key.status not in {"active", "decrypt_only", "revoked"}:
                    raise TypeError
                _b64url_decode(key.public_key, field="public_key", length=32)
                keys.append(key)
        except (TypeError, HostedResultError) as exc:
            raise HostedResultError("hosted result key metadata is invalid") from exc
        return keys

    def active(self) -> HostedResultKey | None:
        active = [key for key in self.list() if key.status == "active"]
        if len(active) > 1:
            raise HostedResultError("multiple active hosted result keys are not allowed")
        return active[0] if active else None

    def create_or_rotate(self) -> HostedResultKey:
        keys = self.list()
        active = [key for key in keys if key.status == "active"]
        if len(active) > 1:
            raise HostedResultError("multiple active hosted result keys are not allowed")
        next_version = max((key.version for key in keys), default=0) + 1
        new_key, private_key = generate_hosted_result_key(version=next_version)
        self._save_secret(new_key.recipient_key_id, new_key.version, private_key)
        replaced = [
            HostedResultKey(**{**asdict(key), "status": "decrypt_only"}) if key.status == "active" else key
            for key in keys
        ]
        try:
            self._write([*replaced, new_key])
        except Exception:
            self._clear_secret(new_key.recipient_key_id, new_key.version)
            raise
        return new_key

    def resolve(self, recipient_key_id: str, version: int) -> tuple[HostedResultKey, str]:
        matches = [
            key for key in self.list() if key.recipient_key_id == recipient_key_id and key.version == version
        ]
        if len(matches) != 1:
            raise HostedResultError("hosted result recipient key is unknown")
        key = matches[0]
        if key.status == "revoked":
            raise HostedResultError("hosted result recipient key is revoked")
        private_key = self._read_secret(key.recipient_key_id, key.version)
        if not private_key:
            raise HostedResultError("hosted result private key is unavailable")
        return key, private_key

    def revoke(self, recipient_key_id: str, version: int) -> None:
        keys = self.list()
        found = False
        updated: list[HostedResultKey] = []
        for key in keys:
            if key.recipient_key_id == recipient_key_id and key.version == version:
                found = True
                updated.append(HostedResultKey(**{**asdict(key), "status": "revoked"}))
            else:
                updated.append(key)
        if not found:
            raise HostedResultError("hosted result recipient key is unknown")
        self._write(updated)
        self._clear_secret(recipient_key_id, version)
        if self._purge_pending is not None:
            self._purge_pending(recipient_key_id, version)

    def _write(self, keys: list[HostedResultKey]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps({"version": 1, "keys": [asdict(key) for key in keys]}, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.chmod(0o600)
            temporary.replace(self.path)
            self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


class HostedResultPendingStore:
    """Durable encrypted-artifact journal used to replay ambiguous acknowledgements."""

    def __init__(self, *, path: Path = HOSTED_RESULT_PENDING_PATH) -> None:
        self.path = path

    def get(self, job_id: str) -> dict[str, Any] | None:
        records = self._load()
        if self._purge_expired_records(records, now=datetime.now(timezone.utc)):
            self._write(records)
        return records.get(job_id)

    def put(
        self,
        *,
        job_id: str,
        request_id: str,
        correlation_id: str,
        envelope: dict[str, Any],
    ) -> None:
        records = self._load()
        self._purge_expired_records(records, now=datetime.now(timezone.utc))
        candidate = {
            "job_id": job_id,
            "request_id": request_id,
            "correlation_id": correlation_id,
            "envelope": envelope,
            "acknowledged": False,
            "acknowledgement_id": "",
            "acknowledged_at": "",
        }
        existing = records.get(job_id)
        if existing is not None and existing != candidate:
            raise HostedResultError(
                "hosted result pending journal conflicts with the fetched artifact"
            )
        records[job_id] = candidate
        self._write(records)

    def mark_acknowledged(self, job_id: str, acknowledgement_id: str) -> None:
        records = self._load()
        record = records.get(job_id)
        if record is None:
            raise HostedResultError("hosted result pending journal entry is missing")
        record["acknowledged"] = True
        record["acknowledgement_id"] = acknowledgement_id
        record["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
        self._write(records)

    def accept(self, job_id: str) -> None:
        records = self._load()
        if job_id in records:
            records.pop(job_id)
            self._write(records)

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Remove ciphertext whose authoritative artifact expiry has elapsed."""
        records = self._load()
        removed = self._purge_expired_records(records, now=now or datetime.now(timezone.utc))
        if removed:
            self._write(records)
        return removed

    def purge_recipient(self, recipient_key_id: str, version: int) -> None:
        """Remove ciphertext that can no longer be decrypted after key revocation."""
        records = self._load()
        retained = {
            job_id: record
            for job_id, record in records.items()
            if not self._matches_recipient(record, recipient_key_id, version)
        }
        if len(retained) != len(records):
            self._write(retained)

    @staticmethod
    def _matches_recipient(record: dict[str, Any], recipient_key_id: str, version: int) -> bool:
        envelope = record.get("envelope")
        return bool(
            isinstance(envelope, dict)
            and envelope.get("recipient_key_id") == recipient_key_id
            and envelope.get("recipient_key_version") == version
        )

    @staticmethod
    def _purge_expired_records(records: dict[str, dict[str, Any]], *, now: datetime) -> int:
        if now.tzinfo is None:
            raise HostedResultError("hosted result pending expiry time must be timezone-aware")
        expired: list[str] = []
        for job_id, record in records.items():
            envelope = record.get("envelope")
            expires_at = envelope.get("expires_at") if isinstance(envelope, dict) else None
            if not isinstance(expires_at, str):
                continue
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if expiry.tzinfo is not None and expiry <= now:
                expired.append(job_id)
        for job_id in expired:
            records.pop(job_id)
        return len(expired)

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HostedResultError("hosted result pending journal is unreadable") from exc
        records = raw.get("records") if isinstance(raw, dict) and raw.get("version") == 1 else None
        if not isinstance(records, dict) or not all(
            isinstance(key, str) and isinstance(value, dict) for key, value in records.items()
        ):
            raise HostedResultError("hosted result pending journal has an unsupported format")
        return records

    def _write(self, records: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps({"version": 1, "records": records}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.chmod(0o600)
            temporary.replace(self.path)
            self.path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


def decrypt_hosted_result(
    envelope: dict[str, Any],
    *,
    expected: ExpectedHostedResult,
    private_key: str,
) -> dict[str, Any]:
    """Validate the complete frozen envelope and decrypt its JSON object payload."""
    if set(envelope) != _ENVELOPE_FIELDS:
        raise HostedResultError("hosted result envelope fields do not match the frozen contract")
    if (
        envelope.get("contract_version") != CONTRACT_VERSION
        or envelope.get("crypto_format") != CRYPTO_FORMAT
    ):
        raise HostedResultError("hosted result contract version is unsupported")
    if (
        envelope.get("crypto_version") != 1
        or envelope.get("algorithm") != ALGORITHM
        or envelope.get("kdf") != KDF_NAME
    ):
        raise HostedResultError("hosted result cryptography parameters are unsupported")
    expires_at = envelope.get("expires_at")
    if envelope.get("ack_state") != "pending" or not isinstance(expires_at, str):
        raise HostedResultError("hosted result lifecycle state is invalid")
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HostedResultError("hosted result expiry is invalid") from exc
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
        raise HostedResultError("hosted result artifact has expired")
    recipient_key_id = envelope.get("recipient_key_id")
    recipient_key_version = envelope.get("recipient_key_version")
    if (
        not isinstance(recipient_key_id, str)
        or not recipient_key_id
        or type(recipient_key_version) is not int
    ):
        raise HostedResultError("hosted result recipient key reference is invalid")

    aad = envelope.get("aad")
    if (
        not isinstance(aad, dict)
        or set(aad) != _AAD_FIELDS
        or not all(isinstance(value, str) for value in aad.values())
    ):
        raise HostedResultError("hosted result AAD does not match the frozen contract")
    expected_values = {
        "contract_version": CONTRACT_VERSION,
        "crypto_format": CRYPTO_FORMAT,
        "account_id": expected.account_id,
        "device_id": expected.device_id,
        "job_id": expected.job_id,
        "request_id": expected.request_id,
        "correlation_id": expected.correlation_id,
        "artifact_id": expected.artifact_id,
        "recipient_key_id": recipient_key_id,
        "recipient_key_version": str(recipient_key_version),
        "ephemeral_public_key": envelope["ephemeral_public_key"],
    }
    if aad != expected_values:
        raise HostedResultError("hosted result identity binding does not match the requested result")
    for field in ("job_id", "request_id", "correlation_id", "artifact_id", "recipient_key_id"):
        if envelope[field] != aad[field]:
            raise HostedResultError(f"hosted result outer {field} does not match its AAD")
    if str(envelope["recipient_key_version"]) != aad["recipient_key_version"]:
        raise HostedResultError("hosted result outer recipient key version does not match its AAD")

    aad_bytes = _canonical_json(aad)
    binding = _b64url_decode(envelope["integrity_binding"], field="integrity_binding", length=32)
    if not hmac.compare_digest(binding, hashlib.sha256(aad_bytes).digest()):
        raise HostedResultError("hosted result AAD integrity binding is invalid")
    expected_info = (
        f"dictate-result|{CONTRACT_VERSION}|{CRYPTO_FORMAT}|{expected.artifact_id}|"
        f"{recipient_key_id}|{recipient_key_version}"
    )
    if envelope.get("kdf_info") != expected_info:
        raise HostedResultError("hosted result KDF context is invalid")

    private_bytes = _b64url_decode(private_key, field="private_key", length=32)
    ephemeral_bytes = _b64url_decode(envelope["ephemeral_public_key"], field="ephemeral_public_key", length=32)
    salt = _b64url_decode(envelope["kdf_salt"], field="kdf_salt", length=32)
    nonce = _b64url_decode(envelope["nonce"], field="nonce", length=12)
    ciphertext = _b64url_decode(envelope["ciphertext"], field="ciphertext")
    try:
        shared = X25519PrivateKey.from_private_bytes(private_bytes).exchange(
            X25519PublicKey.from_public_bytes(ephemeral_bytes)
        )
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            info=expected_info.encode("utf-8"),
        ).derive(shared)
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad_bytes)
    except Exception as exc:  # cryptography deliberately exposes several backend-specific failures
        raise HostedResultError("hosted result authentication or decryption failed") from exc
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostedResultError("hosted result plaintext is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise HostedResultError("hosted result plaintext must be a JSON object")
    return payload
