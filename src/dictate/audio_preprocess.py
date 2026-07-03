"""Real-time capture preprocessing so dictation works on any mic / room.

Two stages run on the live stream before the audio reaches the recognizer:

1. **Automatic gain control + limiter** (``_StreamingAgc``) — dependency-free and
   always on. It tracks the signal level and applies a smoothed gain toward a
   target, scaling quiet mics *up* and hot mics *down*, with a hard limiter so a
   too-hot mic cannot clip and destroy the signal. This removes the need for any
   manual mic-level tweaking, which is unworkable across the range of hardware,
   mics, and rooms real users have.
2. **Noise suppression** (WebRTC APM via ``webrtc-noise-gain``, the class of stack
   Telegram/Zoom use) — optional; applied when the native dependency is present.

The processor is created per recording. It degrades gracefully: if noise
suppression is unavailable, gain control still runs; if the whole stage is
disabled (``DICTATE_DENOISE=0``), callers pass audio through unchanged.
"""

from __future__ import annotations

import logging
import math
import os

import numpy as np

logger = logging.getLogger(__name__)

# WebRTC APM fixed frame: 10 ms @ 16 kHz mono.
_FRAME_SAMPLES = 160

_DEFAULT_NOISE_SUPPRESSION = 3  # 0-4; WebRTC NS aggressiveness.


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        return default


def preprocessing_enabled() -> bool:
    """True unless explicitly disabled via ``DICTATE_DENOISE=0``."""
    value = os.environ.get("DICTATE_DENOISE")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "off", "no"}


class _StreamingAgc:
    """Smoothed automatic gain control with a hard limiter, in the float domain.

    Targets a fixed RMS so the recognizer sees a consistent level regardless of
    the mic or how loud the user speaks, then hard-limits to keep peaks in range
    (a hot mic scaled down cannot clip; a quiet mic is boosted).
    """

    def __init__(
        self,
        *,
        target_rms: float = 0.12,  # ~ -18 dBFS RMS, a comfortable level for Whisper
        max_gain: float = 40.0,
        min_gain: float = 0.02,
        limit: float = 0.98,
    ) -> None:
        self._target = _env_float("DICTATE_AGC_TARGET_RMS", target_rms)
        self._max_gain = max_gain
        self._min_gain = min_gain
        self._limit = limit
        self._gain = 1.0
        self._env = 1e-4  # running RMS envelope

    def process(self, x: np.ndarray) -> np.ndarray:
        if x.size == 0:
            return x
        block_rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
        # Update the level envelope (fast attack toward louder, slower release).
        coef = 0.5 if block_rms > self._env else 0.1
        self._env += (block_rms - self._env) * coef
        if self._env > 1e-5:
            desired = self._target / self._env
        else:
            desired = self._gain  # essentially silence: hold gain, don't amplify noise
        desired = max(self._min_gain, min(self._max_gain, desired))
        # Smooth gain changes: drop fast (avoid clipping), rise slowly (avoid pumping).
        gcoef = 0.4 if desired < self._gain else 0.05
        self._gain += (desired - self._gain) * gcoef
        y = x * self._gain
        # Hard limiter: guarantees the signal (and the int16 NS sees) never clips.
        np.clip(y, -self._limit, self._limit, out=y)
        return y.astype(np.float32, copy=False)


class _WebRtcNoiseSuppressor:
    """WebRTC APM noise suppression over 10 ms int16 frames; buffers remainder."""

    def __init__(self, noise_suppression_level: int) -> None:
        from webrtc_noise_gain import AudioProcessor

        # AGC is handled by _StreamingAgc; use WebRTC only for noise suppression.
        self._ap = AudioProcessor(0, noise_suppression_level)
        self._tail = np.empty(0, dtype=np.int16)

    def process(self, samples: np.ndarray) -> np.ndarray:
        pcm = np.concatenate((self._tail, _to_int16(samples)))
        n_frames = pcm.size // _FRAME_SAMPLES
        if n_frames == 0:
            self._tail = pcm
            return np.empty(0, dtype=np.float32)
        used = n_frames * _FRAME_SAMPLES
        self._tail = pcm[used:].copy()
        return self._run(pcm[:used])

    def flush(self) -> np.ndarray:
        if self._tail.size == 0:
            return np.empty(0, dtype=np.float32)
        original = self._tail.size
        pad = (-original) % _FRAME_SAMPLES
        padded = np.concatenate((self._tail, np.zeros(pad, dtype=np.int16))) if pad else self._tail
        self._tail = np.empty(0, dtype=np.int16)
        return self._run(padded)[:original]

    def _run(self, pcm: np.ndarray) -> np.ndarray:
        chunks: list[bytes] = []
        for start in range(0, pcm.size, _FRAME_SAMPLES):
            frame = pcm[start : start + _FRAME_SAMPLES]
            try:
                result = self._ap.Process10ms(frame.tobytes())
                chunks.append(getattr(result, "audio", frame.tobytes()))
            except Exception:  # noqa: BLE001 — never let NS break capture
                chunks.append(frame.tobytes())
        processed = np.frombuffer(b"".join(chunks), dtype=np.int16)
        return (processed.astype(np.float32) / 32768.0).copy()


class AudioPreprocessor:
    """AGC + limiter (always) followed by optional WebRTC noise suppression."""

    def __init__(self, *, sample_rate: int = 16000) -> None:
        if sample_rate != 16000:
            raise ValueError("AudioPreprocessor requires 16 kHz audio")
        self._agc = _StreamingAgc()
        self._ns: _WebRtcNoiseSuppressor | None = None
        try:
            level = _env_int("DICTATE_DENOISE_LEVEL", _DEFAULT_NOISE_SUPPRESSION, 0, 4)
            if level > 0:
                self._ns = _WebRtcNoiseSuppressor(level)
        except Exception as exc:  # noqa: BLE001
            logger.info("Noise suppression unavailable (%s); using gain control only.", exc)

    @property
    def has_noise_suppression(self) -> bool:
        return self._ns is not None

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.size == 0:
            return np.empty(0, dtype=np.float32)
        leveled = self._agc.process(samples)
        if self._ns is None:
            return leveled
        return self._ns.process(leveled)

    def flush(self) -> np.ndarray:
        if self._ns is None:
            return np.empty(0, dtype=np.float32)
        return self._ns.flush()


def _to_int16(samples: np.ndarray) -> np.ndarray:
    clipped = np.clip(samples.astype(np.float32), -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def create_preprocessor(sample_rate: int = 16000) -> AudioPreprocessor | None:
    """Build a preprocessor, or ``None`` if preprocessing is disabled."""
    if not preprocessing_enabled():
        return None
    try:
        return AudioPreprocessor(sample_rate=sample_rate)
    except Exception as exc:  # noqa: BLE001
        logger.info("Audio preprocessing unavailable (%s); capturing raw audio.", exc)
        return None


def dbfs(x: np.ndarray) -> float:
    """Peak level of ``x`` in dBFS (for capture diagnostics)."""
    if x.size == 0:
        return -math.inf
    peak = float(np.max(np.abs(x)))
    return 20.0 * math.log10(peak + 1e-12)
