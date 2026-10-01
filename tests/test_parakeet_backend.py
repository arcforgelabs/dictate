"""Tests for the Parakeet (onnx-asr) backend registration and behavior.

The model itself is a ~630 MB download and is not exercised here; these tests
cover registration, capabilities, the graceful-degradation contract, and the
transcribe wrapper against a fake onnx-asr model.
"""

from __future__ import annotations

import os
import unittest
import sys
import types
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

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
            backend="parakeet", model="parakeet-tdt-0.6b-v2", compute_type="int8"
        )
        self.assertEqual(stt.backend_name, "parakeet")
        self.assertEqual(stt.compute_type, "int8")
        self.assertIsNone(stt._model)  # lazy — not loaded on construction

    def test_factory_builds_v3_without_loading_model(self) -> None:
        stt = create_speech_to_text(
            backend="parakeet",
            model="parakeet-tdt-0.6b-v3",
            compute_type="int8",
        )
        self.assertEqual(stt.model_name, "parakeet-tdt-0.6b-v3")
        self.assertIsNone(stt._model)

    def test_factory_rejects_unknown_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "not wired"):
            create_speech_to_text(
                backend="parakeet",
                model="parakeet-tdt-unknown",
                compute_type="int8",
            )


class _FakeOnnxModel:
    def __init__(self, text: str) -> None:
        self._text = text
        self.received: np.ndarray | None = None

    def recognize(self, audio):  # noqa: ANN001
        self.received = audio
        return self._text


class _FakeTimestampedModel(_FakeOnnxModel):
    def with_timestamps(self):
        return self

    def recognize(self, audio):  # noqa: ANN001
        self.received = audio
        return types.SimpleNamespace(
            text=self._text,
            timestamps=[0.25, 1.5],
            tokens=["Hello", "world"],
        )


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

    def test_transcribe_segments_uses_timestamp_adapter(self) -> None:
        stt = ParakeetSpeechToText()
        stt._model = _FakeTimestampedModel("Hello world")

        segments = stt.transcribe_segments(np.ones(32000, dtype=np.float32), language="en")

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].text, "Hello world")
        self.assertEqual(segments[0].t_start, 0.25)
        self.assertEqual(segments[0].t_end, 1.5)

    def test_release_clears_model(self) -> None:
        stt = self._stt_with_fake("ok")
        stt.release()
        self.assertIsNone(stt._model)

    def test_model_load_pins_cpu_provider(self) -> None:
        fake_onnx_asr = types.SimpleNamespace(load_model=Mock(return_value=_FakeOnnxModel("ok")))
        stt = ParakeetSpeechToText(model_name="parakeet-tdt-0.6b-v2")

        with (
            patch.dict(sys.modules, {"onnx_asr": fake_onnx_asr}),
            patch("dictate.stt.parakeet_backend._ensure_model", return_value=Path("/tmp/model")),
        ):
            self.assertIs(stt.model, fake_onnx_asr.load_model.return_value)

        fake_onnx_asr.load_model.assert_called_once()
        args, kwargs = fake_onnx_asr.load_model.call_args
        self.assertEqual(args[0], "nemo-parakeet-tdt-0.6b-v2")
        self.assertEqual(Path(args[1]), Path("/tmp/model"))
        self.assertEqual(
            kwargs,
            {
                "quantization": "int8",
                "providers": ["CPUExecutionProvider"],
            },
        )

    def test_float32_compute_uses_unquantized_files(self) -> None:
        stt = ParakeetSpeechToText(
            model_name="parakeet-tdt-0.6b-v2",
            compute_type="float32",
        )

        self.assertEqual(stt.quantization, None)

    def test_bundled_v2_int8_model_root_is_used_before_downloads(self) -> None:
        fake_onnx_asr = types.SimpleNamespace(load_model=Mock(return_value=_FakeOnnxModel("ok")))
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.dict(os.environ, {"DICTATE_PARAKEET_MODEL_PATH": temp_dir}, clear=True),
                patch("dictate.stt.parakeet_backend._model_files_present", return_value=True),
                patch("dictate.stt.parakeet_backend._download_model_files") as download,
                patch.dict(sys.modules, {"onnx_asr": fake_onnx_asr}),
            ):
                stt = ParakeetSpeechToText(model_name="parakeet-tdt-0.6b-v2")
                self.assertIs(stt.model, fake_onnx_asr.load_model.return_value)

        download.assert_not_called()
        args, kwargs = fake_onnx_asr.load_model.call_args
        self.assertEqual(Path(args[1]), Path(temp_dir))
        self.assertEqual(kwargs["quantization"], "int8")

    def test_v3_model_still_resolves_from_the_normal_download_path(self) -> None:
        fake_onnx_asr = types.SimpleNamespace(load_model=Mock(return_value=_FakeOnnxModel("ok")))
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_model_dir = Path(temp_dir) / "normal-model-dir"
            with (
                patch.dict(os.environ, {"DICTATE_PARAKEET_MODEL_PATH": temp_dir}, clear=True),
                patch("dictate.stt.parakeet_backend._model_dir", return_value=isolated_model_dir),
                patch("dictate.stt.parakeet_backend._download_model_files") as download,
                patch.dict(sys.modules, {"onnx_asr": fake_onnx_asr}),
            ):
                stt = ParakeetSpeechToText(model_name="parakeet-tdt-0.6b-v3")
                self.assertIs(stt.model, fake_onnx_asr.load_model.return_value)

        download.assert_called_once()
        args, kwargs = fake_onnx_asr.load_model.call_args
        self.assertEqual(Path(args[1]), isolated_model_dir)
        self.assertNotEqual(Path(args[1]), Path(temp_dir))
        self.assertEqual(kwargs["quantization"], "int8")


class ParakeetReadinessTests(unittest.TestCase):
    def test_readiness_reports_missing_dependency(self) -> None:
        from dictate.stt import check_backend_readiness

        with patch("dictate.stt.factory.parakeet_available", return_value=False):
            report = check_backend_readiness(backend="parakeet", model=None)
        self.assertTrue(any("onnx-asr is not importable" in e for e in report.errors))

    def test_readiness_ok_when_available(self) -> None:
        from dictate.stt import check_backend_readiness

        with patch("dictate.stt.factory.parakeet_available", return_value=True):
            report = check_backend_readiness(backend="parakeet", model=None)
        self.assertEqual(report.errors, [])

    def test_readiness_accepts_v3_when_available(self) -> None:
        from dictate.stt import check_backend_readiness

        with patch("dictate.stt.factory.parakeet_available", return_value=True):
            report = check_backend_readiness(
                backend="parakeet",
                model="parakeet-tdt-0.6b-v3",
            )
        self.assertEqual(report.errors, [])


if __name__ == "__main__":
    unittest.main()
