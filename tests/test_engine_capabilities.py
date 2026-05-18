from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from dictate.engine import DictationEngine
from dictate.stt import SpeechToText, SttCapabilities


class _DummyNoHotwordsSpeechToText(SpeechToText):
    backend_name = "dummy-no-hotwords"
    capabilities = SttCapabilities(supports_hotwords=False, supports_prompt_bias=False)

    def __init__(self) -> None:
        self.received_hotwords: str | None = None
        self.received_prompt_context: str | None = None

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language
        self.received_hotwords = hotwords
        self.received_prompt_context = prompt_context
        return "ok"


class _DummyHotwordsSpeechToText(SpeechToText):
    backend_name = "dummy-hotwords"
    capabilities = SttCapabilities(supports_hotwords=True, supports_prompt_bias=False)

    def __init__(self, *, response_text: str = "ok") -> None:
        self.received_hotwords: str | None = None
        self.received_prompt_context: str | None = None
        self.response_text = response_text

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language
        self.received_hotwords = hotwords
        self.received_prompt_context = prompt_context
        return self.response_text


class _DummyPromptSpeechToText(SpeechToText):
    backend_name = "dummy-prompt"
    capabilities = SttCapabilities(supports_hotwords=False, supports_prompt_bias=True)

    def __init__(self) -> None:
        self.received_hotwords: str | None = None
        self.received_prompt_context: str | None = None

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language
        self.received_hotwords = hotwords
        self.received_prompt_context = prompt_context
        return "ok"


class _FailingApiSpeechToText(SpeechToText):
    backend_name = "xai"
    capabilities = SttCapabilities(supports_hotwords=True, supports_prompt_bias=False)
    model_name = "grok-speech-to-text"

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language, hotwords, prompt_context
        raise RuntimeError("remote 503")


class _FallbackSpeechToText(SpeechToText):
    backend_name = "faster-whisper"
    capabilities = SttCapabilities(supports_hotwords=True, supports_prompt_bias=False)
    model_name = "base"

    def __init__(self, *, response_text: str = "fallback text", fail: bool = False) -> None:
        self.response_text = response_text
        self.fail = fail
        self.received_hotwords: str | None = None

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language, prompt_context
        self.received_hotwords = hotwords
        if self.fail:
            raise RuntimeError("local model unavailable")
        return self.response_text


class DictationEngineCapabilityTests(unittest.TestCase):
    def test_hotwords_dropped_when_backend_does_not_support_them(self) -> None:
        stt = _DummyNoHotwordsSpeechToText()
        engine = DictationEngine(stt=stt, hotwords="AcmeWidget ProjectNova")
        audio = np.ones(8000, dtype=np.float32)

        result = engine.transcribe(audio, language="en")

        self.assertEqual(result.status, "ok")
        self.assertIsNone(stt.received_hotwords)
        self.assertIsNone(stt.received_prompt_context)

    def test_hotwords_passed_when_backend_supports_them(self) -> None:
        stt = _DummyHotwordsSpeechToText()
        engine = DictationEngine(stt=stt, hotwords="AcmeWidget ProjectNova")
        audio = np.ones(8000, dtype=np.float32)

        result = engine.transcribe(audio, language="en")

        self.assertEqual(result.status, "ok")
        self.assertEqual(stt.received_hotwords, "AcmeWidget ProjectNova")
        self.assertIsNone(stt.received_prompt_context)

    def test_prompt_mode_passes_context_on_prompt_capable_backend(self) -> None:
        stt = _DummyPromptSpeechToText()
        engine = DictationEngine(
            stt=stt,
            hotwords="AcmeWidget ProjectNova",
            lexicon_mode="prompt",
        )
        audio = np.ones(8000, dtype=np.float32)

        result = engine.transcribe(audio, language="en")

        self.assertEqual(result.status, "ok")
        self.assertIsNone(stt.received_hotwords)
        self.assertIsNotNone(stt.received_prompt_context)
        self.assertIn("AcmeWidget", stt.received_prompt_context or "")

    def test_post_mode_applies_single_edit_correction_for_hotwords(self) -> None:
        stt = _DummyHotwordsSpeechToText(response_text="Testing canery one two three")
        engine = DictationEngine(
            stt=stt,
            hotwords="canary",
            lexicon_mode="post",
        )
        audio = np.ones(8000, dtype=np.float32)

        result = engine.transcribe(audio, language="en")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "Testing canary one two three")
        self.assertIsNone(stt.received_hotwords)

    def test_post_mode_applies_explicit_replacement_map(self) -> None:
        stt = _DummyHotwordsSpeechToText(response_text="Testing kinneri one two three")
        engine = DictationEngine(
            stt=stt,
            hotwords="canary",
            lexicon_mode="post",
            lexicon_replacements={"kinneri": "canary"},
        )
        audio = np.ones(8000, dtype=np.float32)

        result = engine.transcribe(audio, language="en")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "Testing canary one two three")

    def test_api_backend_failure_uses_cpu_whisper_fallback_for_same_audio(self) -> None:
        fallback = _FallbackSpeechToText(response_text="recovered turn")
        engine = DictationEngine(
            stt=_FailingApiSpeechToText(),
            hotwords="AcmeWidget",
        )
        audio = np.ones(8000, dtype=np.float32)

        with patch("dictate.engine._create_cpu_whisper_fallback", return_value=fallback):
            result = engine.transcribe(audio, language="en")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "recovered turn")
        self.assertEqual(fallback.received_hotwords, "AcmeWidget")
        self.assertIsNotNone(result.notice)
        self.assertIn("xAI transcription failed", result.notice or "")
        self.assertIn("faster-whisper/base on CPU", result.notice or "")

    def test_api_backend_failure_reports_cpu_fallback_failure(self) -> None:
        fallback = _FallbackSpeechToText(fail=True)
        engine = DictationEngine(stt=_FailingApiSpeechToText())
        audio = np.ones(8000, dtype=np.float32)

        with patch("dictate.engine._create_cpu_whisper_fallback", return_value=fallback):
            result = engine.transcribe(audio, language="en")

        self.assertEqual(result.status, "error")
        self.assertIn("xAI transcription failed: remote 503", result.error or "")
        self.assertIn("CPU fallback failed: local model unavailable", result.error or "")


if __name__ == "__main__":
    unittest.main()
