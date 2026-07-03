"""Tests for the AGC/limiter + noise-suppression capture preprocessor."""

from __future__ import annotations

import builtins
import os
import unittest

import numpy as np

from dictate.audio_preprocess import (
    AudioPreprocessor,
    create_preprocessor,
    preprocessing_enabled,
)


class _EnvGuard:
    def __init__(self, **values: str) -> None:
        self._values = values
        self._saved: dict[str, str | None] = {}

    def __enter__(self):
        for k, v in self._values.items():
            self._saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class EnableAndFallbackTests(unittest.TestCase):
    def test_enabled_by_default(self) -> None:
        self.assertTrue(preprocessing_enabled())

    def test_disabled_by_env(self) -> None:
        for value in ("0", "false", "off", "no", "OFF"):
            with self.subTest(value=value), _EnvGuard(DICTATE_DENOISE=value):
                self.assertFalse(preprocessing_enabled())
                self.assertIsNone(create_preprocessor())

    def test_created_even_when_noise_suppression_dep_missing(self) -> None:
        # Gain control is dependency-free and must still run without webrtc.
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "webrtc_noise_gain":
                raise ModuleNotFoundError("no webrtc_noise_gain")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            p = create_preprocessor()
            self.assertIsNotNone(p)
            self.assertFalse(p.has_noise_suppression)
            # And it still levels audio (below).
            out = p.process((np.ones(1600, dtype=np.float32) * 0.01))
            self.assertGreater(out.size, 0)
        finally:
            builtins.__import__ = real_import


class GainControlTests(unittest.TestCase):
    """The core fix: any input level is normalized and never clips."""

    def _agc_only(self) -> AudioPreprocessor:
        # Disable NS so we test the gain path deterministically.
        with _EnvGuard(DICTATE_DENOISE_LEVEL="0"):
            return AudioPreprocessor()

    def test_hot_input_is_limited_not_clipped(self) -> None:
        p = self._agc_only()
        # A hot mic delivering float values well above 1.0 (what we measured).
        t = np.linspace(0, 40, 16000, dtype=np.float32)
        hot = (np.sin(t) * 2.2).astype(np.float32)
        out = np.concatenate([p.process(hot[i : i + 1024]) for i in range(0, len(hot), 1024)])
        self.assertLessEqual(float(np.max(np.abs(out))), 0.99)
        # Not a degenerate square wave pinned at the limit — most of it is scaled.
        at_limit = float(np.mean(np.abs(out) >= 0.97))
        self.assertLess(at_limit, 0.5)

    def test_quiet_input_is_boosted(self) -> None:
        p = self._agc_only()
        t = np.linspace(0, 200, 16000 * 3, dtype=np.float32)
        quiet = (np.sin(t) * 0.01).astype(np.float32)  # ~ -40 dBFS
        out = np.concatenate([p.process(quiet[i : i + 1024]) for i in range(0, len(quiet), 1024)])
        # The tail (after the gain ramps up) should be much louder than the input.
        tail_rms = float(np.sqrt(np.mean(out[-16000:] ** 2)))
        self.assertGreater(tail_rms, 0.03)

    def test_rejects_non_16k(self) -> None:
        with self.assertRaises(ValueError):
            AudioPreprocessor(sample_rate=48000)

    def test_empty_input_is_safe(self) -> None:
        p = self._agc_only()
        self.assertEqual(p.process(np.empty(0, dtype=np.float32)).size, 0)
        self.assertEqual(p.flush().size, 0)


def _has_webrtc() -> bool:
    try:
        import webrtc_noise_gain  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_has_webrtc(), "webrtc-noise-gain not installed")
class NoiseSuppressionFramingTests(unittest.TestCase):
    def test_has_noise_suppression(self) -> None:
        self.assertTrue(AudioPreprocessor().has_noise_suppression)

    def test_total_length_preserved_across_calls(self) -> None:
        p = AudioPreprocessor()
        total_in = total_out = 0
        for _ in range(6):
            chunk = (np.sin(np.linspace(0, 5, 237)) * 0.2).astype(np.float32)
            total_in += chunk.size
            total_out += p.process(chunk).size
        total_out += p.flush().size
        self.assertEqual(total_out, total_in)


if __name__ == "__main__":
    unittest.main()
