from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate.model_prepare import _create_loaded_stt, _prepare_backend_resources, run_prepare_model
from dictate.model_state import is_model_prepared
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
    def test_retired_device_flag_is_ignored_and_prepares_on_cpu(self) -> None:
        stt = FakePreparedStt()
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "model-state.json"

            def mark_prepared(**kwargs):
                from dictate.model_state import mark_model_prepared

                mark_model_prepared(**kwargs, path=state_path)

            with (
                patch("dictate.model_prepare.create_speech_to_text", return_value=stt) as create,
                patch("dictate.model_prepare.mark_model_prepared", side_effect=mark_prepared),
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                code = run_prepare_model(
                    ["--stt-backend", "parakeet", "--device", "cuda", "--compute-type", "int8"]
                )

            self.assertEqual(code, 0)
            self.assertNotIn("device", create.call_args.kwargs)
            self.assertIn("Ignoring --device cuda: Dictate runs on CPU only.", stderr.getvalue())
            self.assertTrue(
                is_model_prepared("parakeet", "parakeet-tdt-0.6b-v2", "int8", path=state_path)
            )

    def test_prepare_rejects_gpu_only_compute_type(self) -> None:
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            run_prepare_model(["--stt-backend", "parakeet", "--compute-type", "float16"])

    def test_create_loaded_stt_releases_backend_when_model_load_fails(self) -> None:
        stt = FakeFailingStt()
        with patch("dictate.model_prepare.create_speech_to_text", return_value=stt):
            with self.assertRaisesRegex(RuntimeError, "load failed"):
                _create_loaded_stt(
                    backend="parakeet",
                    model="parakeet-tdt-0.6b-v2",
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
