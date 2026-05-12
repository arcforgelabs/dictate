from __future__ import annotations

import unittest
from unittest.mock import patch

from dictate.model_prepare import _create_loaded_stt, _should_retry_on_cpu


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
                    backend="whisper-cpp",
                    model="large-v3-turbo-q5_0",
                    device="auto",
                    compute_type="int8",
                )

        self.assertTrue(stt.released)


if __name__ == "__main__":
    unittest.main()
