"""Sustained-silence detection for long note recordings."""

from __future__ import annotations

import numpy as np

from dictate.note_chunker import FRAME_SAMPLES, SILENCE_RMS

DEFAULT_AUTO_PAUSE_SECONDS = 120.0


class NoteSilenceMonitor:
    """Accumulate consecutive silent samples; fire once the pause threshold is met."""

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        pause_after_seconds: float = DEFAULT_AUTO_PAUSE_SECONDS,
        silence_rms: float = SILENCE_RMS,
    ) -> None:
        self.sample_rate = sample_rate
        self._pause_samples = max(1, int(sample_rate * pause_after_seconds))
        self.silence_rms = silence_rms
        self._frame_samples = max(1, min(FRAME_SAMPLES, sample_rate // 20))
        self._silent_samples = 0

    def reset(self) -> None:
        self._silent_samples = 0

    def push(self, samples: np.ndarray) -> bool:
        """Return True when sustained silence exceeds the configured threshold."""
        if samples.size == 0:
            return False
        chunk = np.asarray(samples, dtype=np.float32).reshape(-1)
        frame = self._frame_samples
        offset = 0
        while offset < chunk.size:
            end = min(offset + frame, chunk.size)
            window = chunk[offset:end]
            if self._frame_rms(window) < self.silence_rms:
                self._silent_samples += int(window.size)
            else:
                self._silent_samples = 0
            if self._silent_samples >= self._pause_samples:
                return True
            offset = end
        return False

    @staticmethod
    def _frame_rms(frame: np.ndarray) -> float:
        if frame.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
