"""Persistent rolling history of recent successful dictations."""

from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dictate.platform_paths import user_data_dir
from dictate.sync import SyncOutbox

MAX_ENTRIES = 20
HISTORY_PATH = user_data_dir() / "recent-history.json"


@dataclass(slots=True)
class HistoryEntry:
    id: str
    created_at: str
    text: str
    archived: bool = False
    rev: int = 1
    updated_at: str | None = None


class HistoryStore:
    """Thread-safe rolling buffer of recent dictation texts, persisted to JSON."""

    def __init__(self, path: Path = HISTORY_PATH, sync_outbox: SyncOutbox | None = None) -> None:
        self._path = path
        self._sync_outbox = sync_outbox

    def attach_sync_outbox(self, sync_outbox: SyncOutbox | None) -> None:
        self._sync_outbox = sync_outbox

    def load(self, *, include_archived: bool = False) -> list[HistoryEntry]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text())
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(raw, dict):
            return []
        entries_raw = raw.get("entries", [])
        if not isinstance(entries_raw, list):
            return []
        entries: list[HistoryEntry] = []
        for item in entries_raw:
            if not isinstance(item, dict):
                continue
            entry_id = item.get("id")
            created_at = item.get("created_at")
            text = item.get("text")
            if isinstance(entry_id, str) and isinstance(created_at, str) and isinstance(text, str):
                entries.append(
                    HistoryEntry(
                        id=entry_id,
                        created_at=created_at,
                        text=text,
                        archived=bool(item.get("archived", False)),
                        rev=_positive_int(item.get("rev"), 1),
                        updated_at=_optional_str(item.get("updated_at")),
                    )
                )
        if not include_archived:
            entries = [entry for entry in entries if not entry.archived]
        return entries[:MAX_ENTRIES]

    def archive(self, entry_id: str) -> bool:
        entries = self.load(include_archived=True)
        found = False
        updated: list[HistoryEntry] = []
        for entry in entries:
            if entry.id != entry_id:
                updated.append(entry)
                continue
            found = True
            updated.append(
                HistoryEntry(
                    id=entry.id,
                    created_at=entry.created_at,
                    text=entry.text,
                    archived=True,
                    rev=entry.rev + 1,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        if not found:
            return False
        self._save(updated)
        self._enqueue_entry(next(entry for entry in updated if entry.id == entry_id))
        return True

    def unarchive(self, entry_id: str) -> bool:
        entries = self.load(include_archived=True)
        found = False
        updated: list[HistoryEntry] = []
        for entry in entries:
            if entry.id != entry_id:
                updated.append(entry)
                continue
            found = True
            updated.append(
                HistoryEntry(
                    id=entry.id,
                    created_at=entry.created_at,
                    text=entry.text,
                    archived=False,
                    rev=entry.rev + 1,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        if not found:
            return False
        self._save(updated)
        self._enqueue_entry(next(entry for entry in updated if entry.id == entry_id))
        return True

    def append(self, text: str) -> HistoryEntry:
        now = datetime.now(timezone.utc).isoformat()
        entry = HistoryEntry(
            id=f"{now}-{uuid.uuid4().hex}",
            created_at=now,
            text=text,
            updated_at=now,
        )
        entries = [entry, *self.load(include_archived=True)][:MAX_ENTRIES]
        self._save(entries)
        self._enqueue_entry(entry)
        return entry

    def apply_synced_entry(self, payload: dict[str, Any], *, deleted: bool = False) -> bool:
        entry_id = payload.get("id")
        created_at = payload.get("created_at")
        text = payload.get("text")
        if not isinstance(entry_id, str) or not isinstance(created_at, str) or not isinstance(text, str):
            return False
        incoming = HistoryEntry(
            id=entry_id,
            created_at=created_at,
            text=text,
            archived=bool(payload.get("archived", False) or deleted),
            rev=_positive_int(payload.get("rev"), 1),
            updated_at=_optional_str(payload.get("updated_at")) or created_at,
        )
        entries = self.load(include_archived=True)
        replaced = False
        merged: list[HistoryEntry] = []
        for entry in entries:
            if entry.id != incoming.id:
                merged.append(entry)
                continue
            replaced = True
            merged.append(_newer_history_entry(incoming, entry))
        if not replaced:
            merged.insert(0, incoming)
        merged.sort(key=lambda item: item.created_at, reverse=True)
        self._save(merged[:MAX_ENTRIES])
        return True

    def _save(self, entries: list[HistoryEntry]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "entries": [asdict(e) for e in entries],
        }
        content = json.dumps(data, indent=2)
        # Atomic write: write to temp file then replace.
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._path.parent,
            suffix=".tmp",
            delete=False,
        )
        try:
            fd.write(content)
            fd.flush()
            fd.close()
            Path(fd.name).replace(self._path)
        except Exception:
            try:
                Path(fd.name).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            raise

    def _enqueue_entry(self, entry: HistoryEntry) -> None:
        if self._sync_outbox is None:
            return
        self._sync_outbox.enqueue(
            collection="history",
            record_id=entry.id,
            rev=entry.rev,
            updated_at=entry.updated_at or entry.created_at,
            content_type="application/vnd.dictate.history+json;v=1",
            payload=asdict(entry),
        )


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _newer_history_entry(left: HistoryEntry, right: HistoryEntry) -> HistoryEntry:
    left_key = (left.rev, left.updated_at or left.created_at, left.id)
    right_key = (right.rev, right.updated_at or right.created_at, right.id)
    return left if left_key >= right_key else right
