from __future__ import annotations

import unittest

from dictate.stt import (
    BACKEND_REGISTRY,
    STT_BACKENDS,
    check_backend_readiness,
    create_speech_to_text,
    resolve_model_name,
)


class SttRegistryTests(unittest.TestCase):
    def test_backend_registry_has_expected_backends(self) -> None:
        self.assertIn("faster-whisper", STT_BACKENDS)
        self.assertIn("nemo-canary", STT_BACKENDS)
        self.assertIn("whisper-cpp", STT_BACKENDS)
        self.assertIn("faster-whisper", BACKEND_REGISTRY)
        self.assertIn("nemo-canary", BACKEND_REGISTRY)
        self.assertIn("whisper-cpp", BACKEND_REGISTRY)

    def test_resolve_model_name_defaults(self) -> None:
        self.assertEqual(resolve_model_name("faster-whisper", None), "base")
        self.assertEqual(resolve_model_name("nemo-canary", None), "nvidia/canary-1b-flash")
        self.assertEqual(resolve_model_name("whisper-cpp", None), "large-v3-turbo-q5_0")

    def test_create_backend_instances_without_loading_models(self) -> None:
        whisper = create_speech_to_text(
            backend="faster-whisper",
            model="turbo",
            device="cpu",
        )
        canary = create_speech_to_text(
            backend="nemo-canary",
            model="nvidia/canary-1b-flash",
            device="cpu",
        )
        whisper_cpp = create_speech_to_text(
            backend="whisper-cpp",
            model="large-v3-turbo-q5_0",
            device="cpu",
        )
        self.assertEqual(whisper.backend_name, "faster-whisper")
        self.assertEqual(canary.backend_name, "nemo-canary")
        self.assertEqual(whisper_cpp.backend_name, "whisper-cpp")

    def test_backend_readiness_returns_metadata(self) -> None:
        report = check_backend_readiness(
            backend="nemo-canary",
            model="nvidia/canary-1b-flash",
            device="cpu",
        )
        self.assertTrue(any(note.startswith("STT backend:") for note in report.notes))
        self.assertTrue(any(note.startswith("STT model:") for note in report.notes))


if __name__ == "__main__":
    unittest.main()
