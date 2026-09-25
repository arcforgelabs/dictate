"""Durable on-disk store for long-form note recordings."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from dictate.platform_paths import user_data_dir

NOTES_ROOT = user_data_dir() / "notes"
NoteStatus = Literal["recording", "processing", "ready", "failed", "interrupted"]

# Locally generated ids are always `note_<uuid4 hex>` (see NoteStore.create_note),
# but synced note ids arrive from peers over the wire and are joined directly into
# a filesystem path. Restrict them to a conservative "plain filename" character
# class and reject Windows reserved device names, before the id ever reaches disk.
# This rules out path traversal (`note_..\..\evil`, `../x`), Windows reserved
# device names (`CON`, `NUL`), and separator injection (`a/b`, `a:b`).
_NOTE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _is_safe_note_id(note_id: str) -> bool:
    """True if note_id is safe to join into a filesystem path unescaped."""
    if not _NOTE_ID_PATTERN.fullmatch(note_id):
        return False
    # _NOTE_ID_PATTERN already excludes "." entirely, so note_id can never
    # actually contain a dot here -- this split is a no-op today. It's kept as
    # belt-and-braces in case the character class is ever loosened to allow
    # dots, since Windows reserved device names are reserved even with a
    # trailing extension (e.g. "CON.txt").
    stem = note_id.split(".", 1)[0]
    return stem.upper() not in _WINDOWS_RESERVED_NAMES


@dataclass(slots=True)
class NoteRecord:
    note_id: str
    mode: str
    provider: str
    model: str
    started_at: str
    ended_at: str | None
    duration_s: float | None
    status: NoteStatus
    speaker_labels: bool
    archived: bool = False
    recording_id: int | None = None
    error: str | None = None
    rev: int = 1
    updated_at: str | None = None


@dataclass(slots=True)
class NoteSegment:
    seq: int
    t_start: float
    t_end: float
    provider: str
    model: str
    text: str
    speaker_id: str | None = None
    speaker_label: str | None = None


class NoteStore:
    """Append-only segment log plus atomic note metadata."""

    def __init__(self, root: Path = NOTES_ROOT) -> None:
        self._root = root
        self._last_note_timestamp: datetime | None = None

    def create_note(
        self,
        *,
        provider: str,
        model: str,
        recording_id: int | None = None,
        speaker_labels: bool = False,
        mode: str = "note",
    ) -> str:
        note_id = f"note_{uuid.uuid4().hex}"
        started_at = self._next_timestamp().isoformat()
        record = NoteRecord(
            note_id=note_id,
            mode=mode,
            provider=provider,
            model=model,
            started_at=started_at,
            ended_at=None,
            duration_s=None,
            status="recording",
            speaker_labels=speaker_labels,
            recording_id=recording_id,
        )
        note_dir = self._note_dir(note_id)
        note_dir.mkdir(parents=True, exist_ok=True)
        (note_dir / "segments.jsonl").touch(exist_ok=True)
        self._write_note(record)
        return note_id

    def append_segment(self, note_id: str, segment: NoteSegment) -> None:
        note_dir = self._note_dir(note_id)
        note_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(segment), ensure_ascii=False)
        with (note_dir / "segments.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def load_note(self, note_id: str) -> NoteRecord | None:
        path = self._note_dir(note_id) / "note.json"
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(raw, dict):
            return None
        return NoteRecord(
            note_id=str(raw.get("note_id", note_id)),
            mode=str(raw.get("mode", "note")),
            provider=str(raw.get("provider", "")),
            model=str(raw.get("model", "")),
            started_at=str(raw.get("started_at", "")),
            ended_at=raw.get("ended_at"),
            duration_s=raw.get("duration_s"),
            status=raw.get("status", "recording"),
            speaker_labels=bool(raw.get("speaker_labels", False)),
            archived=bool(raw.get("archived", False)),
            recording_id=raw.get("recording_id"),
            error=raw.get("error"),
            rev=_positive_int(raw.get("rev"), 1),
            updated_at=_optional_str(raw.get("updated_at")),
        )

    def list_notes(self, *, limit: int = 50, include_archived: bool = False) -> list[NoteRecord]:
        if not self._root.is_dir():
            return []
        notes: list[NoteRecord] = []
        for note_dir in self._root.iterdir():
            if not note_dir.is_dir():
                continue
            note = self.load_note(note_dir.name)
            if note is None:
                continue
            if note.archived and not include_archived:
                continue
            notes.append(note)
        notes.sort(key=_note_sort_key, reverse=True)
        return notes[: max(0, limit)]

    def archive_note(self, note_id: str) -> bool:
        if not _is_safe_note_id(note_id):
            return False
        record = self.load_note(note_id)
        if record is None:
            return False
        if not record.archived:
            self._update_note(note_id, archived=True)
        return True

    def unarchive_note(self, note_id: str) -> bool:
        if not _is_safe_note_id(note_id):
            return False
        record = self.load_note(note_id)
        if record is None:
            return False
        if record.archived:
            self._update_note(note_id, archived=False)
        return True

    def delete_note(self, note_id: str) -> bool:
        if not _is_safe_note_id(note_id):
            return False
        note_dir = self._note_dir(note_id)
        if not note_dir.is_dir():
            return False
        shutil.rmtree(note_dir)
        return True

    def load_segments(self, note_id: str) -> list[NoteSegment]:
        path = self._note_dir(note_id) / "segments.jsonl"
        if not path.is_file():
            return []
        segments: list[NoteSegment] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            text = raw.get("text")
            if not isinstance(text, str):
                continue
            segments.append(
                NoteSegment(
                    seq=int(raw.get("seq", len(segments))),
                    t_start=float(raw.get("t_start", 0.0)),
                    t_end=float(raw.get("t_end", 0.0)),
                    provider=str(raw.get("provider", "")),
                    model=str(raw.get("model", "")),
                    text=text,
                    speaker_id=_optional_str(raw.get("speaker_id")),
                    speaker_label=_optional_str(raw.get("speaker_label")),
                )
            )
        segments.sort(key=lambda item: item.seq)
        return segments

    def assembled_text(self, note_id: str) -> str:
        segments = self.load_segments(note_id)
        if any(segment.speaker_label or segment.speaker_id for segment in segments):
            parts = _speaker_grouped_parts(segments)
        else:
            parts = [segment.text.strip() for segment in segments]
        return " ".join(part for part in parts if part)

    def mark_processing(self, note_id: str) -> None:
        self._update_note(note_id, status="processing")

    def mark_ready(self, note_id: str, *, duration_s: float | None = None) -> None:
        ended_at = datetime.now(timezone.utc).isoformat()
        self._update_note(note_id, status="ready", ended_at=ended_at, duration_s=duration_s)

    def mark_failed(self, note_id: str, *, error: str | None = None) -> None:
        ended_at = datetime.now(timezone.utc).isoformat()
        self._update_note(note_id, status="failed", ended_at=ended_at, error=error)

    def mark_interrupted(self, note_id: str) -> None:
        ended_at = datetime.now(timezone.utc).isoformat()
        self._update_note(note_id, status="interrupted", ended_at=ended_at)

    def recover_interrupted(self) -> list[str]:
        """Mark stale in-flight notes as interrupted after a crash."""
        if not self._root.is_dir():
            return []
        recovered: list[str] = []
        for note_dir in sorted(self._root.iterdir()):
            if not note_dir.is_dir():
                continue
            note = self.load_note(note_dir.name)
            if note is None:
                continue
            if note.status in {"recording", "processing"}:
                self.mark_interrupted(note.note_id)
                if self.assembled_text(note.note_id):
                    recovered.append(note.note_id)
        return recovered

    def _update_note(self, note_id: str, **changes: object) -> None:
        record = self.load_note(note_id)
        if record is None:
            return
        data = asdict(record)
        data.update(changes)
        data["rev"] = record.rev + 1
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_note(NoteRecord(**data))

    def _write_note(self, record: NoteRecord) -> None:
        note_dir = self._note_dir(record.note_id)
        note_dir.mkdir(parents=True, exist_ok=True)
        path = note_dir / "note.json"
        payload = json.dumps(asdict(record), indent=2)
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=note_dir,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            fd.write(payload)
            fd.flush()
            fd.close()
            Path(fd.name).replace(path)
        except Exception:
            try:
                Path(fd.name).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            raise

    def _note_dir(self, note_id: str) -> Path:
        # Defense-in-depth backstop: every external boundary
        # apply_synced_segment, delete_note, archive_note, unarchive_note)
        # already validates note_id and returns early before reaching here, and
        # every internal caller only ever passes a locally-generated
        # `note_<uuid4 hex>` id or one round-tripped from a disk-enumerated,
        # already-validated note directory. This raise should never fire in
        # normal operation -- it exists so a FUTURE caller that forgets to
        # validate a wire-sourced id can't silently reopen the path-traversal
        # hole by joining it straight into a filesystem path here.
        if not _is_safe_note_id(note_id):
            raise ValueError(f"unsafe note id: {note_id!r}")
        return self._root / note_id

    def _next_timestamp(self) -> datetime:
        now = datetime.now(timezone.utc)
        if self._last_note_timestamp is not None and now <= self._last_note_timestamp:
            now = self._last_note_timestamp + timedelta(microseconds=1)
        self._last_note_timestamp = now
        return now


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _note_sort_tuple(note: NoteRecord) -> tuple[int, str, str]:
    return (note.rev, note.updated_at or note.ended_at or note.started_at, note.note_id)


def _note_sort_key(note: NoteRecord) -> str:
    # Order by when the note was spoken. ended_at is a completion stamp, and
    # recover_interrupted writes the same stamp onto every stale note, which
    # would otherwise float old recordings above anything said since.
    return note.started_at or note.ended_at or ""


def _segment_display_text(segment: NoteSegment) -> str:
    text = segment.text.strip()
    if not text:
        return ""
    label = segment.speaker_label or segment.speaker_id
    return f"{label}: {text}" if label else text


def _speaker_grouped_parts(segments: list[NoteSegment]) -> list[str]:
    grouped: list[str] = []
    current_label: str | None = None
    current_parts: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        label = segment.speaker_label or segment.speaker_id
        if label != current_label and current_parts:
            grouped.append(_speaker_line(current_label, current_parts))
            current_parts = []
        current_label = label
        current_parts.append(text)
    if current_parts:
        grouped.append(_speaker_line(current_label, current_parts))
    return grouped


def _speaker_line(label: str | None, parts: list[str]) -> str:
    text = " ".join(part.strip() for part in parts if part.strip()).strip()
    return f"{label}: {text}" if label else text
