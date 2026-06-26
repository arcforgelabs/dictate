from __future__ import annotations

import threading
import unittest

import numpy as np

from dictate.note_chunker import NoteChunkAccumulator


class NoteChunkAccumulatorTests(unittest.TestCase):
    def test_default_note_chunks_emit_before_short_note_finishes(self) -> None:
        acc = NoteChunkAccumulator(sample_rate=10, silence_rms=0.01)

        emitted = acc.push(np.ones(60, dtype=np.float32))

        self.assertEqual(len(emitted), 1)
        self.assertAlmostEqual(emitted[0].t_start, 0.0)
        self.assertAlmostEqual(emitted[0].t_end, 6.0)

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

    def test_final_flush_with_default_overlap_returns_once(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=1.0,
            max_chunk_seconds=2.0,
            silence_gap_seconds=0.2,
            silence_rms=0.01,
        )
        acc.push(np.full(3, 0.8, dtype=np.float32))

        result: list[list[object]] = []

        def _flush() -> None:
            result.append(acc.flush(final=True))

        thread = threading.Thread(target=_flush)
        thread.start()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 1)
        self.assertEqual(result[0][0].samples.shape[0], 3)
        self.assertEqual(acc.pending_samples, 0)

    def test_final_flush_skips_overlap_only_buffer(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=0.1,
            max_chunk_seconds=0.5,
            silence_gap_seconds=0.2,
            overlap_seconds=0.2,
            silence_rms=0.01,
        )
        acc.push(np.full(5, 0.8, dtype=np.float32))

        emitted = acc.flush(final=True)

        self.assertEqual(emitted, [])
        self.assertEqual(acc.pending_samples, 0)

    def test_final_flush_emits_tail_after_overlap_buffer(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=0.1,
            max_chunk_seconds=0.5,
            silence_gap_seconds=0.2,
            overlap_seconds=0.2,
            silence_rms=0.01,
        )
        acc.push(np.full(5, 0.8, dtype=np.float32))
        acc.push(np.full(2, 0.8, dtype=np.float32))

        emitted = acc.flush(final=True)

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].samples.shape[0], 4)
        self.assertEqual(acc.pending_samples, 0)

    def test_push_with_silence_split_returns_promptly(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=0.1,
            max_chunk_seconds=1.0,
            silence_gap_seconds=0.2,
            overlap_seconds=0.2,
            silence_rms=0.01,
        )
        result: list[list[object]] = []

        def _push() -> None:
            result.append(acc.push(np.array([1, 1, 1, 1, 1, 0, 0, 0], dtype=np.float32)))

        thread = threading.Thread(target=_push)
        thread.start()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 1)
        self.assertEqual(result[0][0].samples.tolist(), [1.0, 1.0, 1.0, 1.0, 1.0])
        self.assertEqual(acc.pending_samples, 2)

        second = acc.push(np.zeros(2, dtype=np.float32))
        third = acc.push(np.zeros(2, dtype=np.float32))
        self.assertEqual(second, [])
        self.assertEqual(third, [])
        self.assertEqual(acc.pending_samples, 2)

    def test_cap_emissions_keep_monotonic_time_with_overlap(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=0.1,
            max_chunk_seconds=0.5,
            silence_gap_seconds=0.2,
            overlap_seconds=0.2,
            silence_rms=0.01,
        )

        first = acc.push(np.full(5, 0.8, dtype=np.float32))
        second = acc.push(np.full(5, 0.8, dtype=np.float32))

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0].sequence, 0)
        self.assertEqual(second[0].sequence, 1)
        self.assertAlmostEqual(first[0].t_start, 0.0)
        self.assertAlmostEqual(first[0].t_end, 0.5)
        self.assertAlmostEqual(second[0].t_start, 0.3)
        self.assertAlmostEqual(second[0].t_end, 0.8)

    def test_cap_emissions_preserve_suffix_with_overlap(self) -> None:
        acc = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=0.1,
            max_chunk_seconds=0.5,
            silence_gap_seconds=0.2,
            overlap_seconds=0.2,
            silence_rms=0.01,
        )

        emitted = acc.push(np.arange(1, 9, dtype=np.float32))
        self.assertEqual(len(emitted), 2)
        self.assertListEqual(emitted[0].samples.tolist(), [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertListEqual(emitted[1].samples.tolist(), [4.0, 5.0, 6.0, 7.0, 8.0])
        self.assertEqual(acc.pending_samples, 2)

        flushed = acc.flush(final=True)
        self.assertEqual(flushed, [])
        self.assertEqual(acc.pending_samples, 0)

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
