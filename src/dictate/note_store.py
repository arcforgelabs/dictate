"""Durable on-disk store for long-form note recordings."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from dictate.platform_paths import user_data_dir
from dictate.sync import SyncOutbox

NOTES_ROOT = user_data_dir() / "notes"
NoteStatus = Literal["recording", "processing", "ready", "failed", "interrupted"]


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

    def __init__(self, root: Path = NOTES_ROOT, sync_outbox: SyncOutbox | None = None) -> None:
        self._root = root
        self._last_note_timestamp: datetime | None = None
        self._sync_outbox = sync_outbox

    def attach_sync_outbox(self, sync_outbox: SyncOutbox | None) -> None:
        self._sync_outbox = sync_outbox

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
        self._enqueue_segment(note_id, segment)

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
        record = self.load_note(note_id)
        if record is None:
            return False
        if not record.archived:
            self._update_note(note_id, archived=True)
        return True

    def unarchive_note(self, note_id: str) -> bool:
        record = self.load_note(note_id)
        if record is None:
            return False
        if record.archived:
            self._update_note(note_id, archived=False)
        return True

    def delete_note(self, note_id: str) -> bool:
        note_dir = self._note_dir(note_id)
        if not note_dir.is_dir():
            return False
        record = self.load_note(note_id)
        shutil.rmtree(note_dir)
        if record is not None:
            tombstone = NoteRecord(
                note_id=record.note_id,
                mode=record.mode,
                provider=record.provider,
                model=record.model,
                started_at=record.started_at,
                ended_at=record.ended_at,
                duration_s=record.duration_s,
                status=record.status,
                speaker_labels=record.speaker_labels,
                archived=record.archived,
                recording_id=record.recording_id,
                error=record.error,
                rev=record.rev + 1,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            self._enqueue_note(tombstone, deleted=True)
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

    def apply_synced_note(self, payload: dict[str, Any], *, deleted: bool = False) -> bool:
        note_id = payload.get("note_id")
        if not isinstance(note_id, str) or not note_id.strip():
            return False
        if deleted:
            shutil.rmtree(self._note_dir(note_id), ignore_errors=True)
            return True
        incoming = _note_from_payload(payload, fallback_note_id=note_id)
        if incoming is None:
            return False
        existing = self.load_note(note_id)
        if existing is not None and _note_sort_tuple(existing) > _note_sort_tuple(incoming):
            return True
        self._write_note(incoming, enqueue=False)
        return True

    def apply_synced_segment(self, payload: dict[str, Any], *, deleted: bool = False) -> bool:
        note_id = payload.get("note_id")
        if not isinstance(note_id, str) or not note_id.strip():
            return False
        try:
            seq = int(payload.get("seq"))
        except (TypeError, ValueError):
            return False
        note_dir = self._note_dir(note_id)
        note_dir.mkdir(parents=True, exist_ok=True)
        path = note_dir / "segments.jsonl"
        existing = [segment for segment in self.load_segments(note_id) if segment.seq != seq]
        if not deleted:
            text = payload.get("text")
            if not isinstance(text, str):
                return False
            existing.append(
                NoteSegment(
                    seq=seq,
                    t_start=float(payload.get("t_start", payload.get("tStart", 0.0))),
                    t_end=float(payload.get("t_end", payload.get("tEnd", 0.0))),
                    provider=str(payload.get("provider") or ""),
                    model=str(payload.get("model") or ""),
                    text=text,
                    speaker_id=_optional_str(payload.get("speaker_id", payload.get("speakerId"))),
                    speaker_label=_optional_str(payload.get("speaker_label", payload.get("speakerLabel"))),
                )
            )
        existing.sort(key=lambda segment: segment.seq)
        with path.open("w", encoding="utf-8") as handle:
            for segment in existing:
                handle.write(json.dumps(asdict(segment), ensure_ascii=False) + "\n")
        return True

    def _update_note(self, note_id: str, **changes: object) -> None:
        record = self.load_note(note_id)
        if record is None:
            return
        data = asdict(record)
        data.update(changes)
        data["rev"] = record.rev + 1
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_note(NoteRecord(**data))

    def _write_note(self, record: NoteRecord, *, enqueue: bool = True) -> None:
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
        if enqueue:
            self._enqueue_note(record)

    def _note_dir(self, note_id: str) -> Path:
        return self._root / note_id

    def _next_timestamp(self) -> datetime:
        now = datetime.now(timezone.utc)
        if self._last_note_timestamp is not None and now <= self._last_note_timestamp:
            now = self._last_note_timestamp + timedelta(microseconds=1)
        self._last_note_timestamp = now
        return now

    def _enqueue_note(self, record: NoteRecord, *, deleted: bool = False) -> None:
        if self._sync_outbox is None:
            return
        self._sync_outbox.enqueue(
            collection="note",
            record_id=record.note_id,
            rev=record.rev,
            updated_at=record.updated_at or record.ended_at or record.started_at,
            deleted=deleted,
            content_type="application/vnd.dictate.note+json;v=1",
            payload=asdict(record),
        )

    def _enqueue_segment(self, note_id: str, segment: NoteSegment) -> None:
        if self._sync_outbox is None:
            return
        self._sync_outbox.enqueue(
            collection="segment",
            record_id=f"{note_id}:{segment.seq}",
            rev=1,
            content_type="application/vnd.dictate.segment+json;v=1",
            payload={"note_id": note_id, **asdict(segment)},
        )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _note_from_payload(payload: dict[str, Any], *, fallback_note_id: str) -> NoteRecord | None:
    try:
        return NoteRecord(
            note_id=str(payload.get("note_id") or fallback_note_id),
            mode=str(payload.get("mode") or "note"),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            started_at=str(payload.get("started_at") or payload.get("startedAt") or ""),
            ended_at=_optional_str(payload.get("ended_at", payload.get("endedAt"))),
            duration_s=payload.get("duration_s", payload.get("durationSeconds")),
            status=payload.get("status") or "ready",
            speaker_labels=bool(payload.get("speaker_labels", payload.get("speakerLabels", False))),
            archived=bool(payload.get("archived", False)),
            recording_id=payload.get("recording_id", payload.get("recordingId")),
            error=_optional_str(payload.get("error")),
            rev=_positive_int(payload.get("rev"), 1),
            updated_at=_optional_str(payload.get("updated_at", payload.get("updatedAt"))),
        )
    except (TypeError, ValueError):
        return None


def _note_sort_tuple(note: NoteRecord) -> tuple[int, str, str]:
    return (note.rev, note.updated_at or note.ended_at or note.started_at, note.note_id)


def _note_sort_key(note: NoteRecord) -> str:
    return note.ended_at or note.started_at or ""


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
