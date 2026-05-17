from __future__ import annotations

import unittest
from unittest.mock import patch

from dictate.stt import (
    BACKEND_REGISTRY,
    STT_BACKENDS,
    check_backend_readiness,
    create_speech_to_text,
    resolve_model_name,
)


class SttRegistryTests(unittest.TestCase):
    def test_backend_registry_has_expected_backends(self) -> None:
        self.assertEqual(STT_BACKENDS, ("faster-whisper", "openai", "xai", "gemini"))
        self.assertEqual(tuple(BACKEND_REGISTRY.keys()), STT_BACKENDS)

    def test_resolve_model_name_defaults(self) -> None:
        self.assertEqual(resolve_model_name("faster-whisper", None), "turbo")
        self.assertEqual(resolve_model_name("openai", None), "gpt-4o-mini-transcribe")
        self.assertEqual(resolve_model_name("xai", None), "grok-speech-to-text")
        self.assertEqual(resolve_model_name("gemini", None), "gemini-3-flash-preview")

    def test_create_backend_instances_without_loading_models(self) -> None:
        whisper = create_speech_to_text(
            backend="faster-whisper",
            model="turbo",
            device="cpu",
        )
        with patch.dict("os.environ", {"DICTATE_OPENAI_API_KEY": "test-key"}):
            openai = create_speech_to_text(
                backend="openai",
                model="gpt-4o-mini-transcribe",
                device="cpu",
            )
        with patch.dict("os.environ", {"DICTATE_XAI_API_KEY": "test-key"}):
            xai = create_speech_to_text(
                backend="xai",
                model="grok-speech-to-text",
                device="cpu",
            )
        with patch.dict("os.environ", {"DICTATE_GEMINI_API_KEY": "test-key"}):
            gemini = create_speech_to_text(
                backend="gemini",
                model="gemini-3-flash-preview",
                device="cpu",
            )
        self.assertEqual(whisper.backend_name, "faster-whisper")
        self.assertEqual(openai.backend_name, "openai")
        self.assertEqual(xai.backend_name, "xai")
        self.assertEqual(gemini.backend_name, "gemini")

    def test_backend_readiness_returns_metadata(self) -> None:
        report = check_backend_readiness(
            backend="faster-whisper",
            model="turbo",
            device="cpu",
        )
        self.assertTrue(any(note.startswith("STT backend:") for note in report.notes))
        self.assertTrue(any(note.startswith("STT model:") for note in report.notes))

    def test_openai_readiness_requires_api_key(self) -> None:
        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "", "DICTATE_OPENAI_API_KEY": ""}),
            patch("dictate.stt.openai_backend.read_api_key", return_value=None),
            patch("dictate.api_keys.read_api_key", return_value=None),
        ):
            report = check_backend_readiness(
                backend="openai",
                model="gpt-4o-mini-transcribe",
                device="cpu",
            )
        self.assertTrue(any("API key" in error for error in report.errors))

    def test_gemini_readiness_requires_api_key(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "GEMINI_API_KEY": "",
                    "GOOGLE_API_KEY": "",
                    "DICTATE_GEMINI_API_KEY": "",
                },
            ),
            patch("dictate.stt.gemini_backend.read_api_key", return_value=None),
            patch("dictate.api_keys.read_api_key", return_value=None),
        ):
            report = check_backend_readiness(
                backend="gemini",
                model="gemini-3-flash-preview",
                device="cpu",
            )
        self.assertTrue(any("API key" in error for error in report.errors))

    def test_xai_readiness_requires_api_key(self) -> None:
        with (
            patch.dict("os.environ", {"XAI_API_KEY": "", "DICTATE_XAI_API_KEY": ""}),
            patch("dictate.stt.xai_backend.read_api_key", return_value=None),
            patch("dictate.api_keys.read_api_key", return_value=None),
        ):
            report = check_backend_readiness(
                backend="xai",
                model="grok-speech-to-text",
                device="cpu",
            )
        self.assertTrue(any("API key" in error for error in report.errors))


if __name__ == "__main__":
    unittest.main()
