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
