from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dictate.note_store import NoteSegment, NoteStore

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
            note_id = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2", recording_id=7)
            store.append_segment(
                note_id,
                NoteSegment(seq=0, t_start=0.0, t_end=12.0, provider="parakeet", model="parakeet-tdt-0.6b-v2", text="hello"),
            )
            store.append_segment(
                note_id,
                NoteSegment(seq=1, t_start=12.0, t_end=24.0, provider="parakeet", model="parakeet-tdt-0.6b-v2", text="world"),
            )
            self.assertEqual(store.assembled_text(note_id), "hello world")
            store.mark_ready(note_id, duration_s=24.0)
            note = store.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "ready")
            self.assertEqual(note.mode, "note")
            self.assertFalse(note.speaker_labels)

    def test_meeting_transcript_saved_before_removal_stays_readable(self) -> None:
        # Meeting capture was removed (#140). These are the files it left
        # under notes/ in 2026.9.27, byte for byte in shape: an upgrade must
        # list them, read them with their speaker labels, and never drop them.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "notes"
            note_dir = root / "note_0123456789abcdef0123456789abcdef"
            note_dir.mkdir(parents=True)
            (note_dir / "note.json").write_text(
                json.dumps(
                    {
                        "note_id": note_dir.name,
                        "mode": "meeting",
                        "provider": "parakeet-pyannote",
                        "model": "parakeet-tdt-0.6b-v2+pyannote/speaker-diarization-community-1",
                        "started_at": "2026-09-30T01:00:00+00:00",
                        "ended_at": "2026-09-30T01:05:00+00:00",
                        "duration_s": None,
                        "status": "ready",
                        "speaker_labels": True,
                        "archived": False,
                        "recording_id": 8,
                        "error": None,
                        "rev": 3,
                        "updated_at": "2026-09-30T01:05:00+00:00",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            segment = {
                "provider": "parakeet-pyannote",
                "model": "parakeet-tdt-0.6b-v2+pyannote/speaker-diarization-community-1",
            }
            (note_dir / "segments.jsonl").write_text(
                json.dumps(
                    {
                        "seq": 0, "t_start": 0.0, "t_end": 1.0, **segment, "text": "hello",
                        "speaker_id": "SPEAKER_00", "speaker_label": "Speaker 1",
                    }
                )
                + "\n"
                + json.dumps(
                    {
                        "seq": 1, "t_start": 1.0, "t_end": 2.0, **segment, "text": "reply",
                        "speaker_id": "SPEAKER_01", "speaker_label": "Speaker 2",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            store = NoteStore(root=root)

            self.assertEqual(store.recover_interrupted(), [])
            notes = store.list_notes()
            self.assertEqual([note.note_id for note in notes], [note_dir.name])
            note = notes[0]
            self.assertEqual(note.mode, "meeting")
            self.assertTrue(note.speaker_labels)
            self.assertEqual(note.status, "ready")
            segments = store.load_segments(note.note_id)
            self.assertEqual(segments[0].speaker_id, "SPEAKER_00")
            self.assertEqual(segments[1].speaker_label, "Speaker 2")
            self.assertEqual(segments[1].t_end, 2.0)
            self.assertEqual(store.assembled_text(note.note_id), "Speaker 1: hello Speaker 2: reply")
            self.assertTrue(store.archive_note(note.note_id))
            self.assertTrue(store.unarchive_note(note.note_id))
            self.assertTrue((note_dir / "segments.jsonl").is_file())

    def test_list_notes_returns_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            first = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
            second = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")

            notes = store.list_notes()

            self.assertEqual([note.note_id for note in notes], [second, first])

    def test_recover_interrupted_marks_stale_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
            store.append_segment(
                note_id,
                NoteSegment(seq=0, t_start=0.0, t_end=1.0, provider="parakeet", model="parakeet-tdt-0.6b-v2", text="saved"),
            )
            recovered = store.recover_interrupted()
            self.assertIn(note_id, recovered)
            note = store.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "interrupted")

    def test_archive_note_hides_from_list_but_keeps_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
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
            note_id = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
            store.mark_ready(note_id, duration_s=1.0)
            self.assertTrue(store.archive_note(note_id))
            self.assertEqual(store.list_notes(), [])

            self.assertTrue(store.unarchive_note(note_id))
            notes = store.list_notes()
            self.assertEqual(len(notes), 1)
            note = store.load_note(note_id)
            assert note is not None
            self.assertFalse(note.archived)

    def test_archive_and_unarchive_reject_unsafe_ids_without_touching_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_root = Path(tmp) / "notes"
            store = NoteStore(root=notes_root)
            for unsafe_id in UNSAFE_NOTE_IDS:
                self.assertFalse(store.archive_note(unsafe_id), unsafe_id)
                self.assertFalse(store.unarchive_note(unsafe_id), unsafe_id)
            self.assertFalse(notes_root.exists())
            outside = Path(tmp) / "evil"
            self.assertFalse(outside.exists())

    def test_note_dir_raises_on_unsafe_id_as_a_structural_backstop(self) -> None:
        """_note_dir is the single chokepoint every method joins note_id through.

        The external boundaries (delete_note, archive_note, unarchive_note)
        already validate and return early before reaching _note_dir. This test
        guards the chokepoint itself, so a FUTURE caller that forgets to
        validate an externally-sourced id can't silently reopen the
        path-traversal hole.
        """
        with tempfile.TemporaryDirectory() as tmp:
            notes_root = Path(tmp) / "notes"
            store = NoteStore(root=notes_root)
            for unsafe_id in UNSAFE_NOTE_IDS:
                with self.subTest(unsafe_id=unsafe_id):
                    with self.assertRaises(ValueError):
                        store._note_dir(unsafe_id)
            self.assertFalse(notes_root.exists())

    def test_archive_and_unarchive_still_work_for_legitimate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
            store.mark_ready(note_id, duration_s=1.0)

            self.assertTrue(store.archive_note(note_id))
            note = store.load_note(note_id)
            assert note is not None
            self.assertTrue(note.archived)

            self.assertTrue(store.unarchive_note(note_id))
            note = store.load_note(note_id)
            assert note is not None
            self.assertFalse(note.archived)

    def test_delete_note_removes_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = NoteStore(root=Path(tmp) / "notes")
            note_id = store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
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
