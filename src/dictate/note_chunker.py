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
        self._parts: list[np.ndarray] = []
        self._sequence = max(0, int(seq_offset))
        self._cursor_samples = max(0, int(sample_rate * float(time_offset_s)))
        self._trailing_silence = 0
        self._overlap_only_buffer = False

    @property
    def pending_samples(self) -> int:
        return sum(int(part.size) for part in self._parts)

    def push(self, samples: np.ndarray) -> list[EmittedNoteChunk]:
        if samples.size == 0:
            return []
        chunk = np.asarray(samples, dtype=np.float32).reshape(-1)
        self._parts.append(chunk)
        self._overlap_only_buffer = False
        emitted: list[EmittedNoteChunk] = []
        while True:
            ready = self._maybe_emit(force=False)
            if ready is None:
                break
            emitted.append(ready)
        return emitted

    def flush(self, *, final: bool = False) -> list[EmittedNoteChunk]:
        emitted: list[EmittedNoteChunk] = []
        if final and self._overlap_only_buffer:
            self._parts = []
            self._overlap_only_buffer = False
            self._trailing_silence = 0
            return emitted
        while True:
            ready = self._maybe_emit(force=final)
            if ready is None:
                break
            emitted.append(ready)
        if final and self.pending_samples > 0:
            emitted.append(self._emit_buffer(reason="final"))
        return emitted

    def _maybe_emit(self, *, force: bool) -> EmittedNoteChunk | None:
        if self.pending_samples == 0:
            return None
        self._trailing_silence = self._measure_trailing_silence()
        if force and self.pending_samples > 0:
            return self._emit_buffer(reason="final")
        if self.pending_samples < self.min_samples:
            return None
        if self.pending_samples >= self.max_samples:
            return self._emit_buffer(reason="cap")
        if self._trailing_silence >= self.silence_gap_samples:
            return self._emit_buffer(reason="silence")
        return None

    def _emit_buffer(self, *, reason: str) -> EmittedNoteChunk:
        total = self.pending_samples
        if reason == "cap":
            emit_count = min(total, self.max_samples)
        elif self._trailing_silence >= self.silence_gap_samples:
            emit_count = total - self._trailing_silence
        else:
            emit_count = total
        emit_count = max(1, min(emit_count, total))
        audio = self._take_samples(emit_count)
        t_start = self._cursor_samples / self.sample_rate
        t_end = (self._cursor_samples + emit_count) / self.sample_rate
        if reason == "final":
            self._cursor_samples += emit_count
            self._parts = []
            self._overlap_only_buffer = False
        elif self.overlap_samples > 0 and emit_count > 0:
            overlap = audio[emit_count - self.overlap_samples : emit_count].copy()
            suffix = self._parts
            self._parts = ([overlap] if overlap.size else []) + suffix
            self._overlap_only_buffer = bool(overlap.size and not suffix)
            self._cursor_samples += max(0, emit_count - overlap.size)
        else:
            self._parts = []
            self._overlap_only_buffer = False
            self._cursor_samples += emit_count
        self._trailing_silence = 0
        chunk = EmittedNoteChunk(
            samples=audio,
            sequence=self._sequence,
            t_start=t_start,
            t_end=t_end,
        )
        self._sequence += 1
        return chunk

    def _take_samples(self, count: int) -> np.ndarray:
        if count <= 0 or not self._parts:
            return np.array([], dtype=np.float32)
        remaining = count
        taken: list[np.ndarray] = []
        while remaining > 0 and self._parts:
            head = self._parts[0]
            if head.size <= remaining:
                taken.append(head)
                self._parts.pop(0)
                remaining -= int(head.size)
                continue
            taken.append(head[:remaining].copy())
            self._parts[0] = head[remaining:]
            remaining = 0
        if not taken:
            return np.array([], dtype=np.float32)
        if len(taken) == 1:
            return taken[0]
        return np.concatenate(taken)

    def _measure_trailing_silence(self) -> int:
        silent = 0
        for part in reversed(self._parts):
            part_silent = self._measure_trailing_silence_in(part)
            silent += part_silent
            if part_silent < part.size:
                break
        return min(self.pending_samples, silent)

    def _measure_trailing_silence_in(self, audio: np.ndarray) -> int:
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
