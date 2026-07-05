"""Client-side Dictate Pro sync engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dictate.history import HistoryStore
from dictate.note_store import NoteStore
from dictate.pro.client import ProClient
from dictate.sync import SyncSettingsStore, decrypt_record, encrypted_record_from_dict


@dataclass(slots=True)
class SyncRunResult:
    enabled: bool
    pushed: int = 0
    remaining: int = 0
    pulled: int = 0
    applied: int = 0
    last_seq: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "pushed": self.pushed,
            "remaining": self.remaining,
            "pulled": self.pulled,
            "applied": self.applied,
            "lastSeq": self.last_seq,
            "error": self.error,
        }


class SyncEngine:
    def __init__(
        self,
        *,
        settings: SyncSettingsStore,
        pro_client: ProClient,
        history_store: HistoryStore,
        note_store: NoteStore,
    ) -> None:
        self.settings = settings
        self.pro_client = pro_client
        self.history_store = history_store
        self.note_store = note_store

    def attach_outbox(self) -> None:
        outbox = self.settings.outbox()
        self.history_store.attach_sync_outbox(outbox)
        self.note_store.attach_sync_outbox(outbox)

    def run_once(self, *, limit: int = 500) -> SyncRunResult:
        state = self.settings.load()
        if not state.enabled:
            self.history_store.attach_sync_outbox(None)
            self.note_store.attach_sync_outbox(None)
            return SyncRunResult(enabled=False, last_seq=state.last_seq)
        account_key = self.settings.account_key()
        outbox = self.settings.outbox()
        if account_key is None or outbox is None:
            return SyncRunResult(enabled=True, last_seq=state.last_seq, error="sync key unavailable")
        self.history_store.attach_sync_outbox(outbox)
        self.note_store.attach_sync_outbox(outbox)

        pushed = self.pro_client.drain_sync_outbox(outbox)
        changes = self.pro_client.get_sync_changes(since=state.last_seq, limit=limit)
        records = changes.get("records") if isinstance(changes, dict) else []
        if not isinstance(records, list):
            return SyncRunResult(
                enabled=True,
                pushed=int(pushed.get("pushed", 0)),
                remaining=int(pushed.get("remaining", 0)),
                last_seq=state.last_seq,
                error="invalid sync changes response",
            )

        applied = 0
        max_seq = state.last_seq
        for raw in records:
            if not isinstance(raw, dict):
                continue
            seq = int(raw.get("seq") or 0)
            encrypted = encrypted_record_from_dict(raw)
            payload = decrypt_record(state.account_id, account_key, encrypted)
            if self.apply_record(encrypted.collection, payload, deleted=encrypted.deleted):
                applied += 1
                max_seq = max(max_seq, seq)
        self.settings.set_cursor(max_seq)
        return SyncRunResult(
            enabled=True,
            pushed=int(pushed.get("pushed", 0)),
            remaining=int(pushed.get("remaining", 0)),
            pulled=len(records),
            applied=applied,
            last_seq=max_seq,
        )

    def apply_record(self, collection: str, payload: dict[str, Any], *, deleted: bool = False) -> bool:
        if collection == "history":
            return self.history_store.apply_synced_entry(payload, deleted=deleted)
        if collection == "note":
            return self.note_store.apply_synced_note(payload, deleted=deleted)
        if collection == "segment":
            return self.note_store.apply_synced_segment(payload, deleted=deleted)
        # Settings and lexicon are intentionally deferred until config split is complete.
        return False
