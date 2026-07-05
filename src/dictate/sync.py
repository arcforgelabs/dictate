"""Encrypted local foundations for Dictate Pro cloud sync."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from dictate.platform_paths import user_data_dir
from dictate import api_keys as api_keys_mod

SYNC_DEVICE_PATH = user_data_dir() / "sync-device.json"
SYNC_OUTBOX_PATH = user_data_dir() / "sync-outbox.jsonl"
SYNC_STATE_PATH = user_data_dir() / "sync-state.json"
RECOVERY_KEY_PREFIX = "dictate-rk-"
RECOVERY_KEY_ITERATIONS = 390_000

SyncCollection = Literal["history", "note", "segment", "settings", "lexicon"]
SYNC_SETTINGS_CONTENT_TYPE = "application/vnd.dictate.setting+json;v=1"
SYNC_LEXICON_CONTENT_TYPE = "application/vnd.dictate.lexicon+json;v=1"
SYNCED_PREF_KEYS = frozenset({"theme", "sound", "ambient", "activation", "outputFormat"})


@dataclass(frozen=True, slots=True)
class SyncDevice:
    device_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SyncState:
    enabled: bool
    account_id: str
    device_id: str
    enabled_at: str | None = None
    last_seq: int = 0


@dataclass(frozen=True, slots=True)
class PlainSyncRecord:
    collection: SyncCollection
    record_id: str
    rev: int
    updated_at: str
    device_id: str
    deleted: bool
    content_type: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EncryptedSyncRecord:
    collection: SyncCollection
    record_id: str
    rev: int
    updated_at: str
    device_id: str
    deleted: bool
    content_type: str
    ciphertext: str
    nonce: str
    aad_hash: str
    payload_bytes: int


@dataclass(frozen=True, slots=True)
class RecoveryKeyEnvelope:
    version: int
    kdf: str
    iterations: int
    salt: str
    nonce: str
    ciphertext: str
    aad_hash: str


@dataclass(frozen=True, slots=True)
class DeviceKeyPair:
    private_key: str
    public_key: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_or_create_device(path: Path = SYNC_DEVICE_PATH) -> SyncDevice:
    """Return a stable per-install device id, creating one if needed."""
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict):
            device_id = str(raw.get("device_id") or "").strip()
            created_at = str(raw.get("created_at") or "").strip()
            if device_id and created_at:
                return SyncDevice(device_id=device_id, created_at=created_at)

    device = SyncDevice(device_id=f"device_{uuid.uuid4().hex}", created_at=utc_now_iso())
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, asdict(device))
    return device


def save_sync_device(device_id: str, *, path: Path = SYNC_DEVICE_PATH) -> SyncDevice:
    device = SyncDevice(device_id=device_id.strip(), created_at=utc_now_iso())
    if not device.device_id:
        raise ValueError("device_id is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, asdict(device))
    return device


def generate_account_key() -> bytes:
    """Generate a 256-bit account data key for encrypted sync payloads."""
    return AESGCM.generate_key(bit_length=256)


def encode_key(key: bytes) -> str:
    return base64.b64encode(key).decode("ascii")


def decode_key(value: str) -> bytes:
    key = base64.b64decode(value.encode("ascii"), validate=True)
    if len(key) != 32:
        raise ValueError("sync account key must be 32 bytes")
    return key


def generate_recovery_key() -> str:
    """Generate a user-held recovery key for restoring encrypted sync on new devices."""
    return RECOVERY_KEY_PREFIX + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def generate_device_key_pair() -> DeviceKeyPair:
    private = x25519.X25519PrivateKey.generate()
    public = private.public_key()
    return DeviceKeyPair(
        private_key=base64.b64encode(
            private.private_bytes(
                encoding=Encoding.Raw,
                format=PrivateFormat.Raw,
                encryption_algorithm=NoEncryption(),
            )
        ).decode("ascii"),
        public_key=base64.b64encode(public.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)).decode("ascii"),
    )


def wrap_account_key_for_device(
    *,
    account_id: str,
    account_key: bytes,
    recipient_public_key: str,
) -> dict[str, Any]:
    _validate_key(account_key)
    ephemeral = x25519.X25519PrivateKey.generate()
    recipient = x25519.X25519PublicKey.from_public_bytes(_decode_raw_key(recipient_public_key, "device public key"))
    shared = ephemeral.exchange(recipient)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    aad = _device_envelope_aad(account_id)
    wrapping_key = _derive_device_wrapping_key(shared, salt)
    ciphertext = AESGCM(wrapping_key).encrypt(nonce, account_key, aad)
    return {
        "version": 1,
        "algorithm": "x25519-aes-256-gcm",
        "ephemeral_public_key": base64.b64encode(
            ephemeral.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
        ).decode("ascii"),
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "aad_hash": base64.b64encode(hashlib.sha256(aad).digest()).decode("ascii"),
    }


def unwrap_account_key_for_device(
    *,
    account_id: str,
    private_key: str,
    envelope: dict[str, Any],
) -> bytes:
    if int(envelope.get("version") or 0) != 1:
        raise ValueError("unsupported device key envelope version")
    if envelope.get("algorithm") != "x25519-aes-256-gcm":
        raise ValueError("unsupported device key envelope algorithm")
    aad = _device_envelope_aad(account_id)
    expected_hash = base64.b64encode(hashlib.sha256(aad).digest()).decode("ascii")
    if envelope.get("aad_hash") != expected_hash:
        raise ValueError("device key envelope metadata authentication hash mismatch")
    private = x25519.X25519PrivateKey.from_private_bytes(_decode_raw_key(private_key, "device private key"))
    ephemeral_public = x25519.X25519PublicKey.from_public_bytes(
        _decode_raw_key(str(envelope.get("ephemeral_public_key") or ""), "ephemeral public key")
    )
    shared = private.exchange(ephemeral_public)
    salt = base64.b64decode(str(envelope["salt"]).encode("ascii"), validate=True)
    nonce = base64.b64decode(str(envelope["nonce"]).encode("ascii"), validate=True)
    ciphertext = base64.b64decode(str(envelope["ciphertext"]).encode("ascii"), validate=True)
    account_key = AESGCM(_derive_device_wrapping_key(shared, salt)).decrypt(nonce, ciphertext, aad)
    _validate_key(account_key)
    return account_key


def create_recovery_envelope(
    *,
    account_id: str,
    account_key: bytes,
    recovery_key: str,
) -> RecoveryKeyEnvelope:
    """Wrap the account data key using a recovery key the server never sees."""
    _validate_key(account_key)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    aad = _recovery_aad(account_id)
    wrapping_key = _derive_recovery_wrapping_key(recovery_key, salt, RECOVERY_KEY_ITERATIONS)
    ciphertext = AESGCM(wrapping_key).encrypt(nonce, account_key, aad)
    return RecoveryKeyEnvelope(
        version=1,
        kdf="pbkdf2-sha256",
        iterations=RECOVERY_KEY_ITERATIONS,
        salt=base64.b64encode(salt).decode("ascii"),
        nonce=base64.b64encode(nonce).decode("ascii"),
        ciphertext=base64.b64encode(ciphertext).decode("ascii"),
        aad_hash=base64.b64encode(hashlib.sha256(aad).digest()).decode("ascii"),
    )


def recover_account_key(
    *,
    account_id: str,
    recovery_key: str,
    envelope: RecoveryKeyEnvelope,
) -> bytes:
    """Recover an account data key from a user-held recovery key and opaque envelope."""
    aad = _recovery_aad(account_id)
    expected_hash = base64.b64encode(hashlib.sha256(aad).digest()).decode("ascii")
    if envelope.version != 1:
        raise ValueError("unsupported sync recovery envelope version")
    if envelope.kdf != "pbkdf2-sha256":
        raise ValueError("unsupported sync recovery envelope kdf")
    if envelope.aad_hash != expected_hash:
        raise ValueError("sync recovery envelope metadata authentication hash mismatch")
    salt = base64.b64decode(envelope.salt.encode("ascii"), validate=True)
    nonce = base64.b64decode(envelope.nonce.encode("ascii"), validate=True)
    ciphertext = base64.b64decode(envelope.ciphertext.encode("ascii"), validate=True)
    wrapping_key = _derive_recovery_wrapping_key(recovery_key, salt, envelope.iterations)
    account_key = AESGCM(wrapping_key).decrypt(nonce, ciphertext, aad)
    _validate_key(account_key)
    return account_key


def recovery_envelope_from_dict(raw: dict[str, Any]) -> RecoveryKeyEnvelope:
    return RecoveryKeyEnvelope(
        version=int(raw["version"]),
        kdf=str(raw["kdf"]),
        iterations=int(raw["iterations"]),
        salt=str(raw["salt"]),
        nonce=str(raw["nonce"]),
        ciphertext=str(raw["ciphertext"]),
        aad_hash=str(raw["aad_hash"]),
    )


def encrypt_record(account_id: str, account_key: bytes, record: PlainSyncRecord) -> EncryptedSyncRecord:
    """Encrypt a sync payload before it can be written to disk or uploaded."""
    _validate_key(account_key)
    nonce = os.urandom(12)
    plaintext = json.dumps(record.payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    aad = _aad(account_id, record)
    ciphertext = AESGCM(account_key).encrypt(nonce, plaintext, aad)
    return EncryptedSyncRecord(
        collection=record.collection,
        record_id=record.record_id,
        rev=record.rev,
        updated_at=record.updated_at,
        device_id=record.device_id,
        deleted=record.deleted,
        content_type=record.content_type,
        ciphertext=base64.b64encode(ciphertext).decode("ascii"),
        nonce=base64.b64encode(nonce).decode("ascii"),
        aad_hash=base64.b64encode(hashlib.sha256(aad).digest()).decode("ascii"),
        payload_bytes=len(plaintext),
    )


def decrypt_record(account_id: str, account_key: bytes, encrypted: EncryptedSyncRecord) -> dict[str, Any]:
    """Decrypt and verify an encrypted sync payload locally."""
    _validate_key(account_key)
    aad = _aad(
        account_id,
        PlainSyncRecord(
            collection=encrypted.collection,
            record_id=encrypted.record_id,
            rev=encrypted.rev,
            updated_at=encrypted.updated_at,
            device_id=encrypted.device_id,
            deleted=encrypted.deleted,
            content_type=encrypted.content_type,
            payload={},
        ),
    )
    expected_hash = base64.b64encode(hashlib.sha256(aad).digest()).decode("ascii")
    if encrypted.aad_hash != expected_hash:
        raise ValueError("sync record metadata authentication hash mismatch")
    plaintext = AESGCM(account_key).decrypt(
        base64.b64decode(encrypted.nonce.encode("ascii"), validate=True),
        base64.b64decode(encrypted.ciphertext.encode("ascii"), validate=True),
        aad,
    )
    parsed = json.loads(plaintext.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("sync record payload must be a JSON object")
    return parsed


class SyncOutbox:
    """Append-only encrypted mutation journal drained by the cloud sync engine."""

    def __init__(
        self,
        *,
        path: Path = SYNC_OUTBOX_PATH,
        account_id: str,
        account_key: bytes,
        device_id: str,
    ) -> None:
        _validate_key(account_key)
        self.path = path
        self.account_id = account_id
        self.account_key = account_key
        self.device_id = device_id

    def enqueue(
        self,
        *,
        collection: SyncCollection,
        record_id: str,
        payload: dict[str, Any],
        content_type: str,
        rev: int = 1,
        updated_at: str | None = None,
        deleted: bool = False,
    ) -> EncryptedSyncRecord:
        if not record_id.strip():
            raise ValueError("sync record_id is required")
        record = PlainSyncRecord(
            collection=collection,
            record_id=record_id,
            rev=max(1, int(rev)),
            updated_at=updated_at or utc_now_iso(),
            device_id=self.device_id,
            deleted=deleted,
            content_type=content_type,
            payload=payload,
        )
        encrypted = encrypt_record(self.account_id, self.account_key, record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(encrypted), sort_keys=True, separators=(",", ":")) + "\n")
        return encrypted

    def pending(self) -> list[EncryptedSyncRecord]:
        if not self.path.is_file():
            return []
        records: list[EncryptedSyncRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                try:
                    records.append(encrypted_record_from_dict(raw))
                except (TypeError, ValueError):
                    continue
        return records

    def replace_pending(self, records: list[EncryptedSyncRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(asdict(record), sort_keys=True, separators=(",", ":")) for record in records]
        _atomic_write_text(self.path, "\n".join(lines) + ("\n" if lines else ""))


class SyncSettingsStore:
    """Non-secret sync consent state plus OS-secret-backed account key access."""

    def __init__(
        self,
        *,
        path: Path = SYNC_STATE_PATH,
        device_path: Path = SYNC_DEVICE_PATH,
        outbox_path: Path = SYNC_OUTBOX_PATH,
        save_key=api_keys_mod.save_sync_account_key,
        read_key=api_keys_mod.read_sync_account_key,
        clear_key=api_keys_mod.clear_sync_account_key,
    ) -> None:
        self.path = path
        self.device_path = device_path
        self.outbox_path = outbox_path
        self._save_key = save_key
        self._read_key = read_key
        self._clear_key = clear_key

    def load(self) -> SyncState:
        if not self.path.is_file():
            return SyncState(enabled=False, account_id="", device_id="")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SyncState(enabled=False, account_id="", device_id="")
        if not isinstance(raw, dict):
            return SyncState(enabled=False, account_id="", device_id="")
        return SyncState(
            enabled=bool(raw.get("enabled", False)),
            account_id=str(raw.get("account_id") or ""),
            device_id=str(raw.get("device_id") or ""),
            enabled_at=_optional_state_str(raw.get("enabled_at")),
            last_seq=_positive_state_int(raw.get("last_seq"), 0),
        )

    def enable(
        self,
        account_id: str,
        *,
        account_key: bytes | None = None,
        device_id: str | None = None,
    ) -> tuple[SyncState, bytes]:
        account = account_id.strip()
        if not account:
            raise ValueError("account_id is required to enable sync")
        key = account_key or generate_account_key()
        _validate_key(key)
        device = save_sync_device(device_id, path=self.device_path) if device_id else load_or_create_device(self.device_path)
        self._save_key(account, encode_key(key))
        state = SyncState(
            enabled=True,
            account_id=account,
            device_id=device.device_id,
            enabled_at=utc_now_iso(),
            last_seq=0,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, asdict(state))
        return state, key

    def disable(self, *, clear_key: bool = False) -> SyncState:
        current = self.load()
        if clear_key and current.account_id:
            self._clear_key(current.account_id)
        state = SyncState(
            enabled=False,
            account_id=current.account_id,
            device_id=current.device_id,
            last_seq=current.last_seq,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, asdict(state))
        return state

    def set_cursor(self, last_seq: int) -> SyncState:
        current = self.load()
        state = SyncState(
            enabled=current.enabled,
            account_id=current.account_id,
            device_id=current.device_id,
            enabled_at=current.enabled_at,
            last_seq=max(0, int(last_seq)),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, asdict(state))
        return state

    def account_key(self) -> bytes | None:
        state = self.load()
        if not state.enabled or not state.account_id:
            return None
        encoded = self._read_key(state.account_id)
        return decode_key(encoded) if encoded else None

    def outbox(self, *, path: Path | None = None) -> SyncOutbox | None:
        state = self.load()
        key = self.account_key()
        if key is None or not state.account_id or not state.device_id:
            return None
        return SyncOutbox(
            path=path or self.outbox_path,
            account_id=state.account_id,
            account_key=key,
            device_id=state.device_id,
        )


def enqueue_lexicon_hotwords(
    outbox: SyncOutbox | None,
    terms: list[str],
    *,
    deleted: bool = False,
    updated_at: str | None = None,
) -> int:
    """Queue encrypted hotword mutations for cloud sync when sync is enabled."""
    if outbox is None:
        return 0
    count = 0
    timestamp = updated_at or utc_now_iso()
    for term in terms:
        if not isinstance(term, str):
            continue
        normalized = " ".join(term.split()).casefold()
        if not normalized:
            continue
        outbox.enqueue(
            collection="lexicon",
            record_id=f"hotword:{_stable_lexicon_id(normalized)}",
            content_type=SYNC_LEXICON_CONTENT_TYPE,
            payload={"kind": "hotword", "term": term, "updated_at": timestamp},
            deleted=deleted,
        )
        count += 1
    return count


def enqueue_lexicon_replacements(
    outbox: SyncOutbox | None,
    replacements: dict[str, str | None],
    *,
    deleted: bool = False,
    updated_at: str | None = None,
) -> int:
    """Queue encrypted lexical replacement mutations for cloud sync when sync is enabled."""
    if outbox is None:
        return 0
    count = 0
    timestamp = updated_at or utc_now_iso()
    for wrong, right in replacements.items():
        if not isinstance(wrong, str):
            continue
        normalized = " ".join(wrong.split()).casefold()
        if not normalized:
            continue
        outbox.enqueue(
            collection="lexicon",
            record_id=f"replacement:{_stable_lexicon_id(normalized)}",
            content_type=SYNC_LEXICON_CONTENT_TYPE,
            payload={
                "kind": "replacement",
                "wrong": wrong,
                "right": right or "",
                "updated_at": timestamp,
            },
            deleted=deleted,
        )
        count += 1
    return count


def encrypted_record_from_dict(raw: dict[str, Any]) -> EncryptedSyncRecord:
    return EncryptedSyncRecord(
        collection=_collection(str(raw["collection"])),
        record_id=str(raw["record_id"]),
        rev=int(raw["rev"]),
        updated_at=str(raw["updated_at"]),
        device_id=str(raw["device_id"]),
        deleted=bool(raw["deleted"]),
        content_type=str(raw["content_type"]),
        ciphertext=str(raw["ciphertext"]),
        nonce=str(raw["nonce"]),
        aad_hash=str(raw["aad_hash"]),
        payload_bytes=int(raw["payload_bytes"]),
    )


def _optional_state_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _positive_state_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _collection(value: str) -> SyncCollection:
    if value not in {"history", "note", "segment", "settings", "lexicon"}:
        raise ValueError(f"unknown sync collection: {value}")
    return value  # type: ignore[return-value]


def _stable_lexicon_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aad(account_id: str, record: PlainSyncRecord) -> bytes:
    parts = (
        account_id,
        record.collection,
        record.record_id,
        str(record.rev),
        record.updated_at,
        record.device_id,
        "1" if record.deleted else "0",
        record.content_type,
    )
    return "\x1f".join(parts).encode("utf-8")


def _recovery_aad(account_id: str) -> bytes:
    account = account_id.strip()
    if not account:
        raise ValueError("account_id is required for sync recovery envelopes")
    return f"dictate-sync-recovery:v1:{account}".encode("utf-8")


def _device_envelope_aad(account_id: str) -> bytes:
    account = account_id.strip()
    if not account:
        raise ValueError("account_id is required for device key envelopes")
    return f"dictate-sync-device-envelope:v1:{account}".encode("utf-8")


def _derive_device_wrapping_key(shared_secret: bytes, salt: bytes) -> bytes:
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    ).derive(shared_secret)


def _derive_recovery_wrapping_key(recovery_key: str, salt: bytes, iterations: int) -> bytes:
    if not recovery_key.startswith(RECOVERY_KEY_PREFIX):
        raise ValueError("invalid sync recovery key format")
    if iterations < 100_000:
        raise ValueError("sync recovery key kdf iterations are too low")
    token = recovery_key.removeprefix(RECOVERY_KEY_PREFIX)
    padding = "=" * (-len(token) % 4)
    try:
        material = base64.urlsafe_b64decode((token + padding).encode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid sync recovery key format") from exc
    if len(material) != 32:
        raise ValueError("invalid sync recovery key length")
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=int(iterations),
    ).derive(material)


def _decode_raw_key(value: str, label: str) -> bytes:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"invalid {label}") from exc
    if len(raw) != 32:
        raise ValueError(f"invalid {label} length")
    return raw


def _validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("sync account key must be 32 bytes")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2))


def _atomic_write_text(path: Path, content: str) -> None:
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        fd.write(content)
        fd.flush()
        fd.close()
        Path(fd.name).replace(path)
    except Exception:
        try:
            Path(fd.name).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise
