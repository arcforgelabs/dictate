"""Encrypted local foundations for Dictate Pro cloud sync."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dictate.platform_paths import user_data_dir

SYNC_DEVICE_PATH = user_data_dir() / "sync-device.json"
SYNC_OUTBOX_PATH = user_data_dir() / "sync-outbox.jsonl"

SyncCollection = Literal["history", "note", "segment", "settings", "lexicon"]


@dataclass(frozen=True, slots=True)
class SyncDevice:
    device_id: str
    created_at: str


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
            if device_id.startswith("device_") and created_at:
                return SyncDevice(device_id=device_id, created_at=created_at)

    device = SyncDevice(device_id=f"device_{uuid.uuid4().hex}", created_at=utc_now_iso())
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


def _collection(value: str) -> SyncCollection:
    if value not in {"history", "note", "segment", "settings", "lexicon"}:
        raise ValueError(f"unknown sync collection: {value}")
    return value  # type: ignore[return-value]


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
