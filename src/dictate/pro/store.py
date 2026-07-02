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


class ProStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
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
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempts_remaining INTEGER NOT NULL
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
                """
            )
            try:
                conn.execute("ALTER TABLE subscriptions ADD COLUMN last_event_created INTEGER")
            except sqlite3.OperationalError:
                pass

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

    def register_device(self, *, account_id: str, device_id: str | None, label: str) -> str:
        device = device_id or f"dev_{uuid.uuid4().hex}"
        now = iso()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT device_id FROM devices WHERE device_id = ?",
                (device,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE devices SET last_seen_at = ?, label = ? WHERE device_id = ?",
                    (now, label, device),
                )
                return device
            conn.execute(
                """
                INSERT INTO devices (device_id, account_id, label, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (device, account_id, label, now, now),
            )
            return device

    def touch_device(self, device_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE devices SET last_seen_at = ? WHERE device_id = ?",
                (iso(), device_id),
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
                        segment.text,
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
