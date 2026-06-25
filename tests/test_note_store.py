from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dictate.note_store import NoteSegment, NoteStore


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
