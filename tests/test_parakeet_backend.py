"""Tests for the Parakeet (onnx-asr) backend registration and behavior.

The model itself is a ~630 MB download and is not exercised here; these tests
cover registration, capabilities, the graceful-degradation contract, and the
transcribe wrapper against a fake onnx-asr model.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from dictate.stt import (
    BACKEND_REGISTRY,
    DEFAULT_MODELS,
    PARAKEET_MODELS,
    STT_BACKENDS,
    create_speech_to_text,
)
from dictate.stt.base import SttBackend
from dictate.stt.parakeet_backend import ParakeetSpeechToText


class ParakeetRegistrationTests(unittest.TestCase):
    def test_registered_in_backends(self) -> None:
        self.assertIn("parakeet", STT_BACKENDS)
        self.assertIn("parakeet", BACKEND_REGISTRY)
        self.assertEqual(DEFAULT_MODELS["parakeet"], "parakeet-tdt-0.6b-v2")
        self.assertIn("parakeet-tdt-0.6b-v2", PARAKEET_MODELS)
        self.assertIn("parakeet-tdt-0.6b-v3", PARAKEET_MODELS)

    def test_type_literal_includes_parakeet(self) -> None:
        # SttBackend is a Literal; parakeet must be one of its args.
        import typing

        self.assertIn("parakeet", typing.get_args(SttBackend))

    def test_capabilities(self) -> None:
        caps = ParakeetSpeechToText.capabilities
        self.assertFalse(caps.supports_streaming_chunks)  # full-utterance decode, no chunking
        self.assertFalse(caps.supports_language_hint)  # English-only, no language arg

    def test_factory_builds_without_loading_model(self) -> None:
        stt = create_speech_to_text(
            backend="parakeet", model="parakeet-tdt-0.6b-v2", device="cpu", compute_type="int8"
        )
        self.assertEqual(stt.backend_name, "parakeet")
        self.assertEqual(stt.compute_type, "int8")
        self.assertIsNone(stt._model)  # lazy — not loaded on construction

    def test_factory_rejects_unwired_v3_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "not wired"):
            create_speech_to_text(
                backend="parakeet",
                model="parakeet-tdt-0.6b-v3",
                device="cpu",
                compute_type="int8",
            )

    def test_factory_rejects_unwired_gpu_device(self) -> None:
        with self.assertRaisesRegex(ValueError, "not wired"):
            create_speech_to_text(
                backend="parakeet",
                model="parakeet-tdt-0.6b-v2",
                device="cuda",
                compute_type="int8",
            )


class _FakeOnnxModel:
    def __init__(self, text: str) -> None:
        self._text = text
        self.received: np.ndarray | None = None

    def recognize(self, audio):  # noqa: ANN001
        self.received = audio
        return self._text


class ParakeetTranscribeTests(unittest.TestCase):
    def _stt_with_fake(self, text: str) -> ParakeetSpeechToText:
        stt = ParakeetSpeechToText()
        stt._model = _FakeOnnxModel(text)
        return stt

    def test_transcribe_returns_stripped_text(self) -> None:
        stt = self._stt_with_fake("  Hello, world.  ")
        out = stt.transcribe(np.ones(16000, dtype=np.float32), language="en")
        self.assertEqual(out, "Hello, world.")

    def test_empty_audio_returns_empty(self) -> None:
        stt = self._stt_with_fake("unused")
        self.assertEqual(stt.transcribe(np.array([], dtype=np.float32)), "")

    def test_ignores_language_and_prompt_args(self) -> None:
        stt = self._stt_with_fake("ok")
        # Must accept the engine's kwargs without error even though it ignores them.
        out = stt.transcribe(
            np.ones(1600, dtype=np.float32),
            language="en",
            hotwords="foo bar",
            prompt_context="ctx",
            initial_prompt="prev",
            long_form=True,
        )
        self.assertEqual(out, "ok")

    def test_release_clears_model(self) -> None:
        stt = self._stt_with_fake("ok")
        stt.release()
        self.assertIsNone(stt._model)


class ParakeetReadinessTests(unittest.TestCase):
    def test_readiness_reports_missing_dependency(self) -> None:
        from dictate.stt import check_backend_readiness

        with patch("dictate.stt.factory.parakeet_available", return_value=False):
            report = check_backend_readiness(backend="parakeet", model=None, device="cpu")
        self.assertTrue(any("onnx-asr is not importable" in e for e in report.errors))

    def test_readiness_ok_when_available(self) -> None:
        from dictate.stt import check_backend_readiness

        with patch("dictate.stt.factory.parakeet_available", return_value=True):
            report = check_backend_readiness(backend="parakeet", model=None, device="cpu")
        self.assertEqual(report.errors, [])

    def test_readiness_marks_v3_as_planned_not_wired(self) -> None:
        from dictate.stt import check_backend_readiness

        with patch("dictate.stt.factory.parakeet_available", return_value=True):
            report = check_backend_readiness(
                backend="parakeet",
                model="parakeet-tdt-0.6b-v3",
                device="cpu",
            )
        self.assertTrue(
            any("planned lane but is not wired yet" in error for error in report.errors)
        )

    def test_readiness_marks_cuda_as_planned_not_wired(self) -> None:
        from dictate.stt import check_backend_readiness

        with patch("dictate.stt.factory.parakeet_available", return_value=True):
            report = check_backend_readiness(
                backend="parakeet",
                model="parakeet-tdt-0.6b-v2",
                device="cuda",
            )
        self.assertTrue(any("device 'cuda'" in error for error in report.errors))


if __name__ == "__main__":
    unittest.main()
