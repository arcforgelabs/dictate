#!/usr/bin/env python3
"""Realistic encrypted cloud-sync volume smoke for Dictate Pro."""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dictate.history import HistoryStore
from dictate.note_store import NoteSegment, NoteStore
from dictate.sync import EncryptedSyncRecord, SyncSettingsStore, generate_account_key
from dictate.sync_engine import SyncEngine


ACCOUNT_ID = "acct_volume_smoke"
NOTE_COUNT = 12
SEGMENTS_PER_NOTE = 30
HISTORY_COUNT = 20
EXPECTED_NOTE_RECORDS = NOTE_COUNT * 2
EXPECTED_SEGMENT_RECORDS = NOTE_COUNT * SEGMENTS_PER_NOTE
EXPECTED_HISTORY_RECORDS = HISTORY_COUNT


class SharedCloudClient:
    """Tiny in-memory gateway stand-in that only stores encrypted records."""

    def __init__(self, cloud: list[dict[str, Any]]) -> None:
        self.cloud = cloud
        self.cursor_updates: list[int] = []

    def drain_sync_outbox(self, outbox: Any) -> dict[str, Any]:
        pending: list[EncryptedSyncRecord] = outbox.pending()
        for record in pending:
            self.cloud.append({**asdict(record), "seq": len(self.cloud) + 1})
        outbox.replace_pending([])
        return {"pushed": len(pending), "remaining": 0, "results": []}

    def get_sync_changes(self, *, since: int = 0, limit: int = 500) -> dict[str, Any]:
        records = [record for record in self.cloud if int(record["seq"]) > since][:limit]
        next_seq = int(records[-1]["seq"]) if records else since
        return {"next_seq": next_seq, "records": records}

    def update_sync_cursor(self, *, last_seq: int) -> dict[str, int]:
        self.cursor_updates.append(last_seq)
        return {"last_seq": last_seq}


def run_smoke(root: Path | None = None) -> dict[str, Any]:
    """Run the local two-device volume smoke and return timing/count evidence."""
    if root is None:
        with tempfile.TemporaryDirectory() as tmp:
            return _run_smoke(Path(tmp))
    root.mkdir(parents=True, exist_ok=True)
    return _run_smoke(root)


def _run_smoke(root: Path) -> dict[str, Any]:
    account_key = generate_account_key()
    cloud: list[dict[str, Any]] = []
    source = _make_device(root / "source", account_key, "device_volume_source", cloud)
    target = _make_device(root / "target", account_key, "device_volume_target", cloud)

    source["engine"].attach_outbox()
    sentinels = _populate_source(source["history"], source["notes"])

    started = time.perf_counter()
    push_result = source["engine"].run_once(limit=1_000)
    pull_result = target["engine"].run_once(limit=1_000)
    idempotent_result = target["engine"].run_once(limit=1_000)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    if push_result.error:
        raise AssertionError(f"source push failed: {push_result.error}")
    if pull_result.error:
        raise AssertionError(f"target pull failed: {pull_result.error}")
    if idempotent_result.error:
        raise AssertionError(f"idempotent pull failed: {idempotent_result.error}")
    if push_result.remaining != 0:
        raise AssertionError(f"source outbox still has {push_result.remaining} records")
    if push_result.pushed != len(cloud):
        raise AssertionError(f"pushed {push_result.pushed} records but cloud has {len(cloud)}")
    expected_records = EXPECTED_NOTE_RECORDS + EXPECTED_SEGMENT_RECORDS + EXPECTED_HISTORY_RECORDS
    if len(cloud) != expected_records:
        raise AssertionError(f"expected {expected_records} encrypted records, got {len(cloud)}")
    if pull_result.pulled != expected_records or pull_result.applied != expected_records:
        raise AssertionError(
            f"target applied {pull_result.applied}/{pull_result.pulled}; expected {expected_records}"
        )
    if idempotent_result.pulled != 0 or idempotent_result.applied != 0:
        raise AssertionError("second target sync should be idempotent")

    target_notes = target["notes"].list_notes(limit=1_000, include_archived=True)
    if len(target_notes) != NOTE_COUNT:
        raise AssertionError(f"expected {NOTE_COUNT} target notes, got {len(target_notes)}")
    target_segments = sum(len(target["notes"].load_segments(note.note_id)) for note in target_notes)
    if target_segments != EXPECTED_SEGMENT_RECORDS:
        raise AssertionError(f"expected {EXPECTED_SEGMENT_RECORDS} target segments, got {target_segments}")
    target_history = target["history"].load(include_archived=True)
    if len(target_history) != HISTORY_COUNT:
        raise AssertionError(f"expected {HISTORY_COUNT} target history entries, got {len(target_history)}")

    serialized_cloud = json.dumps(cloud, sort_keys=True)
    serialized_outbox = (root / "source" / "outbox.jsonl").read_text(encoding="utf-8")
    for sentinel in sentinels:
        if sentinel in serialized_cloud:
            raise AssertionError(f"plaintext sentinel leaked to cloud: {sentinel}")
        if sentinel in serialized_outbox:
            raise AssertionError(f"plaintext sentinel leaked to local encrypted outbox: {sentinel}")

    return {
        "records": len(cloud),
        "notes": len(target_notes),
        "segments": target_segments,
        "history": len(target_history),
        "elapsed_ms": elapsed_ms,
        "last_seq": target["settings"].load().last_seq,
    }


def _make_device(
    root: Path,
    account_key: bytes,
    device_id: str,
    cloud: list[dict[str, Any]],
) -> dict[str, Any]:
    secrets: dict[str, str] = {}
    root.mkdir(parents=True, exist_ok=True)
    settings = SyncSettingsStore(
        path=root / "sync-state.json",
        device_path=root / "sync-device.json",
        outbox_path=root / "outbox.jsonl",
        save_key=lambda account, encoded: secrets.__setitem__(account, encoded),
        read_key=lambda account: secrets.get(account),
        clear_key=lambda account: secrets.pop(account, None),
    )
    settings.enable(ACCOUNT_ID, account_key=account_key, device_id=device_id)
    history = HistoryStore(root / "recent-history.json")
    notes = NoteStore(root / "notes")
    engine = SyncEngine(
        settings=settings,
        pro_client=SharedCloudClient(cloud),
        history_store=history,
        note_store=notes,
    )
    return {"settings": settings, "history": history, "notes": notes, "engine": engine}


def _populate_source(history: HistoryStore, notes: NoteStore) -> list[str]:
    sentinels: list[str] = []
    for index in range(HISTORY_COUNT):
        text = f"volume smoke private history {index:02d}"
        sentinels.append(text)
        history.append(text)

    for note_index in range(NOTE_COUNT):
        note_id = notes.create_note(
            provider="parakeet",
            model="parakeet-tdt-0.6b-v2",
            speaker_labels=note_index % 2 == 0,
            mode="meeting" if note_index % 3 == 0 else "note",
        )
        for seq in range(SEGMENTS_PER_NOTE):
            text = f"volume smoke private segment note {note_index:02d} seq {seq:02d}"
            sentinels.append(text)
            notes.append_segment(
                note_id,
                NoteSegment(
                    seq=seq,
                    t_start=seq * 2.5,
                    t_end=(seq + 1) * 2.5,
                    provider="parakeet",
                    model="parakeet-tdt-0.6b-v2",
                    text=text,
                    speaker_id=f"speaker_{seq % 3}" if note_index % 2 == 0 else None,
                    speaker_label=f"Speaker {(seq % 3) + 1}" if note_index % 2 == 0 else None,
                ),
            )
        notes.mark_ready(note_id, duration_s=SEGMENTS_PER_NOTE * 2.5)
    return sentinels


def main() -> int:
    evidence = run_smoke()
    print(
        "cloud sync volume smoke passed: "
        f"{evidence['records']} encrypted records, "
        f"{evidence['notes']} notes, "
        f"{evidence['segments']} segments, "
        f"{evidence['history']} history entries, "
        f"{evidence['elapsed_ms']} ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
