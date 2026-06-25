from __future__ import annotations

import unittest

import numpy as np

from dictate.note_chunker import NoteChunkAccumulator


class NoteChunkAccumulatorTests(unittest.TestCase):
    def test_emits_after_silence_gap_when_min_duration_met(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=100,
            min_chunk_seconds=0.2,
            max_chunk_seconds=1.0,
            silence_gap_seconds=0.1,
            overlap_seconds=0.0,
            silence_rms=0.05,
        )
        speech = np.full(30, 0.5, dtype=np.float32)
        silence = np.zeros(12, dtype=np.float32)
        emitted = acc.push(speech)
        self.assertEqual(emitted, [])
        emitted = acc.push(silence)
        self.assertEqual(len(emitted), 1)
        self.assertGreaterEqual(emitted[0].samples.shape[0], 28)
        self.assertEqual(emitted[0].sequence, 0)

    def test_hard_cap_emits_when_no_silence(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=0.2,
            max_chunk_seconds=0.5,
            silence_gap_seconds=0.2,
            overlap_seconds=0.0,
            silence_rms=0.01,
        )
        emitted = acc.push(np.full(8, 0.8, dtype=np.float32))
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].samples.shape[0], 5)

    def test_flush_emits_remaining_audio(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=1.0,
            max_chunk_seconds=2.0,
            silence_gap_seconds=0.2,
            overlap_seconds=0.0,
            silence_rms=0.01,
        )
        acc.push(np.full(4, 0.8, dtype=np.float32))
        emitted = acc.flush(final=True)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].samples.shape[0], 4)

    def test_resume_offsets_continue_sequence_and_time(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=0.1,
            max_chunk_seconds=1.0,
            silence_gap_seconds=0.1,
            overlap_seconds=0.0,
            silence_rms=0.05,
            seq_offset=2,
            time_offset_s=1.5,
        )
        acc.push(np.full(4, 0.8, dtype=np.float32))
        emitted = acc.flush(final=True)
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].sequence, 2)
        self.assertEqual(emitted[0].t_start, 1.5)
        self.assertEqual(emitted[0].t_end, 1.9)
