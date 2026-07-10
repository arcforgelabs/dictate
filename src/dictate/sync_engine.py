"""Client-side Dictate Pro sync engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag

from dictate import config as config_mod
from dictate.history import HistoryStore
from dictate.note_store import NoteStore
from dictate.pro.client import ProClient
from dictate.sync import SYNCED_PREF_KEYS, SyncSettingsStore, decrypt_record, encrypted_record_from_dict


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
        config_path: Path = config_mod.CONFIG_PATH,
        prefs_store: Any | None = None,
    ) -> None:
        self.settings = settings
        self.pro_client = pro_client
        self.history_store = history_store
        self.note_store = note_store
        self.config_path = config_path
        self.prefs_store = prefs_store

    def attach_outbox(self) -> None:
        outbox = self.settings.outbox()
        # sync_scope="meetings" syncs note+segment only; the rolling quick-copy history is
        # detached so its enqueues become no-ops. Unset defaults to "everything" (backward
        # compatible); enable_sync sets "meetings" for newly enabled sync. See
        # docs/record-categories-spec.md.
        scope = config_mod.load_config(self.config_path).sync_scope or "everything"
        self.history_store.attach_sync_outbox(outbox if scope == "everything" else None)
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

        try:
            pushed = self.pro_client.drain_sync_outbox(outbox)
        except Exception as exc:  # noqa: BLE001
            return SyncRunResult(
                enabled=True,
                remaining=len(outbox.pending()),
                last_seq=state.last_seq,
                error=f"sync push failed: {exc}",
            )
        pulled = 0
        applied = 0
        current_seq = state.last_seq
        while True:
            try:
                changes = self.pro_client.get_sync_changes(since=current_seq, limit=limit)
            except Exception as exc:  # noqa: BLE001
                return SyncRunResult(
                    enabled=True,
                    pushed=int(pushed.get("pushed", 0)),
                    remaining=int(pushed.get("remaining", 0)),
                    pulled=pulled,
                    applied=applied,
                    last_seq=current_seq,
                    error=f"sync pull failed: {exc}",
                )
            records = changes.get("records") if isinstance(changes, dict) else []
            if not isinstance(records, list):
                return SyncRunResult(
                    enabled=True,
                    pushed=int(pushed.get("pushed", 0)),
                    remaining=int(pushed.get("remaining", 0)),
                    pulled=pulled,
                    applied=applied,
                    last_seq=current_seq,
                    error="invalid sync changes response",
                )
            if not records:
                break

            page_applied = 0
            page_max_seq = current_seq
            for raw in records:
                if not isinstance(raw, dict):
                    continue
                seq = int(raw.get("seq") or 0)
                try:
                    encrypted = encrypted_record_from_dict(raw)
                    payload = decrypt_record(state.account_id, account_key, encrypted)
                    payload.setdefault("updated_at", encrypted.updated_at)
                except (InvalidTag, KeyError, TypeError, ValueError) as exc:
                    return SyncRunResult(
                        enabled=True,
                        pushed=int(pushed.get("pushed", 0)),
                        remaining=int(pushed.get("remaining", 0)),
                        pulled=pulled + len(records),
                        applied=applied + page_applied,
                        last_seq=current_seq,
                        error=f"invalid encrypted sync record at seq {seq}: {exc}",
                    )
                if self.apply_record(encrypted.collection, payload, deleted=encrypted.deleted):
                    page_applied += 1
                page_max_seq = max(page_max_seq, seq)
            pulled += len(records)
            applied += page_applied
            if page_max_seq > current_seq:
                self.settings.set_cursor(page_max_seq)
                try:
                    self.pro_client.update_sync_cursor(last_seq=page_max_seq)
                except Exception as exc:  # noqa: BLE001
                    return SyncRunResult(
                        enabled=True,
                        pushed=int(pushed.get("pushed", 0)),
                        remaining=int(pushed.get("remaining", 0)),
                        pulled=pulled,
                        applied=applied,
                        last_seq=page_max_seq,
                        error=f"sync cursor update failed: {exc}",
                    )
                current_seq = page_max_seq
            if not _has_more(changes):
                break
        return SyncRunResult(
            enabled=True,
            pushed=int(pushed.get("pushed", 0)),
            remaining=int(pushed.get("remaining", 0)),
            pulled=pulled,
            applied=applied,
            last_seq=current_seq,
        )

    def apply_record(self, collection: str, payload: dict[str, Any], *, deleted: bool = False) -> bool:
        if collection == "history":
            return self.history_store.apply_synced_entry(payload, deleted=deleted)
        if collection == "note":
            return self.note_store.apply_synced_note(payload, deleted=deleted)
        if collection == "segment":
            return self.note_store.apply_synced_segment(payload, deleted=deleted)
        if collection == "settings":
            return self.apply_synced_setting(payload, deleted=deleted)
        if collection == "lexicon":
            return self.apply_synced_lexicon(payload, deleted=deleted)
        return False

    def apply_synced_setting(self, payload: dict[str, Any], *, deleted: bool = False) -> bool:
        if deleted:
            return False
        key = payload.get("key")
        if key not in SYNCED_PREF_KEYS:
            return False
        if self.prefs_store is None:
            return False
        if hasattr(self.prefs_store, "apply_synced_setting"):
            return bool(
                self.prefs_store.apply_synced_setting(
                    str(key),
                    payload.get("value"),
                    updated_at=payload.get("updated_at"),
                    deleted=deleted,
                )
            )
        self.prefs_store.update({str(key): payload.get("value")})
        return True

    def apply_synced_lexicon(self, payload: dict[str, Any], *, deleted: bool = False) -> bool:
        kind = payload.get("kind")
        if kind == "hotword":
            term = payload.get("term")
            if not isinstance(term, str) or not term.strip():
                return False
            if deleted:
                return bool(config_mod.remove_hotwords([term], path=self.config_path))
            config_mod.add_hotwords([term], path=self.config_path)
            return True
        if kind == "replacement":
            wrong = payload.get("wrong")
            right = payload.get("right")
            if not isinstance(wrong, str) or not wrong.strip():
                return False
            if deleted:
                return bool(config_mod.remove_lexicon_replacements([wrong], path=self.config_path))
            if not isinstance(right, str) or not right.strip():
                return False
            config_mod.add_lexicon_replacements({wrong: right}, path=self.config_path)
            return True
        return False


def _has_more(changes: dict[str, Any]) -> bool:
    return changes.get("has_more") is True or changes.get("hasMore") is True
