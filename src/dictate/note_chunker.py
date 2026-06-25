"""Silence-aligned audio chunking for long local note recordings."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_SAMPLE_RATE = 16000
MIN_CHUNK_SECONDS = 20.0
MAX_CHUNK_SECONDS = 45.0
SILENCE_GAP_SECONDS = 0.4
OVERLAP_SECONDS = 1.5
SILENCE_RMS = 0.012
FRAME_SAMPLES = 320  # 20ms at 16kHz


@dataclass(slots=True)
class EmittedNoteChunk:
    samples: np.ndarray
    sequence: int
    t_start: float
    t_end: float


class NoteChunkAccumulator:
    """Accumulate mic audio and emit chunks on silence gaps or hard caps."""

    def __init__(
        self,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        min_chunk_seconds: float = MIN_CHUNK_SECONDS,
        max_chunk_seconds: float = MAX_CHUNK_SECONDS,
        silence_gap_seconds: float = SILENCE_GAP_SECONDS,
        overlap_seconds: float = OVERLAP_SECONDS,
        silence_rms: float = SILENCE_RMS,
        seq_offset: int = 0,
        time_offset_s: float = 0.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.min_samples = max(1, int(sample_rate * min_chunk_seconds))
        self.max_samples = max(self.min_samples, int(sample_rate * max_chunk_seconds))
        self.silence_gap_samples = max(1, int(sample_rate * silence_gap_seconds))
        self.overlap_samples = max(0, int(sample_rate * overlap_seconds))
        self.silence_rms = silence_rms
        self._buffer = np.array([], dtype=np.float32)
        self._sequence = max(0, int(seq_offset))
        self._cursor_samples = max(0, int(sample_rate * float(time_offset_s)))
        self._trailing_silence = 0

    @property
    def pending_samples(self) -> int:
        return int(self._buffer.size)

    def push(self, samples: np.ndarray) -> list[EmittedNoteChunk]:
        if samples.size == 0:
            return []
        chunk = np.asarray(samples, dtype=np.float32).reshape(-1)
        self._buffer = np.concatenate((self._buffer, chunk))
        emitted: list[EmittedNoteChunk] = []
        while True:
            ready = self._maybe_emit(force=False)
            if ready is None:
                break
            emitted.append(ready)
        return emitted

    def flush(self, *, final: bool = False) -> list[EmittedNoteChunk]:
        emitted: list[EmittedNoteChunk] = []
        while True:
            ready = self._maybe_emit(force=final)
            if ready is None:
                break
            emitted.append(ready)
        if final and self._buffer.size > 0:
            emitted.append(self._emit_buffer(reason="final"))
        return emitted

    def _maybe_emit(self, *, force: bool) -> EmittedNoteChunk | None:
        if self._buffer.size == 0:
            return None
        self._trailing_silence = self._measure_trailing_silence(self._buffer)
        if force and self._buffer.size > 0:
            return self._emit_buffer(reason="final")
        if self._buffer.size < self.min_samples:
            return None
        if self._buffer.size >= self.max_samples:
            return self._emit_buffer(reason="cap")
        if self._trailing_silence >= self.silence_gap_samples:
            return self._emit_buffer(reason="silence")
        return None

    def _emit_buffer(self, *, reason: str) -> EmittedNoteChunk:
        if reason == "cap":
            emit_count = min(int(self._buffer.size), self.max_samples)
        elif self._trailing_silence >= self.silence_gap_samples:
            emit_count = int(self._buffer.size) - self._trailing_silence
        else:
            emit_count = int(self._buffer.size)
        emit_count = max(1, min(emit_count, int(self._buffer.size)))
        audio = self._buffer[:emit_count].copy()
        t_start = self._cursor_samples / self.sample_rate
        t_end = (self._cursor_samples + emit_count) / self.sample_rate
        self._cursor_samples += emit_count
        overlap = self._buffer[emit_count - self.overlap_samples : emit_count].copy() if self.overlap_samples else np.array([], dtype=np.float32)
        self._buffer = overlap if overlap.size else np.array([], dtype=np.float32)
        self._trailing_silence = 0
        chunk = EmittedNoteChunk(
            samples=audio,
            sequence=self._sequence,
            t_start=t_start,
            t_end=t_end,
        )
        self._sequence += 1
        return chunk

    def _measure_trailing_silence(self, audio: np.ndarray) -> int:
        frame = self._frame_samples
        if audio.size < frame:
            return 0 if self._frame_rms(audio) >= self.silence_rms else int(audio.size)
        silent = 0
        offset = audio.size
        while offset >= frame:
            offset -= frame
            window = audio[offset : offset + frame]
            if self._frame_rms(window) >= self.silence_rms:
                break
            silent += frame
        if offset > 0 and silent < audio.size:
            head = audio[:offset]
            if head.size and self._frame_rms(head) < self.silence_rms:
                silent += int(head.size)
        return min(int(audio.size), silent)

    @property
    def _frame_samples(self) -> int:
        return max(1, min(FRAME_SAMPLES, self.sample_rate // 20))

    @staticmethod
    def _frame_rms(frame: np.ndarray) -> float:
        if frame.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
