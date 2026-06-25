"""Short audible cues for capture state changes."""

from __future__ import annotations

import logging
import threading

import numpy as np

logger = logging.getLogger(__name__)

_PAUSE_CLICK_HZ = 880.0
_PAUSE_CLICK_SECONDS = 0.04
_PLAYBACK_SAMPLE_RATE = 48000


def play_pause_cue() -> None:
    """Play a soft click without blocking the caller."""
    threading.Thread(target=_play_pause_cue_sync, name="dictate-pause-cue", daemon=True).start()


def _play_pause_cue_sync() -> None:
    try:
        import sounddevice as sd
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pause cue unavailable: %s", exc)
        return
    try:
        count = max(1, int(_PLAYBACK_SAMPLE_RATE * _PAUSE_CLICK_SECONDS))
        t = np.linspace(0.0, _PAUSE_CLICK_SECONDS, count, endpoint=False, dtype=np.float64)
        envelope = np.exp(-t * 80.0)
        tone = (0.12 * np.sin(2.0 * np.pi * _PAUSE_CLICK_HZ * t) * envelope).astype(np.float32)
        sd.play(tone, _PLAYBACK_SAMPLE_RATE, blocking=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pause cue playback failed: %s", exc)
