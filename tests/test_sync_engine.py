from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from dictate.history import HistoryStore
from dictate.note_store import NoteSegment, NoteStore
from dictate.sync import PlainSyncRecord, SyncSettingsStore, encrypt_record, generate_account_key
from dictate.sync_engine import SyncEngine


class _FakeProClient:
    def __init__(self, records=None) -> None:
        self.records = list(records or [])
        self.drained = False
        self.changes_since: list[int] = []

    def drain_sync_outbox(self, outbox):  # noqa: ANN001
        self.drained = True
        pending = outbox.pending()
        outbox.replace_pending([])
        return {"pushed": len(pending), "remaining": 0, "results": []}

    def get_sync_changes(self, *, since: int = 0, limit: int = 500):
        self.changes_since.append(since)
        return {"next_seq": self.records[-1]["seq"] if self.records else since, "records": self.records}


class SyncEngineTests(unittest.TestCase):
    def _settings(self, tmp: str, account_id: str, key: bytes) -> SyncSettingsStore:
        saved: dict[str, str] = {}
        store = SyncSettingsStore(
            path=Path(tmp) / "state.json",
            device_path=Path(tmp) / "device.json",
            outbox_path=Path(tmp) / "outbox.jsonl",
            save_key=lambda account, encoded: saved.__setitem__(account, encoded),
            read_key=lambda account: saved.get(account),
            clear_key=lambda account: saved.pop(account, None),
        )
        store.enable(account_id, account_key=key)
        return store

    def test_disabled_sync_detaches_outboxes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SyncSettingsStore(path=Path(tmp) / "state.json", device_path=Path(tmp) / "device.json")
            history = HistoryStore(Path(tmp) / "history.json")
            notes = NoteStore(Path(tmp) / "notes")
            engine = SyncEngine(settings=settings, pro_client=_FakeProClient(), history_store=history, note_store=notes)

            result = engine.run_once()

            self.assertFalse(result.enabled)
            self.assertIsNone(history._sync_outbox)
            self.assertIsNone(notes._sync_outbox)

    def test_pull_applies_history_and_advances_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            record = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="history",
                    record_id="hist_1",
                    rev=1,
                    updated_at="2026-07-05T12:00:00+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.history+json;v=1",
                    payload={
                        "id": "hist_1",
                        "created_at": "2026-07-05T12:00:00+00:00",
                        "updated_at": "2026-07-05T12:00:00+00:00",
                        "rev": 1,
                        "text": "synced private note",
                        "archived": False,
                    },
                ),
            )
            changes = [{**asdict(record), "seq": 11}]
            settings = self._settings(tmp, account_id, key)
            history = HistoryStore(Path(tmp) / "history.json")
            notes = NoteStore(Path(tmp) / "notes")
            engine = SyncEngine(
                settings=settings,
                pro_client=_FakeProClient(changes),
                history_store=history,
                note_store=notes,
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 1)
            self.assertEqual(settings.load().last_seq, 11)
            self.assertEqual(history.load()[0].text, "synced private note")

    def test_pull_applies_note_and_segment_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            note = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="note",
                    record_id="note_1",
                    rev=1,
                    updated_at="2026-07-05T12:00:00+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.note+json;v=1",
                    payload={
                        "note_id": "note_1",
                        "mode": "meeting",
                        "provider": "parakeet",
                        "model": "parakeet-tdt-0.6b-v2",
                        "started_at": "2026-07-05T12:00:00+00:00",
                        "ended_at": "2026-07-05T12:00:10+00:00",
                        "duration_s": 10.0,
                        "status": "ready",
                        "speaker_labels": True,
                        "archived": False,
                    },
                ),
            )
            segment = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="segment",
                    record_id="note_1:0",
                    rev=1,
                    updated_at="2026-07-05T12:00:01+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.segment+json;v=1",
                    payload={
                        "note_id": "note_1",
                        "seq": 0,
                        "t_start": 0.0,
                        "t_end": 1.0,
                        "provider": "parakeet",
                        "model": "parakeet-tdt-0.6b-v2",
                        "text": "hello",
                        "speaker_label": "Speaker 1",
                    },
                ),
            )
            settings = self._settings(tmp, account_id, key)
            notes = NoteStore(Path(tmp) / "notes")
            engine = SyncEngine(
                settings=settings,
                pro_client=_FakeProClient([{**asdict(note), "seq": 1}, {**asdict(segment), "seq": 2}]),
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=notes,
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 2)
            self.assertEqual(notes.assembled_text("note_1"), "Speaker 1: hello")

    def test_push_drains_local_outbox_before_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            settings = self._settings(tmp, "acct_1", key)
            outbox = settings.outbox()
            assert outbox is not None
            outbox.enqueue(
                collection="history",
                record_id="hist_1",
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"id": "hist_1", "text": "private"},
            )
            client = _FakeProClient()
            engine = SyncEngine(
                settings=settings,
                pro_client=client,
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=NoteStore(Path(tmp) / "notes"),
            )

            result = engine.run_once()

            self.assertTrue(client.drained)
            self.assertEqual(result.pushed, 1)
            self.assertEqual(outbox.pending(), [])


if __name__ == "__main__":
    unittest.main()
