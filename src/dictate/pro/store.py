"""SQLite persistence for the Dictate Pro control plane."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from dictate.pro.signing import MetadataSigner

MeetingStatus = Literal[
    "queued",
    "uploading",
    "processing",
    "ready",
    "failed",
    "quota_exceeded",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    value = dt or utcnow()
    return value.replace(microsecond=0).isoformat()


@dataclass(slots=True)
class AccountRow:
    account_id: str
    email: str
    stripe_customer_id: str | None


@dataclass(slots=True)
class SubscriptionRow:
    account_id: str
    stripe_subscription_id: str
    stripe_customer_id: str
    plan_id: str
    status: str
    current_period_start: str
    current_period_end: str
    cancel_at_period_end: bool
    last_event_created: int | None = None


@dataclass(slots=True)
class AccessGrantRow:
    grant_id: str
    account_id: str
    plan_id: str
    status: str
    source: str
    starts_at: str
    expires_at: str | None
    revoked_at: str | None
    note: str | None
    created_at: str
    updated_at: str


@dataclass(slots=True)
class UsagePeriodRow:
    account_id: str
    plan_id: str
    period_start: str
    period_end: str
    included_seconds: int
    used_seconds: int


@dataclass(slots=True)
class MeetingJobRow:
    job_id: str
    account_id: str
    device_id: str
    plan_id: str
    status: MeetingStatus
    mode: str
    provider: str
    provider_model: str
    language: str | None
    requested_diarization: bool
    audio_duration_seconds: float | None
    billable_seconds: int | None
    billing_period_start: str | None
    billing_period_end: str | None
    provider_request_id: str | None
    error: str | None
    retry_count: int
    created_at: str
    started_at: str | None
    completed_at: str | None


@dataclass(slots=True)
class TranscriptSegmentRow:
    seq: int
    speaker_id: str
    speaker_label: str
    text: str
    t_start: float
    t_end: float


@dataclass(slots=True)
class SyncRecordRow:
    account_id: str
    collection: str
    record_id: str
    seq: int
    rev: int
    device_id: str
    updated_at: str
    deleted: bool
    content_type: str
    ciphertext: str
    nonce: str
    aad_hash: str
    payload_bytes: int


@dataclass(slots=True)
class DeviceRow:
    account_id: str
    device_id: str
    label: str
    public_key: str | None
    created_at: str
    trusted_at: str | None
    revoked_at: str | None
    last_seen_at: str
    signature: dict[str, str] | None


@dataclass(slots=True)
class SyncCursorRow:
    account_id: str
    device_id: str
    last_seq: int
    updated_at: str


@dataclass(slots=True)
class KeyEnvelopeRow:
    account_id: str
    device_id: str
    envelope_kind: str
    envelope_json: str
    created_at: str
    updated_at: str
    signature: dict[str, str] | None


class ProStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._signer = MetadataSigner.load_or_create(self._db_path.parent / "server-signing-key.pem")
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    stripe_customer_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT 'Desktop',
                    public_key TEXT,
                    trusted_at TEXT,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    signature_json TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempts_remaining INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_codes (
                    code_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    redirect_uri TEXT NOT NULL,
                    code_challenge TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    device_label TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS device_codes (
                    device_code_hash TEXT PRIMARY KEY,
                    user_code TEXT NOT NULL UNIQUE,
                    account_id TEXT,
                    client_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    device_label TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    interval INTEGER NOT NULL,
                    last_polled_at TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    consumed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    device_id TEXT,
                    token_type TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    stripe_subscription_id TEXT NOT NULL UNIQUE,
                    stripe_customer_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_period_start TEXT NOT NULL,
                    current_period_end TEXT NOT NULL,
                    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_subscriptions_account
                    ON subscriptions(account_id);

                CREATE TABLE IF NOT EXISTS access_grants (
                    grant_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    expires_at TEXT,
                    revoked_at TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_access_grants_account
                    ON access_grants(account_id);

                CREATE TABLE IF NOT EXISTS usage_periods (
                    usage_period_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    included_seconds INTEGER NOT NULL,
                    used_seconds INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(account_id, period_start)
                );

                CREATE TABLE IF NOT EXISTS usage_events (
                    event_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    billable_seconds INTEGER NOT NULL,
                    period_start TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meeting_jobs (
                    job_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_model TEXT NOT NULL,
                    language TEXT,
                    requested_diarization INTEGER NOT NULL,
                    audio_duration_seconds REAL,
                    billable_seconds INTEGER,
                    billing_period_start TEXT,
                    billing_period_end TEXT,
                    provider_request_id TEXT,
                    error TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS transcript_segments (
                    segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    speaker_id TEXT NOT NULL,
                    speaker_label TEXT NOT NULL,
                    text TEXT NOT NULL,
                    t_start REAL NOT NULL,
                    t_end REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_transcript_segments_job
                    ON transcript_segments(job_id, seq);

                CREATE TABLE IF NOT EXISTS billing_events (
                    event_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_records (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    collection TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    rev INTEGER NOT NULL,
                    device_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0,
                    content_type TEXT NOT NULL,
                    ciphertext TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    aad_hash TEXT NOT NULL,
                    payload_bytes INTEGER NOT NULL,
                    UNIQUE(account_id, collection, record_id)
                );

                CREATE INDEX IF NOT EXISTS idx_sync_records_account_seq
                    ON sync_records(account_id, seq);

                CREATE INDEX IF NOT EXISTS idx_sync_records_account_device
                    ON sync_records(account_id, device_id);

                CREATE TABLE IF NOT EXISTS sync_cursors (
                    account_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    last_seq INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (account_id, device_id)
                );

                CREATE TABLE IF NOT EXISTS key_envelopes (
                    account_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    envelope_kind TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    signature_json TEXT,
                    PRIMARY KEY (account_id, device_id, envelope_kind)
                );

                CREATE INDEX IF NOT EXISTS idx_key_envelopes_account
                    ON key_envelopes(account_id);
                """
            )
            try:
                conn.execute("ALTER TABLE subscriptions ADD COLUMN last_event_created INTEGER")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE access_grants ADD COLUMN note TEXT")
            except sqlite3.OperationalError:
                pass
            trusted_at_column_added = False
            try:
                conn.execute("ALTER TABLE devices ADD COLUMN trusted_at TEXT")
                trusted_at_column_added = True
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE devices ADD COLUMN revoked_at TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE devices ADD COLUMN public_key TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE devices ADD COLUMN signature_json TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE key_envelopes ADD COLUMN signature_json TEXT")
            except sqlite3.OperationalError:
                pass
            if trusted_at_column_added:
                conn.execute(
                    """
                    UPDATE devices
                    SET trusted_at = COALESCE(trusted_at, created_at)
                    WHERE trusted_at IS NULL
                    """
                )
            for row in conn.execute(
                """
                SELECT account_id, device_id
                FROM devices
                WHERE signature_json IS NULL
                """
            ).fetchall():
                self._refresh_device_signature(conn, account_id=row["account_id"], device_id=row["device_id"])
            for row in conn.execute(
                """
                SELECT account_id, device_id, envelope_kind
                FROM key_envelopes
                WHERE signature_json IS NULL
                """
            ).fetchall():
                self._refresh_key_envelope_signature(
                    conn,
                    account_id=row["account_id"],
                    device_id=row["device_id"],
                    envelope_kind=row["envelope_kind"],
                )

    def upsert_sync_records(
        self,
        *,
        account_id: str,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Upsert opaque encrypted sync records using metadata-only LWW rules."""
        outcomes: list[dict[str, Any]] = []
        with self._conn() as conn:
            for raw in records:
                incoming = _coerce_sync_record(account_id, raw)
                existing = conn.execute(
                    """
                    SELECT *
                    FROM sync_records
                    WHERE account_id = ? AND collection = ? AND record_id = ?
                    """,
                    (account_id, incoming["collection"], incoming["record_id"]),
                ).fetchone()
                if existing is not None and not _incoming_sync_wins(incoming, dict(existing)):
                    outcomes.append({"status": "superseded", "record": _sync_record_payload(existing)})
                    continue
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO sync_records (
                            account_id, collection, record_id, rev, device_id, updated_at,
                            deleted, content_type, ciphertext, nonce, aad_hash, payload_bytes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            account_id,
                            incoming["collection"],
                            incoming["record_id"],
                            incoming["rev"],
                            incoming["device_id"],
                            incoming["updated_at"],
                            1 if incoming["deleted"] else 0,
                            incoming["content_type"],
                            incoming["ciphertext"],
                            incoming["nonce"],
                            incoming["aad_hash"],
                            incoming["payload_bytes"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE sync_records
                        SET seq = (SELECT COALESCE(MAX(seq), 0) + 1 FROM sync_records),
                            rev = ?,
                            device_id = ?,
                            updated_at = ?,
                            deleted = ?,
                            content_type = ?,
                            ciphertext = ?,
                            nonce = ?,
                            aad_hash = ?,
                            payload_bytes = ?
                        WHERE account_id = ? AND collection = ? AND record_id = ?
                        """,
                        (
                            incoming["rev"],
                            incoming["device_id"],
                            incoming["updated_at"],
                            1 if incoming["deleted"] else 0,
                            incoming["content_type"],
                            incoming["ciphertext"],
                            incoming["nonce"],
                            incoming["aad_hash"],
                            incoming["payload_bytes"],
                            account_id,
                            incoming["collection"],
                            incoming["record_id"],
                        ),
                    )
                row = conn.execute(
                    """
                    SELECT *
                    FROM sync_records
                    WHERE account_id = ? AND collection = ? AND record_id = ?
                    """,
                    (account_id, incoming["collection"], incoming["record_id"]),
                ).fetchone()
                outcomes.append({"status": "accepted", "record": _sync_record_payload(row)})
        return outcomes

    def list_sync_changes(
        self,
        *,
        account_id: str,
        since: int,
        limit: int,
    ) -> list[SyncRecordRow]:
        bounded_limit = min(max(1, int(limit)), 1000)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM sync_records
                WHERE account_id = ? AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (account_id, max(0, int(since)), bounded_limit),
            ).fetchall()
            return [_sync_record_row(row) for row in rows]

    def get_sync_storage_usage(self, account_id: str) -> dict[str, int]:
        """Return account-scoped sync counters without reading plaintext content."""
        with self._conn() as conn:
            sync_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS record_count,
                    COALESCE(SUM(payload_bytes), 0) AS payload_bytes,
                    COALESCE(SUM(LENGTH(ciphertext)), 0) AS ciphertext_bytes,
                    COALESCE(SUM(LENGTH(nonce)), 0) AS nonce_bytes,
                    COALESCE(SUM(LENGTH(aad_hash)), 0) AS aad_hash_bytes
                FROM sync_records
                WHERE account_id = ?
                """,
                (account_id,),
            ).fetchone()
            envelope_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS key_envelope_count,
                    COALESCE(SUM(LENGTH(envelope_json)), 0) AS key_envelope_bytes
                FROM key_envelopes
                WHERE account_id = ?
                """,
                (account_id,),
            ).fetchone()
            device_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS device_count,
                    COALESCE(SUM(CASE WHEN trusted_at IS NOT NULL AND revoked_at IS NULL THEN 1 ELSE 0 END), 0)
                        AS trusted_device_count,
                    COALESCE(SUM(CASE WHEN trusted_at IS NULL AND revoked_at IS NULL THEN 1 ELSE 0 END), 0)
                        AS pending_device_count,
                    COALESCE(SUM(CASE WHEN revoked_at IS NOT NULL THEN 1 ELSE 0 END), 0)
                        AS revoked_device_count
                FROM devices
                WHERE account_id = ?
                """,
                (account_id,),
            ).fetchone()
        ciphertext_bytes = int(sync_row["ciphertext_bytes"])
        nonce_bytes = int(sync_row["nonce_bytes"])
        aad_hash_bytes = int(sync_row["aad_hash_bytes"])
        key_envelope_bytes = int(envelope_row["key_envelope_bytes"])
        return {
            "record_count": int(sync_row["record_count"]),
            "payload_bytes": int(sync_row["payload_bytes"]),
            "ciphertext_bytes": ciphertext_bytes,
            "nonce_bytes": nonce_bytes,
            "aad_hash_bytes": aad_hash_bytes,
            "key_envelope_count": int(envelope_row["key_envelope_count"]),
            "key_envelope_bytes": key_envelope_bytes,
            "device_count": int(device_row["device_count"]),
            "trusted_device_count": int(device_row["trusted_device_count"]),
            "pending_device_count": int(device_row["pending_device_count"]),
            "revoked_device_count": int(device_row["revoked_device_count"]),
            "stored_bytes": ciphertext_bytes + nonce_bytes + aad_hash_bytes + key_envelope_bytes,
        }

    def set_sync_cursor(self, *, account_id: str, device_id: str, last_seq: int) -> SyncCursorRow:
        device = device_id.strip()
        if not device:
            raise ValueError("device_id is required")
        seq = max(0, int(last_seq))
        now = iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sync_cursors (account_id, device_id, last_seq, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id, device_id) DO UPDATE SET
                    last_seq = MAX(sync_cursors.last_seq, excluded.last_seq),
                    updated_at = excluded.updated_at
                """,
                (account_id, device, seq, now),
            )
            row = conn.execute(
                """
                SELECT account_id, device_id, last_seq, updated_at
                FROM sync_cursors
                WHERE account_id = ? AND device_id = ?
                """,
                (account_id, device),
            ).fetchone()
            return _sync_cursor_row(row)

    def get_sync_cursor(self, *, account_id: str, device_id: str) -> SyncCursorRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT account_id, device_id, last_seq, updated_at
                FROM sync_cursors
                WHERE account_id = ? AND device_id = ?
                """,
                (account_id, device_id),
            ).fetchone()
            return _sync_cursor_row(row) if row else None

    def save_key_envelope(
        self,
        *,
        account_id: str,
        device_id: str,
        envelope_kind: str,
        envelope: dict[str, Any],
    ) -> KeyEnvelopeRow:
        kind = envelope_kind.strip()
        device = device_id.strip()
        if not device:
            raise ValueError("device_id is required")
        if kind not in {"recovery", "device"}:
            raise ValueError("unsupported key envelope kind")
        envelope_json = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        now = iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO key_envelopes (
                    account_id, device_id, envelope_kind, envelope_json, created_at, updated_at, signature_json
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(account_id, device_id, envelope_kind) DO UPDATE SET
                    envelope_json = excluded.envelope_json,
                    updated_at = excluded.updated_at
                """,
                (account_id, device, kind, envelope_json, now, now),
            )
            self._refresh_key_envelope_signature(conn, account_id=account_id, device_id=device, envelope_kind=kind)
            row = conn.execute(
                """
                SELECT account_id, device_id, envelope_kind, envelope_json, created_at, updated_at, signature_json
                FROM key_envelopes
                WHERE account_id = ? AND device_id = ? AND envelope_kind = ?
                """,
                (account_id, device, kind),
            ).fetchone()
            return _key_envelope_row(row)

    def list_key_envelopes(
        self,
        *,
        account_id: str,
        envelope_kind: str | None = None,
    ) -> list[KeyEnvelopeRow]:
        with self._conn() as conn:
            if envelope_kind:
                rows = conn.execute(
                    """
                    SELECT account_id, device_id, envelope_kind, envelope_json, created_at, updated_at, signature_json
                    FROM key_envelopes
                    WHERE account_id = ? AND envelope_kind = ?
                    ORDER BY updated_at ASC
                    """,
                    (account_id, envelope_kind.strip()),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT account_id, device_id, envelope_kind, envelope_json, created_at, updated_at, signature_json
                    FROM key_envelopes
                    WHERE account_id = ?
                    ORDER BY updated_at ASC
                    """,
                    (account_id,),
                ).fetchall()
            return [_key_envelope_row(row) for row in rows]

    def export_account_cloud_data(self, account_id: str) -> dict[str, Any]:
        """Return account-scoped cloud data without decrypting sync payloads."""
        with self._conn() as conn:
            account = conn.execute(
                "SELECT account_id, email, stripe_customer_id, created_at, updated_at FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if account is None:
                return {}
            devices = conn.execute(
                """
                SELECT account_id, device_id, label, public_key, created_at, trusted_at,
                       revoked_at, last_seen_at, signature_json
                FROM devices
                WHERE account_id = ?
                ORDER BY created_at ASC
                """,
                (account_id,),
            ).fetchall()
            sync_records = conn.execute(
                """
                SELECT *
                FROM sync_records
                WHERE account_id = ?
                ORDER BY seq ASC
                """,
                (account_id,),
            ).fetchall()
            key_envelopes = conn.execute(
                """
                SELECT account_id, device_id, envelope_kind, envelope_json, created_at, updated_at, signature_json
                FROM key_envelopes
                WHERE account_id = ?
                ORDER BY updated_at ASC
                """,
                (account_id,),
            ).fetchall()
            sync_cursors = conn.execute(
                """
                SELECT account_id, device_id, last_seq, updated_at
                FROM sync_cursors
                WHERE account_id = ?
                ORDER BY updated_at ASC
                """,
                (account_id,),
            ).fetchall()
            meetings = conn.execute(
                """
                SELECT *
                FROM meeting_jobs
                WHERE account_id = ?
                ORDER BY created_at ASC
                """,
                (account_id,),
            ).fetchall()
            transcripts: dict[str, list[dict[str, Any]]] = {}
            for job in meetings:
                rows = conn.execute(
                    """
                    SELECT seq, speaker_id, speaker_label, text, t_start, t_end
                    FROM transcript_segments
                    WHERE job_id = ?
                    ORDER BY seq ASC
                    """,
                    (job["job_id"],),
                ).fetchall()
                transcripts[job["job_id"]] = [dict(row) for row in rows]
            return {
                "account": dict(account),
                "devices": [_device_payload(row) for row in devices],
                "key_envelopes": [_key_envelope_payload(row) for row in key_envelopes],
                "sync_cursors": [dict(row) for row in sync_cursors],
                "sync_records": [_sync_record_payload(row) for row in sync_records],
                "meeting_jobs": [dict(row) for row in meetings],
                "transcript_segments": transcripts,
            }

    def delete_account_cloud_data(self, account_id: str) -> dict[str, int]:
        """Delete account-owned Dictate cloud data while retaining billing identity."""
        counts: dict[str, int] = {}
        with self._conn() as conn:
            meeting_rows = conn.execute(
                "SELECT job_id FROM meeting_jobs WHERE account_id = ?",
                (account_id,),
            ).fetchall()
            job_ids = [row["job_id"] for row in meeting_rows]
            if job_ids:
                placeholders = ",".join("?" * len(job_ids))
                cur = conn.execute(
                    f"DELETE FROM transcript_segments WHERE job_id IN ({placeholders})",
                    job_ids,
                )
                counts["transcript_segments"] = cur.rowcount
            else:
                counts["transcript_segments"] = 0
            for table in ("key_envelopes", "sync_cursors", "sync_records", "meeting_jobs", "usage_events", "usage_periods"):
                cur = conn.execute(f"DELETE FROM {table} WHERE account_id = ?", (account_id,))
                counts[table] = cur.rowcount
            cur = conn.execute(
                "UPDATE devices SET revoked_at = COALESCE(revoked_at, ?) WHERE account_id = ?",
                (iso(), account_id),
            )
            counts["devices_revoked"] = cur.rowcount
        return counts

    def get_or_create_account(self, email: str) -> AccountRow:
        normalized = email.strip().lower()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT account_id, email, stripe_customer_id FROM accounts WHERE email = ?",
                (normalized,),
            ).fetchone()
            if row:
                return AccountRow(row["account_id"], row["email"], row["stripe_customer_id"])
            account_id = f"acct_{uuid.uuid4().hex}"
            now = iso()
            conn.execute(
                """
                INSERT INTO accounts (account_id, email, stripe_customer_id, created_at, updated_at)
                VALUES (?, ?, NULL, ?, ?)
                """,
                (account_id, normalized, now, now),
            )
            return AccountRow(account_id, normalized, None)

    def link_stripe_customer(self, *, account_id: str, stripe_customer_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE accounts
                SET stripe_customer_id = ?, updated_at = ?
                WHERE account_id = ?
                """,
                (stripe_customer_id, iso(), account_id),
            )

    def get_account(self, account_id: str) -> AccountRow | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT account_id, email, stripe_customer_id FROM accounts WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if not row:
                return None
            return AccountRow(row["account_id"], row["email"], row["stripe_customer_id"])

    def get_account_by_email(self, email: str) -> AccountRow | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT account_id, email, stripe_customer_id FROM accounts WHERE email = ?",
                (email.strip().lower(),),
            ).fetchone()
            if not row:
                return None
            return AccountRow(row["account_id"], row["email"], row["stripe_customer_id"])

    def get_account_by_stripe_customer(self, stripe_customer_id: str) -> AccountRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT account_id, email, stripe_customer_id
                FROM accounts
                WHERE stripe_customer_id = ?
                """,
                (stripe_customer_id,),
            ).fetchone()
            if not row:
                return None
            return AccountRow(row["account_id"], row["email"], row["stripe_customer_id"])

    def register_device(
        self,
        *,
        account_id: str,
        device_id: str | None,
        label: str,
        public_key: str | None = None,
    ) -> str:
        device = device_id or f"dev_{uuid.uuid4().hex}"
        normalized_public_key = public_key.strip() if isinstance(public_key, str) and public_key.strip() else None
        now = iso()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT device_id, account_id FROM devices WHERE device_id = ?",
                (device,),
            ).fetchone()
            if existing and existing["account_id"] != account_id:
                # device_id is a global primary key but callers (email code's complete_sign_in,
                # the authorization_code grant) can supply an arbitrary caller-chosen device_id
                # in the request body. Without this check, an authenticated caller for account A
                # could overwrite account B's device row (label/public_key) merely by naming B's
                # device_id -- device_is_known() would still block the resulting session, but the
                # tamper against B's row would already have persisted. Reject outright rather than
                # silently minting a new id, so the caller sees the failure.
                raise ValueError("device_id belongs to a different account")
            if existing:
                conn.execute(
                    """
                    UPDATE devices
                    SET last_seen_at = ?,
                        label = ?,
                        public_key = COALESCE(?, public_key)
                    WHERE device_id = ?
                    """,
                    (now, label, normalized_public_key, device),
                )
                self._refresh_device_signature(conn, account_id=account_id, device_id=device)
                return device
            trusted_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM devices
                WHERE account_id = ? AND revoked_at IS NULL AND trusted_at IS NOT NULL
                """,
                (account_id,),
            ).fetchone()
            trusted_at = now if int(trusted_count["count"] if trusted_count else 0) == 0 else None
            conn.execute(
                """
                INSERT INTO devices (
                    device_id, account_id, label, public_key, trusted_at, revoked_at,
                    created_at, last_seen_at, signature_json
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL)
                """,
                (device, account_id, label, normalized_public_key, trusted_at, now, now),
            )
            self._refresh_device_signature(conn, account_id=account_id, device_id=device)
            return device

    def approve_device(self, *, account_id: str, device_id: str) -> bool:
        now = iso()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE devices
                SET trusted_at = COALESCE(trusted_at, ?), last_seen_at = ?
                WHERE account_id = ? AND device_id = ? AND revoked_at IS NULL
                """,
                (now, now, account_id, device_id),
            )
            if cur.rowcount:
                self._refresh_device_signature(conn, account_id=account_id, device_id=device_id)
            return cur.rowcount > 0

    def touch_device(self, device_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                (iso(), device_id),
            )

    def list_devices(self, account_id: str) -> list[DeviceRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT account_id, device_id, label, public_key, created_at, trusted_at,
                       revoked_at, last_seen_at, signature_json
                FROM devices
                WHERE account_id = ?
                ORDER BY created_at ASC
                """,
                (account_id,),
            ).fetchall()
            return [_device_row(row) for row in rows]

    def get_device(self, *, account_id: str, device_id: str) -> DeviceRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT account_id, device_id, label, public_key, created_at, trusted_at,
                       revoked_at, last_seen_at, signature_json
                FROM devices
                WHERE account_id = ? AND device_id = ?
                """,
                (account_id, device_id),
            ).fetchone()
            return _device_row(row) if row else None

    def revoke_device(self, *, account_id: str, device_id: str) -> bool:
        now = iso()
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE devices
                SET revoked_at = COALESCE(revoked_at, ?), last_seen_at = last_seen_at
                WHERE account_id = ? AND device_id = ?
                """,
                (now, account_id, device_id),
            )
            if cur.rowcount:
                self._refresh_device_signature(conn, account_id=account_id, device_id=device_id)
                conn.execute(
                    """
                    UPDATE auth_tokens
                    SET revoked_at = COALESCE(revoked_at, ?)
                    WHERE account_id = ? AND device_id = ?
                    """,
                    (now, account_id, device_id),
                )
            return cur.rowcount > 0

    def device_is_active(self, *, account_id: str, device_id: str | None) -> bool:
        if not device_id:
            return False
        device = self.get_device(account_id=account_id, device_id=device_id)
        return bool(device and device.revoked_at is None and device.trusted_at is not None)

    def device_is_known(self, *, account_id: str, device_id: str | None) -> bool:
        if not device_id:
            return False
        device = self.get_device(account_id=account_id, device_id=device_id)
        return bool(device and device.revoked_at is None)

    def _refresh_device_signature(self, conn: sqlite3.Connection, *, account_id: str, device_id: str) -> None:
        row = conn.execute(
            """
            SELECT account_id, device_id, label, public_key, created_at, trusted_at, revoked_at
            FROM devices
            WHERE account_id = ? AND device_id = ?
            """,
            (account_id, device_id),
        ).fetchone()
        if row is None:
            return
        signature = self._signer.bundle(_device_signature_payload(row))
        conn.execute(
            """
            UPDATE devices
            SET signature_json = ?
            WHERE account_id = ? AND device_id = ?
            """,
            (json.dumps(signature, sort_keys=True, separators=(",", ":")), account_id, device_id),
        )

    def _refresh_key_envelope_signature(
        self,
        conn: sqlite3.Connection,
        *,
        account_id: str,
        device_id: str,
        envelope_kind: str,
    ) -> None:
        row = conn.execute(
            """
            SELECT account_id, device_id, envelope_kind, envelope_json, created_at, updated_at
            FROM key_envelopes
            WHERE account_id = ? AND device_id = ? AND envelope_kind = ?
            """,
            (account_id, device_id, envelope_kind),
        ).fetchone()
        if row is None:
            return
        signature = self._signer.bundle(_key_envelope_signature_payload(row))
        conn.execute(
            """
            UPDATE key_envelopes
            SET signature_json = ?
            WHERE account_id = ? AND device_id = ? AND envelope_kind = ?
            """,
            (json.dumps(signature, sort_keys=True, separators=(",", ":")), account_id, device_id, envelope_kind),
        )

    def save_auth_challenge(
        self,
        *,
        challenge_id: str,
        email: str,
        code_hash: str,
        expires_at: str,
        attempts_remaining: int,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO auth_challenges
                (challenge_id, email, code_hash, expires_at, attempts_remaining)
                VALUES (?, ?, ?, ?, ?)
                """,
                (challenge_id, email.strip().lower(), code_hash, expires_at, attempts_remaining),
            )

    def get_auth_challenge(self, challenge_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM auth_challenges WHERE challenge_id = ?",
                (challenge_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_auth_challenge(self, challenge_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM auth_challenges WHERE challenge_id = ?", (challenge_id,))

    def save_auth_code(
        self,
        *,
        code_hash: str,
        account_id: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        scope: str,
        device_label: str,
        expires_at: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO auth_codes
                (code_hash, account_id, client_id, redirect_uri, code_challenge, scope,
                 device_label, created_at, expires_at, consumed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    code_hash,
                    account_id,
                    client_id,
                    redirect_uri,
                    code_challenge,
                    scope,
                    device_label,
                    iso(),
                    expires_at,
                ),
            )

    def get_auth_code(self, code_hash: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM auth_codes WHERE code_hash = ?",
                (code_hash,),
            ).fetchone()
            return dict(row) if row else None

    def consume_auth_code(self, code_hash: str) -> bool:
        """Mark an authorization code used; returns False if already consumed (replay)."""
        now = iso()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE auth_codes SET consumed_at = ? WHERE code_hash = ? AND consumed_at IS NULL",
                (now, code_hash),
            )
            consumed = cur.rowcount > 0
            # Opportunistic cleanup: every exchange attempt is a convenient, low-cost hook
            # to sweep codes that can never be used again (already consumed, or past their
            # 120s TTL), so auth_codes doesn't grow unbounded on a long-running server.
            conn.execute(
                "DELETE FROM auth_codes WHERE consumed_at IS NOT NULL OR expires_at < ?",
                (now,),
            )
            return consumed

    def save_device_code(
        self,
        *,
        device_code_hash: str,
        user_code: str,
        client_id: str,
        scope: str,
        device_label: str,
        expires_at: str,
        interval: int,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO device_codes (
                    device_code_hash, user_code, account_id, client_id, scope, device_label,
                    created_at, expires_at, interval, last_polled_at, status, consumed_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, 'pending', NULL)
                """,
                (device_code_hash, user_code, client_id, scope, device_label, iso(), expires_at, interval),
            )

    def get_device_code(self, device_code_hash: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM device_codes WHERE device_code_hash = ?",
                (device_code_hash,),
            ).fetchone()
            return dict(row) if row else None

    def approve_device_code(self, *, user_code: str, account_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE device_codes
                SET account_id = ?, status = 'approved'
                WHERE user_code = ? AND status = 'pending' AND consumed_at IS NULL
                """,
                (account_id, user_code),
            )
            return cur.rowcount > 0

    def deny_device_code(self, *, user_code: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                """
                UPDATE device_codes
                SET status = 'denied'
                WHERE user_code = ? AND status = 'pending' AND consumed_at IS NULL
                """,
                (user_code,),
            )
            return cur.rowcount > 0

    def touch_device_code_poll(self, device_code_hash: str, *, last_polled_at: str, interval: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE device_codes SET last_polled_at = ?, interval = ? WHERE device_code_hash = ?",
                (last_polled_at, interval, device_code_hash),
            )

    def consume_device_code(self, device_code_hash: str) -> bool:
        """Mark a device_code used; returns False if already consumed (replay)."""
        now = iso()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE device_codes SET consumed_at = ? WHERE device_code_hash = ? AND consumed_at IS NULL",
                (now, device_code_hash),
            )
            consumed = cur.rowcount > 0
            # Opportunistic cleanup, same rationale as consume_auth_code: sweep rows that
            # can never be used again so device_codes doesn't grow unbounded.
            conn.execute(
                "DELETE FROM device_codes WHERE consumed_at IS NOT NULL OR expires_at < ?",
                (now,),
            )
            return consumed

    def save_auth_token(
        self,
        *,
        token_hash: str,
        account_id: str,
        device_id: str | None,
        token_type: str,
        expires_at: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO auth_tokens
                (token_hash, account_id, device_id, token_type, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (token_hash, account_id, device_id, token_type, expires_at),
            )

    def get_auth_token(self, token_hash: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM auth_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            return dict(row) if row else None

    def revoke_auth_token(self, token_hash: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE auth_tokens SET revoked_at = ? WHERE token_hash = ?",
                (iso(), token_hash),
            )

    def upsert_subscription(self, row: SubscriptionRow) -> None:
        with self._conn() as conn:
            self._upsert_subscription(conn, row)

    def upsert_subscription_if_fresh(
        self,
        row: SubscriptionRow,
        *,
        event_created: int | None,
    ) -> Literal["applied", "skipped"]:
        """Atomically upsert only when event_created is not stale."""
        with self._conn() as conn:
            existing = conn.execute(
                """
                SELECT last_event_created
                FROM subscriptions
                WHERE stripe_subscription_id = ?
                """,
                (row.stripe_subscription_id,),
            ).fetchone()
            # Stripe event_created is second-granularity; two events in the same
            # second cannot be ordered by timestamp alone (accepted residual).
            if (
                event_created is not None
                and existing is not None
                and existing["last_event_created"] is not None
                and event_created < int(existing["last_event_created"])
            ):
                return "skipped"
            self._upsert_subscription(conn, row)
            return "applied"

    def _upsert_subscription(self, conn: sqlite3.Connection, row: SubscriptionRow) -> None:
        conn.execute(
            """
            INSERT INTO subscriptions (
                account_id, stripe_subscription_id, stripe_customer_id, plan_id, status,
                current_period_start, current_period_end, cancel_at_period_end, updated_at,
                last_event_created
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stripe_subscription_id) DO UPDATE SET
                account_id = excluded.account_id,
                stripe_customer_id = excluded.stripe_customer_id,
                plan_id = excluded.plan_id,
                status = excluded.status,
                current_period_start = excluded.current_period_start,
                current_period_end = excluded.current_period_end,
                cancel_at_period_end = excluded.cancel_at_period_end,
                updated_at = excluded.updated_at,
                last_event_created = excluded.last_event_created
            """,
            (
                row.account_id,
                row.stripe_subscription_id,
                row.stripe_customer_id,
                row.plan_id,
                row.status,
                row.current_period_start,
                row.current_period_end,
                1 if row.cancel_at_period_end else 0,
                iso(),
                row.last_event_created,
            ),
        )

    def get_subscription_by_stripe_id(self, stripe_subscription_id: str) -> SubscriptionRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT account_id, stripe_subscription_id, stripe_customer_id, plan_id, status,
                       current_period_start, current_period_end, cancel_at_period_end, last_event_created
                FROM subscriptions
                WHERE stripe_subscription_id = ?
                """,
                (stripe_subscription_id,),
            ).fetchone()
            if not row:
                return None
            return _subscription_row(row)

    def get_active_subscription(self, account_id: str) -> SubscriptionRow | None:
        active_statuses = ("active", "trialing", "past_due")
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT account_id, stripe_subscription_id, stripe_customer_id, plan_id, status,
                       current_period_start, current_period_end, cancel_at_period_end, last_event_created
                FROM subscriptions
                WHERE account_id = ?
                  AND status IN ({})
                ORDER BY updated_at DESC
                LIMIT 1
                """.format(",".join("?" * len(active_statuses))),
                (account_id, *active_statuses),
            ).fetchone()
            if not row:
                return None
            return _subscription_row(row)

    def upsert_access_grant(
        self,
        *,
        account_id: str,
        plan_id: str,
        status: str,
        source: str,
        starts_at: str,
        expires_at: str | None = None,
        note: str | None = None,
        grant_id: str | None = None,
    ) -> AccessGrantRow:
        grant = grant_id or f"grant_{uuid.uuid4().hex}"
        now = iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO access_grants (
                    grant_id, account_id, plan_id, status, source, starts_at, expires_at,
                    revoked_at, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                ON CONFLICT(grant_id) DO UPDATE SET
                    plan_id = excluded.plan_id,
                    status = excluded.status,
                    source = excluded.source,
                    starts_at = excluded.starts_at,
                    expires_at = excluded.expires_at,
                    revoked_at = NULL,
                    note = excluded.note,
                    updated_at = excluded.updated_at
                """,
                (grant, account_id, plan_id, status, source, starts_at, expires_at, note, now, now),
            )
            row = conn.execute(
                """
                SELECT grant_id, account_id, plan_id, status, source, starts_at, expires_at,
                       revoked_at, note, created_at, updated_at
                FROM access_grants
                WHERE grant_id = ?
                """,
                (grant,),
            ).fetchone()
            return _access_grant_row(row)

    def get_active_access_grant(self, account_id: str, *, now: str | None = None) -> AccessGrantRow | None:
        active_statuses = ("active", "trialing")
        checked_at = now or iso()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT grant_id, account_id, plan_id, status, source, starts_at, expires_at,
                       revoked_at, note, created_at, updated_at
                FROM access_grants
                WHERE account_id = ?
                  AND status IN ({})
                  AND revoked_at IS NULL
                  AND starts_at <= ?
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY
                  CASE WHEN expires_at IS NULL THEN 1 ELSE 0 END DESC,
                  updated_at DESC
                LIMIT 1
                """.format(",".join("?" * len(active_statuses))),
                (account_id, *active_statuses, checked_at, checked_at),
            ).fetchone()
            return _access_grant_row(row) if row else None

    def list_access_grants(self, account_id: str) -> list[AccessGrantRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT grant_id, account_id, plan_id, status, source, starts_at, expires_at,
                       revoked_at, note, created_at, updated_at
                FROM access_grants
                WHERE account_id = ?
                ORDER BY updated_at DESC
                """,
                (account_id,),
            ).fetchall()
            return [_access_grant_row(row) for row in rows]

    def revoke_access_grants(self, *, account_id: str, plan_id: str | None = None) -> int:
        now = iso()
        with self._conn() as conn:
            if plan_id:
                cur = conn.execute(
                    """
                    UPDATE access_grants
                    SET revoked_at = COALESCE(revoked_at, ?), updated_at = ?
                    WHERE account_id = ? AND plan_id = ? AND revoked_at IS NULL
                    """,
                    (now, now, account_id, plan_id),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE access_grants
                    SET revoked_at = COALESCE(revoked_at, ?), updated_at = ?
                    WHERE account_id = ? AND revoked_at IS NULL
                    """,
                    (now, now, account_id),
                )
            return int(cur.rowcount)

    def ensure_usage_period(
        self,
        *,
        account_id: str,
        plan_id: str,
        period_start: str,
        period_end: str,
        included_seconds: int,
    ) -> UsagePeriodRow:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT account_id, plan_id, period_start, period_end, included_seconds, used_seconds
                FROM usage_periods
                WHERE account_id = ? AND period_start = ?
                """,
                (account_id, period_start),
            ).fetchone()
            if row:
                return UsagePeriodRow(
                    account_id=row["account_id"],
                    plan_id=row["plan_id"],
                    period_start=row["period_start"],
                    period_end=row["period_end"],
                    included_seconds=row["included_seconds"],
                    used_seconds=row["used_seconds"],
                )
            conn.execute(
                """
                INSERT INTO usage_periods
                (account_id, plan_id, period_start, period_end, included_seconds, used_seconds)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (account_id, plan_id, period_start, period_end, included_seconds),
            )
            return UsagePeriodRow(
                account_id=account_id,
                plan_id=plan_id,
                period_start=period_start,
                period_end=period_end,
                included_seconds=included_seconds,
                used_seconds=0,
            )

    def get_usage_period(self, account_id: str, period_start: str) -> UsagePeriodRow | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT account_id, plan_id, period_start, period_end, included_seconds, used_seconds
                FROM usage_periods
                WHERE account_id = ? AND period_start = ?
                """,
                (account_id, period_start),
            ).fetchone()
            if not row:
                return None
            return UsagePeriodRow(
                account_id=row["account_id"],
                plan_id=row["plan_id"],
                period_start=row["period_start"],
                period_end=row["period_end"],
                included_seconds=row["included_seconds"],
                used_seconds=row["used_seconds"],
            )

    def reserve_usage_seconds(
        self,
        *,
        account_id: str,
        period_start: str,
        seconds: int,
        hard_stop_seconds: int,
    ) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT used_seconds, included_seconds
                FROM usage_periods
                WHERE account_id = ? AND period_start = ?
                """,
                (account_id, period_start),
            ).fetchone()
            if not row:
                return False
            projected = int(row["used_seconds"]) + max(0, seconds)
            limit = min(int(row["included_seconds"]), hard_stop_seconds)
            if projected > limit:
                return False
            conn.execute(
                """
                UPDATE usage_periods
                SET used_seconds = used_seconds + ?
                WHERE account_id = ? AND period_start = ?
                """,
                (max(0, seconds), account_id, period_start),
            )
            return True

    def release_usage_seconds(
        self,
        *,
        account_id: str,
        period_start: str,
        seconds: int,
    ) -> None:
        if seconds <= 0:
            return
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE usage_periods
                SET used_seconds = MAX(0, used_seconds - ?)
                WHERE account_id = ? AND period_start = ?
                """,
                (seconds, account_id, period_start),
            )

    def adjust_usage_seconds(
        self,
        *,
        account_id: str,
        period_start: str,
        seconds: int,
    ) -> None:
        if seconds == 0:
            return
        with self._conn() as conn:
            if seconds > 0:
                conn.execute(
                    """
                    UPDATE usage_periods
                    SET used_seconds = used_seconds + ?
                    WHERE account_id = ? AND period_start = ?
                    """,
                    (seconds, account_id, period_start),
                )
            else:
                conn.execute(
                    """
                    UPDATE usage_periods
                    SET used_seconds = MAX(0, used_seconds + ?)
                    WHERE account_id = ? AND period_start = ?
                    """,
                    (seconds, account_id, period_start),
                )

    def record_usage_event(
        self,
        *,
        event_id: str,
        account_id: str,
        job_id: str,
        billable_seconds: int,
        period_start: str,
    ) -> bool:
        with self._conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO usage_events
                    (event_id, account_id, job_id, billable_seconds, period_start, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (event_id, account_id, job_id, billable_seconds, period_start, iso()),
                )
            except sqlite3.IntegrityError:
                return False
            return True

    def delete_usage_event(self, event_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM usage_events WHERE event_id = ?", (event_id,))
            return cur.rowcount > 0

    def usage_event_exists(self, event_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM usage_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return row is not None

    def create_meeting_job(
        self,
        *,
        account_id: str,
        device_id: str,
        plan_id: str,
        mode: str,
        provider: str,
        provider_model: str,
        language: str | None,
        requested_diarization: bool,
        billing_period_start: str | None,
        billing_period_end: str | None,
    ) -> MeetingJobRow:
        job_id = f"mtg_{uuid.uuid4().hex}"
        now = iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO meeting_jobs (
                    job_id, account_id, device_id, plan_id, status, mode, provider, provider_model,
                    language, requested_diarization, billing_period_start, billing_period_end,
                    retry_count, created_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    job_id,
                    account_id,
                    device_id,
                    plan_id,
                    mode,
                    provider,
                    provider_model,
                    language,
                    1 if requested_diarization else 0,
                    billing_period_start,
                    billing_period_end,
                    now,
                ),
            )
        return self.get_meeting_job(job_id)  # type: ignore[return-value]

    def get_meeting_job(self, job_id: str) -> MeetingJobRow | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM meeting_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return _meeting_row(row)

    def update_meeting_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [job_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE meeting_jobs SET {columns} WHERE job_id = ?", values)

    def claim_meeting_job(
        self,
        job_id: str,
        *,
        from_statuses: tuple[str, ...] = ("queued", "failed"),
        to: str = "processing",
    ) -> bool:
        now = iso()
        placeholders = ",".join("?" * len(from_statuses))
        with self._conn() as conn:
            cursor = conn.execute(
                f"""
                UPDATE meeting_jobs
                SET status = ?, started_at = ?
                WHERE job_id = ? AND status IN ({placeholders})
                """,
                (to, now, job_id, *from_statuses),
            )
            return cursor.rowcount == 1

    def save_transcript_segments(self, job_id: str, segments: list[TranscriptSegmentRow]) -> None:
        """Persist hosted meeting segment metadata without storing transcript text.

        Hosted transcription text is returned to the requesting client so it can be
        saved locally and synced through the encrypted sync lane. The Pro control
        plane must not retain readable dictated content.
        """
        with self._conn() as conn:
            conn.execute("DELETE FROM transcript_segments WHERE job_id = ?", (job_id,))
            conn.executemany(
                """
                INSERT INTO transcript_segments
                (job_id, seq, speaker_id, speaker_label, text, t_start, t_end)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        job_id,
                        segment.seq,
                        segment.speaker_id,
                        segment.speaker_label,
                        "",
                        segment.t_start,
                        segment.t_end,
                    )
                    for segment in segments
                ],
            )

    def get_transcript_segments(self, job_id: str) -> list[TranscriptSegmentRow]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT seq, speaker_id, speaker_label, text, t_start, t_end
                FROM transcript_segments
                WHERE job_id = ?
                ORDER BY seq ASC
                """,
                (job_id,),
            ).fetchall()
            return [
                TranscriptSegmentRow(
                    seq=row["seq"],
                    speaker_id=row["speaker_id"],
                    speaker_label=row["speaker_label"],
                    text=row["text"],
                    t_start=row["t_start"],
                    t_end=row["t_end"],
                )
                for row in rows
            ]

    def billing_event_exists(self, event_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM billing_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return row is not None

    def record_billing_event(self, *, event_id: str, provider: str, event_type: str, payload: dict[str, Any]) -> bool:
        with self._conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO billing_events (event_id, provider, event_type, payload_json, received_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_id, provider, event_type, json.dumps(payload), iso()),
                )
            except sqlite3.IntegrityError:
                return False
            return True


def _subscription_row(row: sqlite3.Row) -> SubscriptionRow:
    keys = row.keys()
    last_event_created = row["last_event_created"] if "last_event_created" in keys else None
    return SubscriptionRow(
        account_id=row["account_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        stripe_customer_id=row["stripe_customer_id"],
        plan_id=row["plan_id"],
        status=row["status"],
        current_period_start=row["current_period_start"],
        current_period_end=row["current_period_end"],
        cancel_at_period_end=bool(row["cancel_at_period_end"]),
        last_event_created=last_event_created,
    )


def _access_grant_row(row: sqlite3.Row) -> AccessGrantRow:
    return AccessGrantRow(
        grant_id=row["grant_id"],
        account_id=row["account_id"],
        plan_id=row["plan_id"],
        status=row["status"],
        source=row["source"],
        starts_at=row["starts_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _coerce_sync_record(account_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    collection = str(raw.get("collection") or "").strip()
    if collection not in {"history", "note", "segment", "settings", "lexicon"}:
        raise ValueError("invalid sync collection")
    record_id = str(raw.get("record_id") or "").strip()
    device_id = str(raw.get("device_id") or "").strip()
    updated_at = str(raw.get("updated_at") or "").strip()
    content_type = str(raw.get("content_type") or "").strip()
    ciphertext = str(raw.get("ciphertext") or "").strip()
    nonce = str(raw.get("nonce") or "").strip()
    aad_hash = str(raw.get("aad_hash") or "").strip()
    if not all((account_id, record_id, device_id, updated_at, content_type, ciphertext, nonce, aad_hash)):
        raise ValueError("sync record missing required fields")
    rev = int(raw.get("rev") or 1)
    payload_bytes = int(raw.get("payload_bytes") or 0)
    if rev < 1 or payload_bytes < 0:
        raise ValueError("invalid sync record revision or payload size")
    return {
        "account_id": account_id,
        "collection": collection,
        "record_id": record_id,
        "rev": rev,
        "device_id": device_id,
        "updated_at": updated_at,
        "deleted": bool(raw.get("deleted", False)),
        "content_type": content_type,
        "ciphertext": ciphertext,
        "nonce": nonce,
        "aad_hash": aad_hash,
        "payload_bytes": payload_bytes,
    }


def _incoming_sync_wins(incoming: dict[str, Any], existing: dict[str, Any]) -> bool:
    existing_tuple = (
        int(existing["rev"]),
        str(existing["updated_at"]),
        str(existing["device_id"]),
    )
    incoming_tuple = (
        int(incoming["rev"]),
        str(incoming["updated_at"]),
        str(incoming["device_id"]),
    )
    return incoming_tuple >= existing_tuple


def _sync_record_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "collection": row["collection"],
        "record_id": row["record_id"],
        "seq": int(row["seq"]),
        "rev": int(row["rev"]),
        "device_id": row["device_id"],
        "updated_at": row["updated_at"],
        "deleted": bool(row["deleted"]),
        "content_type": row["content_type"],
        "ciphertext": row["ciphertext"],
        "nonce": row["nonce"],
        "aad_hash": row["aad_hash"],
        "payload_bytes": int(row["payload_bytes"]),
    }


def _sync_record_row(row: sqlite3.Row) -> SyncRecordRow:
    return SyncRecordRow(
        account_id=row["account_id"],
        collection=row["collection"],
        record_id=row["record_id"],
        seq=int(row["seq"]),
        rev=int(row["rev"]),
        device_id=row["device_id"],
        updated_at=row["updated_at"],
        deleted=bool(row["deleted"]),
        content_type=row["content_type"],
        ciphertext=row["ciphertext"],
        nonce=row["nonce"],
        aad_hash=row["aad_hash"],
        payload_bytes=int(row["payload_bytes"]),
    )


def _sync_cursor_row(row: sqlite3.Row) -> SyncCursorRow:
    return SyncCursorRow(
        account_id=row["account_id"],
        device_id=row["device_id"],
        last_seq=int(row["last_seq"]),
        updated_at=row["updated_at"],
    )


def _device_row(row: sqlite3.Row) -> DeviceRow:
    return DeviceRow(
        account_id=row["account_id"],
        device_id=row["device_id"],
        label=row["label"],
        public_key=row["public_key"],
        created_at=row["created_at"],
        trusted_at=row["trusted_at"],
        revoked_at=row["revoked_at"],
        last_seen_at=row["last_seen_at"],
        signature=_decode_signature(row["signature_json"]),
    )


def _device_payload(row: sqlite3.Row | DeviceRow) -> dict[str, Any]:
    if isinstance(row, DeviceRow):
        payload_source = {
            "account_id": row.account_id,
            "device_id": row.device_id,
            "label": row.label,
            "public_key": row.public_key,
            "created_at": row.created_at,
            "trusted_at": row.trusted_at,
            "revoked_at": row.revoked_at,
            "last_seen_at": row.last_seen_at,
            "signature": row.signature,
        }
    else:
        payload_source = {
            "account_id": row["account_id"],
            "device_id": row["device_id"],
            "label": row["label"],
            "public_key": row["public_key"],
            "created_at": row["created_at"],
            "trusted_at": row["trusted_at"],
            "revoked_at": row["revoked_at"],
            "last_seen_at": row["last_seen_at"],
            "signature": _decode_signature(row["signature_json"]),
        }
    return {
        "account_id": payload_source["account_id"],
        "device_id": payload_source["device_id"],
        "label": payload_source["label"],
        "public_key": payload_source["public_key"],
        "created_at": payload_source["created_at"],
        "trusted_at": payload_source["trusted_at"],
        "revoked_at": payload_source["revoked_at"],
        "last_seen_at": payload_source["last_seen_at"],
        "signed_metadata": _device_signature_payload(payload_source),
        "server_signature": payload_source["signature"],
    }


def _key_envelope_payload(row: sqlite3.Row | KeyEnvelopeRow) -> dict[str, Any]:
    envelope_json = row.envelope_json if isinstance(row, KeyEnvelopeRow) else row["envelope_json"]
    payload_source = {
        "account_id": row.account_id if isinstance(row, KeyEnvelopeRow) else row["account_id"],
        "device_id": row.device_id if isinstance(row, KeyEnvelopeRow) else row["device_id"],
        "envelope_kind": row.envelope_kind if isinstance(row, KeyEnvelopeRow) else row["envelope_kind"],
        "envelope_json": envelope_json,
        "created_at": row.created_at if isinstance(row, KeyEnvelopeRow) else row["created_at"],
        "updated_at": row.updated_at if isinstance(row, KeyEnvelopeRow) else row["updated_at"],
    }
    return {
        "account_id": payload_source["account_id"],
        "device_id": payload_source["device_id"],
        "envelope_kind": payload_source["envelope_kind"],
        "envelope": json.loads(envelope_json),
        "created_at": payload_source["created_at"],
        "updated_at": payload_source["updated_at"],
        "signed_metadata": _key_envelope_signature_payload(payload_source),
        "server_signature": row.signature if isinstance(row, KeyEnvelopeRow) else _decode_signature(row["signature_json"]),
    }


def _key_envelope_row(row: sqlite3.Row) -> KeyEnvelopeRow:
    return KeyEnvelopeRow(
        account_id=row["account_id"],
        device_id=row["device_id"],
        envelope_kind=row["envelope_kind"],
        envelope_json=row["envelope_json"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        signature=_decode_signature(row["signature_json"]),
    )


def _decode_signature(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return {str(key): str(item) for key, item in decoded.items()}


def _device_signature_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata_type": "dictate.pro.device",
        "account_id": row["account_id"],
        "device_id": row["device_id"],
        "label": row["label"],
        "public_key": row["public_key"],
        "created_at": row["created_at"],
        "trusted_at": row["trusted_at"],
        "revoked_at": row["revoked_at"],
    }


def _key_envelope_signature_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata_type": "dictate.pro.key_envelope",
        "account_id": row["account_id"],
        "device_id": row["device_id"],
        "envelope_kind": row["envelope_kind"],
        "envelope_hash": _sha256_text(row["envelope_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _meeting_row(row: sqlite3.Row) -> MeetingJobRow:
    return MeetingJobRow(
        job_id=row["job_id"],
        account_id=row["account_id"],
        device_id=row["device_id"],
        plan_id=row["plan_id"],
        status=row["status"],
        mode=row["mode"],
        provider=row["provider"],
        provider_model=row["provider_model"],
        language=row["language"],
        requested_diarization=bool(row["requested_diarization"]),
        audio_duration_seconds=row["audio_duration_seconds"],
        billable_seconds=row["billable_seconds"],
        billing_period_start=row["billing_period_start"],
        billing_period_end=row["billing_period_end"],
        provider_request_id=row["provider_request_id"],
        error=row["error"],
        retry_count=row["retry_count"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )
