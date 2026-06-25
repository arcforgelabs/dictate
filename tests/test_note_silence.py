"""Tests for sustained-silence auto-pause detection."""

from __future__ import annotations

import unittest

import numpy as np

from dictate.note_silence import NoteSilenceMonitor


class NoteSilenceMonitorTests(unittest.TestCase):
    def test_silence_threshold_triggers_once(self) -> None:
        monitor = NoteSilenceMonitor(sample_rate=16000, pause_after_seconds=0.05, silence_rms=0.05)
        silence = np.zeros(500, dtype=np.float32)
        self.assertFalse(monitor.push(silence))
        self.assertTrue(monitor.push(silence))

    def test_speech_resets_timer(self) -> None:
        monitor = NoteSilenceMonitor(sample_rate=16000, pause_after_seconds=0.05, silence_rms=0.05)
        silence = np.zeros(500, dtype=np.float32)
        speech = np.full(500, 0.2, dtype=np.float32)
        monitor.push(silence)
        monitor.push(speech)
        self.assertFalse(monitor.push(silence))

    def test_reset_clears_accumulator(self) -> None:
        monitor = NoteSilenceMonitor(sample_rate=16000, pause_after_seconds=0.05, silence_rms=0.05)
        silence = np.zeros(500, dtype=np.float32)
        monitor.push(silence)
        monitor.reset()
        self.assertFalse(monitor.push(silence))


if __name__ == "__main__":
    unittest.main()
