from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate.model_prepare import _create_loaded_stt, _prepare_backend_resources, _should_retry_on_cpu
from dictate.stt.parakeet_backend import _INT8_FILES, prepare_parakeet_v2_int8_model
from dictate.stt.parakeet_pyannote_backend import ParakeetPyannoteSpeechToText


class FakeFailingStt:
    backend_name = "fake"
    model_name = "fake"

    def __init__(self) -> None:
        self.released = False

    @property
    def model(self):
        raise RuntimeError("load failed")

    def release(self) -> None:
        self.released = True


class FakePreparedStt:
    backend_name = "fake"
    model_name = "fake"

    def __init__(self) -> None:
        self.model_loaded = False
        self.prepared = False

    @property
    def model(self):
        self.model_loaded = True
        return "loaded"

    def prepare_model_resources(self) -> None:
        self.prepared = True

    def release(self) -> None:
        return


class FakeParakeetAsr:
    def __init__(self) -> None:
        self.model_loaded = False

    @property
    def model(self):
        self.model_loaded = True
        return "asr-loaded"

    def release(self) -> None:
        return


class ModelPrepareTests(unittest.TestCase):
    def test_retry_on_cpu_when_cuda_busy_for_auto(self) -> None:
        exc = RuntimeError("CUDA failed with error CUDA-capable device(s) is/are busy or unavailable")
        self.assertTrue(_should_retry_on_cpu(exc, requested_device="auto"))

    def test_retry_on_cpu_when_cuda_oom_for_cuda_device(self) -> None:
        exc = RuntimeError("CUDA failed with error out of memory")
        self.assertTrue(_should_retry_on_cpu(exc, requested_device="cuda"))

    def test_no_retry_on_cpu_for_non_cuda_devices(self) -> None:
        exc = RuntimeError("CUDA failed with error CUDA-capable device(s) is/are busy or unavailable")
        self.assertFalse(_should_retry_on_cpu(exc, requested_device="cpu"))

    def test_create_loaded_stt_releases_backend_when_model_load_fails(self) -> None:
        stt = FakeFailingStt()
        with patch("dictate.model_prepare.create_speech_to_text", return_value=stt):
            with self.assertRaisesRegex(RuntimeError, "load failed"):
                _create_loaded_stt(
                    backend="faster-whisper",
                    model="turbo",
                    device="auto",
                    compute_type="int8",
                )

        self.assertTrue(stt.released)

    def test_prepare_backend_resources_prefers_backend_hook(self) -> None:
        stt = FakePreparedStt()

        _prepare_backend_resources(stt)  # type: ignore[arg-type]

        self.assertTrue(stt.prepared)
        self.assertFalse(stt.model_loaded)

    def test_prepare_parakeet_v2_int8_model_targets_exact_int8_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "engine" / "models" / "parakeet-tdt-0.6b-v2-onnx"
            with patch("dictate.stt.parakeet_backend._download_model_files") as download:
                result = prepare_parakeet_v2_int8_model(output)

        self.assertEqual(result, output.resolve())
        download.assert_called_once()
        args, _kwargs = download.call_args
        self.assertEqual(Path(args[0]), output.resolve())
        self.assertEqual(args[2], _INT8_FILES)

    def test_parakeet_pyannote_prepare_loads_asr_and_pyannote_pipeline(self) -> None:
        stt = ParakeetPyannoteSpeechToText()
        fake_asr = FakeParakeetAsr()
        pipeline_calls = 0

        def fake_pipeline():
            nonlocal pipeline_calls
            pipeline_calls += 1
            return object()

        stt._asr = fake_asr  # type: ignore[assignment]
        stt._pyannote_pipeline = fake_pipeline  # type: ignore[method-assign]

        stt.prepare_model_resources()

        self.assertTrue(fake_asr.model_loaded)
        self.assertEqual(pipeline_calls, 1)


if __name__ == "__main__":
    unittest.main()
