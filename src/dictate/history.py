"""Persistent rolling history of recent successful dictations."""

from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from dictate.platform_paths import user_data_dir

MAX_ENTRIES = 20
HISTORY_PATH = user_data_dir() / "recent-history.json"


@dataclass(slots=True)
class HistoryEntry:
    id: str
    created_at: str
    text: str


class HistoryStore:
    """Thread-safe rolling buffer of recent dictation texts, persisted to JSON."""

    def __init__(self, path: Path = HISTORY_PATH) -> None:
        self._path = path

    def load(self) -> list[HistoryEntry]:
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
                entries.append(HistoryEntry(id=entry_id, created_at=created_at, text=text))
        return entries[:MAX_ENTRIES]

    def append(self, text: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        entry = HistoryEntry(id=f"{now}-{uuid.uuid4().hex}", created_at=now, text=text)
        entries = [entry, *self.load()][:MAX_ENTRIES]
        self._save(entries)

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
