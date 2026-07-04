from __future__ import annotations

import subprocess
import sys
import textwrap
import types
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
        self.assertEqual(
            STT_BACKENDS, ("faster-whisper", "parakeet", "whisperx", "openai", "xai", "gemini")
        )
        self.assertEqual(tuple(BACKEND_REGISTRY.keys()), STT_BACKENDS)

    def test_resolve_model_name_defaults(self) -> None:
        self.assertEqual(resolve_model_name("faster-whisper", None), "turbo")
        self.assertEqual(resolve_model_name("whisperx", None), "large-v3")
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
        fake_whisperx = types.SimpleNamespace(
            load_model=lambda *args, **kwargs: types.SimpleNamespace(
                transcribe=lambda *a, **kw: {"segments": [{"text": "hello"}], "language": "en"}
            )
        )
        with patch.dict("sys.modules", {"whisperx": fake_whisperx}):
            whisperx = create_speech_to_text(
                backend="whisperx",
                model="large-v3",
                device="cpu",
            )
        self.assertEqual(whisper.backend_name, "faster-whisper")
        self.assertEqual(whisperx.backend_name, "whisperx")
        self.assertEqual(openai.backend_name, "openai")
        self.assertEqual(xai.backend_name, "xai")
        self.assertEqual(gemini.backend_name, "gemini")

    @unittest.skipIf(
        sys.platform == "win32",
        "Windows CI intermittently interrupts this subprocess-only import isolation check.",
    )
    def test_registry_import_does_not_require_faster_whisper_runtime(self) -> None:
        code = textwrap.dedent(
            """
            import builtins
            import os

            original_import = builtins.__import__

            def blocked_import(name, *args, **kwargs):
                if name == "faster_whisper" or name.startswith("faster_whisper."):
                    raise FileNotFoundError("missing faster-whisper runtime")
                return original_import(name, *args, **kwargs)

            builtins.__import__ = blocked_import
            os.environ["DICTATE_XAI_API_KEY"] = "test-key"

            from dictate.stt import STT_BACKENDS, create_speech_to_text

            assert "xai" in STT_BACKENDS
            stt = create_speech_to_text(backend="xai", model="grok-speech-to-text", device="cpu")
            assert stt.backend_name == "xai"
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0)

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

    def test_whisperx_readiness_reports_missing_optional_package(self) -> None:
        with patch("dictate.stt.factory.whisperx_available", return_value=False):
            report = check_backend_readiness(
                backend="whisperx",
                model="large-v3",
                device="cpu",
            )
        self.assertTrue(any("WhisperX package" in error for error in report.errors))
        self.assertTrue(any("Hugging Face token" in warning for warning in report.warnings))

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
