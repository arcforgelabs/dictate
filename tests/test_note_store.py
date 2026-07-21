from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dictate.note_store import NoteSegment, NoteStore
from dictate.sync import SyncOutbox, decrypt_record, generate_account_key

UNSAFE_NOTE_IDS = [
    "note_..\\..\\evil",
    "../x",
    "CON",
    "con.txt",
    "NUL",
    "a/b",
    "a:b",
    "",
]


class NoteStoreTests(unittest.TestCase):
    def test_append_and_assemble_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="faster-whisper", model="turbo", recording_id=7)
            store.append_segment(
                note_id,
                NoteSegment(seq=0, t_start=0.0, t_end=12.0, provider="faster-whisper", model="turbo", text="hello"),
            )
            store.append_segment(
                note_id,
                NoteSegment(seq=1, t_start=12.0, t_end=24.0, provider="faster-whisper", model="turbo", text="world"),
            )
            self.assertEqual(store.assembled_text(note_id), "hello world")
            store.mark_ready(note_id, duration_s=24.0)
            note = store.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "ready")

    def test_speaker_segments_round_trip_and_assemble_with_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(
                provider="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                recording_id=8,
                speaker_labels=True,
                mode="meeting",
            )
            store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=1.0,
                    provider="parakeet-pyannote",
                    model="parakeet-tdt-0.6b-v2",
                    text="hello",
                    speaker_id="SPEAKER_A",
                    speaker_label="Speaker 1",
                ),
            )
            store.append_segment(
                note_id,
                NoteSegment(
                    seq=1,
                    t_start=1.0,
                    t_end=2.0,
                    provider="parakeet-pyannote",
                    model="parakeet-tdt-0.6b-v2",
                    text="reply",
                    speaker_id="SPEAKER_B",
                    speaker_label="Speaker 2",
                ),
            )

            note = store.load_note(note_id)
            assert note is not None
            self.assertEqual(note.mode, "meeting")
            self.assertTrue(note.speaker_labels)
            segments = store.load_segments(note_id)
            self.assertEqual(segments[0].speaker_id, "SPEAKER_A")
            self.assertEqual(segments[1].speaker_label, "Speaker 2")
            self.assertEqual(store.assembled_text(note_id), "Speaker 1: hello Speaker 2: reply")

    def test_list_notes_returns_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            first = store.create_note(provider="faster-whisper", model="turbo")
            second = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")

            notes = store.list_notes()

            self.assertEqual([note.note_id for note in notes], [second, first])

    def test_recover_interrupted_marks_stale_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="faster-whisper", model="turbo")
            store.append_segment(
                note_id,
                NoteSegment(seq=0, t_start=0.0, t_end=1.0, provider="faster-whisper", model="turbo", text="saved"),
            )
            recovered = store.recover_interrupted()
            self.assertIn(note_id, recovered)
            note = store.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "interrupted")

    def test_archive_note_hides_from_list_but_keeps_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="faster-whisper", model="turbo")
            store.mark_ready(note_id, duration_s=1.0)

            self.assertTrue(store.archive_note(note_id))
            self.assertEqual(store.list_notes(), [])
            self.assertEqual(store.list_notes(include_archived=True)[0].note_id, note_id)

            note = store.load_note(note_id)
            assert note is not None
            self.assertTrue(note.archived)

    def test_unarchive_note_restores_visible_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="faster-whisper", model="turbo")
            store.mark_ready(note_id, duration_s=1.0)
            self.assertTrue(store.archive_note(note_id))
            self.assertEqual(store.list_notes(), [])

            self.assertTrue(store.unarchive_note(note_id))
            notes = store.list_notes()
            self.assertEqual(len(notes), 1)
            note = store.load_note(note_id)
            assert note is not None
            self.assertFalse(note.archived)

    def test_delete_note_removes_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="faster-whisper", model="turbo")
            self.assertTrue(store.delete_note(note_id))
            self.assertIsNone(store.load_note(note_id))
            self.assertFalse(store.delete_note(note_id))

    def test_delete_note_rejects_unsafe_ids_without_touching_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_root = Path(tmp) / "notes"
            store = NoteStore(root=notes_root)
            for unsafe_id in UNSAFE_NOTE_IDS:
                self.assertFalse(store.delete_note(unsafe_id), unsafe_id)
            # Nothing should have been created outside (or inside) the store root.
            self.assertFalse(notes_root.exists())
            outside = Path(tmp) / "evil"
            self.assertFalse(outside.exists())

    def test_apply_synced_note_rejects_unsafe_ids_without_touching_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_root = Path(tmp) / "notes"
            store = NoteStore(root=notes_root)
            for unsafe_id in UNSAFE_NOTE_IDS:
                if not unsafe_id:
                    continue  # empty note_id is already rejected before path validation
                result = store.apply_synced_note(
                    {
                        "note_id": unsafe_id,
                        "mode": "note",
                        "provider": "faster-whisper",
                        "model": "turbo",
                        "started_at": "2026-01-01T00:00:00+00:00",
                        "status": "ready",
                    }
                )
                self.assertFalse(result, unsafe_id)
            self.assertFalse(notes_root.exists())
            outside = Path(tmp) / "evil"
            self.assertFalse(outside.exists())

    def test_apply_synced_segment_rejects_unsafe_ids_without_touching_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_root = Path(tmp) / "notes"
            store = NoteStore(root=notes_root)
            for unsafe_id in UNSAFE_NOTE_IDS:
                if not unsafe_id:
                    continue  # empty note_id is already rejected before path validation
                result = store.apply_synced_segment(
                    {
                        "note_id": unsafe_id,
                        "seq": 0,
                        "text": "hello",
                    }
                )
                self.assertFalse(result, unsafe_id)
            self.assertFalse(notes_root.exists())
            outside = Path(tmp) / "evil"
            self.assertFalse(outside.exists())

    def test_apply_synced_note_and_delete_still_work_for_legitimate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="faster-whisper", model="turbo")

            applied = store.apply_synced_note(
                {
                    "note_id": note_id,
                    "mode": "note",
                    "provider": "faster-whisper",
                    "model": "turbo",
                    "started_at": "2026-01-01T00:00:00+00:00",
                    "status": "ready",
                    "rev": 2,
                    "updated_at": "2026-01-01T00:01:00+00:00",
                }
            )
            self.assertTrue(applied)
            note = store.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "ready")

            segment_applied = store.apply_synced_segment(
                {"note_id": note_id, "seq": 0, "text": "hello from peer"}
            )
            self.assertTrue(segment_applied)
            self.assertEqual(store.assembled_text(note_id), "hello from peer")

            self.assertTrue(store.delete_note(note_id))
            self.assertIsNone(store.load_note(note_id))

    def test_note_and_segment_mutations_enqueue_encrypted_sync_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            outbox = SyncOutbox(
                path=Path(tmp) / "outbox.jsonl",
                account_id="acct_1",
                account_key=key,
                device_id="device_test",
            )
            store = NoteStore(root=Path(tmp) / "notes", sync_outbox=outbox)

            note_id = store.create_note(provider="faster-whisper", model="turbo")
            store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=1.0,
                    provider="faster-whisper",
                    model="turbo",
                    text="private note text",
                ),
            )
            store.mark_ready(note_id, duration_s=1.0)

            raw_outbox = (Path(tmp) / "outbox.jsonl").read_text()
            self.assertNotIn("private note text", raw_outbox)
            pending = outbox.pending()
            self.assertGreaterEqual(len(pending), 3)
            segment = next(record for record in pending if record.collection == "segment")
            self.assertEqual(segment.record_id, f"{note_id}:0")
            self.assertEqual(decrypt_record("acct_1", key, segment)["text"], "private note text")

    def test_sync_snapshot_enqueues_existing_local_notes_and_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2", mode="meeting")
            store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=1.0,
                    provider="parakeet",
                    model="parakeet-tdt-0.6b-v2",
                    text="private meeting segment",
                    speaker_id="speaker_1",
                    speaker_label="Speaker 1",
                ),
            )
            store.mark_ready(note_id, duration_s=1.0)
            outbox = SyncOutbox(
                path=Path(tmp) / "outbox.jsonl",
                account_id="acct_1",
                account_key=key,
                device_id="device_test",
            )
            store.attach_sync_outbox(outbox)

            self.assertEqual(store.enqueue_sync_snapshot(), 2)

            raw_outbox = (Path(tmp) / "outbox.jsonl").read_text()
            self.assertNotIn("private meeting segment", raw_outbox)
            pending = outbox.pending()
            self.assertEqual({record.collection for record in pending}, {"note", "segment"})
            note_record = next(record for record in pending if record.collection == "note")
            segment_record = next(record for record in pending if record.collection == "segment")
            self.assertEqual(note_record.record_id, note_id)
            self.assertFalse(note_record.deleted)
            self.assertEqual(decrypt_record("acct_1", key, note_record)["mode"], "meeting")
            self.assertEqual(segment_record.record_id, f"{note_id}:0")
            segment_payload = decrypt_record("acct_1", key, segment_record)
            self.assertEqual(segment_payload["text"], "private meeting segment")
            self.assertEqual(segment_payload["speaker_label"], "Speaker 1")

    def test_delete_note_enqueues_tombstone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            outbox = SyncOutbox(
                path=Path(tmp) / "outbox.jsonl",
                account_id="acct_1",
                account_key=key,
                device_id="device_test",
            )
            store = NoteStore(root=Path(tmp) / "notes", sync_outbox=outbox)
            note_id = store.create_note(provider="faster-whisper", model="turbo")

            self.assertTrue(store.delete_note(note_id))

            tombstone = outbox.pending()[-1]
            self.assertEqual(tombstone.collection, "note")
            self.assertEqual(tombstone.record_id, note_id)
            self.assertTrue(tombstone.deleted)
