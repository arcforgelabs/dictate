from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from dictate.engine import DictationEngine
from dictate.stt import SpeechToText, SttCapabilities, TranscriptSegment


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


class _DummySpeakerAttributionSpeechToText(SpeechToText):
    backend_name = "dummy-speakers"
    capabilities = SttCapabilities(supports_speaker_attribution=True)

    def __init__(self) -> None:
        self.calls: list[str] = []

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language, hotwords, prompt_context
        self.calls.append("plain")
        return "plain"

    def transcribe_diarized(self, audio, language=None, hotwords=None) -> str:
        del audio, language, hotwords
        self.calls.append("diarized")
        return "Speaker 1: meeting"


class _DummySegmentSpeakerAttributionSpeechToText(SpeechToText):
    backend_name = "dummy-segment-speakers"
    capabilities = SttCapabilities(supports_speaker_attribution=True)

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language, hotwords, prompt_context
        return "plain"

    def transcribe_diarized_segments(self, audio, language=None, hotwords=None):
        del audio, language, hotwords
        return [
            TranscriptSegment(
                text="hello",
                t_start=0.0,
                t_end=0.5,
                speaker_id="SPEAKER_A",
                speaker_label="Speaker 1",
            ),
            TranscriptSegment(
                text="reply",
                t_start=0.6,
                t_end=1.0,
                speaker_id="SPEAKER_B",
                speaker_label="Speaker 2",
            ),
        ]


class _DummyPlainSegmentSpeechToText(SpeechToText):
    backend_name = "dummy-plain-segments"
    capabilities = SttCapabilities(supports_word_timestamps=True)

    @property
    def model(self):
        return None

    def transcribe(self, audio, language=None, hotwords=None, prompt_context=None) -> str:
        del audio, language, hotwords, prompt_context
        return "plain fallback"

    def transcribe_segments(self, audio, language=None, hotwords=None, prompt_context=None):
        del audio, language, hotwords, prompt_context
        return [
            TranscriptSegment(text="hello", t_start=0.0, t_end=0.4),
            TranscriptSegment(text="world", t_start=0.4, t_end=0.8),
        ]


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

    def transcribe(
        self,
        audio,
        language=None,
        hotwords=None,
        prompt_context=None,
        *,
        initial_prompt=None,
        long_form=False,
        decode_profile="quality",
    ) -> str:
        del audio, language, prompt_context, initial_prompt, long_form, decode_profile
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

    def test_required_speaker_attribution_fails_closed_without_capability(self) -> None:
        stt = _DummyNoHotwordsSpeechToText()
        engine = DictationEngine(stt=stt)
        audio = np.ones(8000, dtype=np.float32)

        result = engine.transcribe(audio, language="en", diarize=True, require_speaker_attribution=True)

        self.assertEqual(result.status, "error")
        self.assertIn("speaker attribution", result.error or "")

    def test_required_speaker_attribution_uses_diarized_backend(self) -> None:
        stt = _DummySpeakerAttributionSpeechToText()
        engine = DictationEngine(stt=stt)
        audio = np.ones(8000, dtype=np.float32)

        result = engine.transcribe(audio, language="en", diarize=True, require_speaker_attribution=True)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "Speaker 1: meeting")
        self.assertEqual(stt.calls, ["diarized"])

    def test_required_speaker_attribution_preserves_structured_segments(self) -> None:
        stt = _DummySegmentSpeakerAttributionSpeechToText()
        engine = DictationEngine(stt=stt)
        audio = np.ones(16000, dtype=np.float32)

        result = engine.transcribe(audio, language="en", diarize=True, require_speaker_attribution=True)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "Speaker 1: hello\nSpeaker 2: reply")
        self.assertIsNotNone(result.segments)
        assert result.segments is not None
        self.assertEqual(result.segments[0].speaker_label, "Speaker 1")
        self.assertEqual(result.segments[0].t_start, 0.0)
        self.assertEqual(result.segments[1].speaker_id, "SPEAKER_B")

    def test_plain_transcription_preserves_structured_segments(self) -> None:
        stt = _DummyPlainSegmentSpeechToText()
        engine = DictationEngine(stt=stt)
        audio = np.ones(16000, dtype=np.float32)

        result = engine.transcribe(audio, language="en")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "hello\nworld")
        self.assertIsNotNone(result.segments)
        assert result.segments is not None
        self.assertEqual(result.segments[0].t_start, 0.0)
        self.assertEqual(result.segments[1].t_end, 0.8)

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


class _FakeWhisperSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _KwargCapturingWhisperModel:
    """Fake faster-whisper WhisperModel that records transcribe kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def transcribe(self, audio, **kwargs):  # noqa: ANN001
        del audio
        self.calls.append(kwargs)
        return [_FakeWhisperSegment("fallback words")], None


class _PromptOnlyStreamingStt(SpeechToText):
    """Streaming backend that accepts initial_prompt/long_form but NOT decode_profile."""

    backend_name = "faster-whisper"
    capabilities = SttCapabilities(supports_hotwords=True, supports_streaming_chunks=True)
    model_name = "base"

    def __init__(self) -> None:
        self.received_initial_prompt: str | None = None
        self.received_long_form: object = None

    @property
    def model(self):
        return None

    def transcribe(
        self,
        audio,
        language=None,
        hotwords=None,
        prompt_context=None,
        *,
        initial_prompt=None,
        long_form=False,
    ) -> str:
        del audio, language, hotwords, prompt_context
        self.received_initial_prompt = initial_prompt
        self.received_long_form = long_form
        return "streamed"


class DecodeProfileThreadingTests(unittest.TestCase):
    def test_note_mode_one_shot_fallback_decodes_with_note_beam_size(self) -> None:
        # Item 2: a note-mode one-shot recording that fails hosted and falls back
        # to CPU must decode with the "note" profile (beam_size=1).
        from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText

        fallback = FasterWhisperSpeechToText(model_name="base", device="cpu", compute_type="int8")
        fake_model = _KwargCapturingWhisperModel()
        fallback._model = fake_model  # type: ignore[attr-defined]

        engine = DictationEngine(stt=_FailingApiSpeechToText())
        audio = np.ones(8000, dtype=np.float32)

        with patch("dictate.engine._create_cpu_whisper_fallback", return_value=fallback):
            result = engine.transcribe(audio, language="en", diarize=True, decode_profile="note")

        self.assertEqual(result.status, "ok")
        self.assertEqual(len(fake_model.calls), 1)
        self.assertEqual(fake_model.calls[0]["beam_size"], 1)
        self.assertEqual(fake_model.calls[0]["vad_parameters"]["speech_pad_ms"], 50)

    def test_dictation_one_shot_uses_quality_beam_size(self) -> None:
        from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText

        fallback = FasterWhisperSpeechToText(model_name="base", device="cpu", compute_type="int8")
        fake_model = _KwargCapturingWhisperModel()
        fallback._model = fake_model  # type: ignore[attr-defined]

        engine = DictationEngine(stt=_FailingApiSpeechToText())
        audio = np.ones(8000, dtype=np.float32)

        with patch("dictate.engine._create_cpu_whisper_fallback", return_value=fallback):
            engine.transcribe(audio, language="en")  # default decode_profile="quality"

        self.assertEqual(fake_model.calls[0]["beam_size"], 5)

    def test_stream_chunk_degrades_decode_profile_but_keeps_initial_prompt(self) -> None:
        # Item 4: a backend that accepts initial_prompt/long_form but not
        # decode_profile still receives initial_prompt (only decode_profile dropped).
        stt = _PromptOnlyStreamingStt()
        engine = DictationEngine(stt=stt)
        engine.min_duration_s = 0
        audio = np.ones(8000, dtype=np.float32)

        result = engine.transcribe_stream_chunk(
            audio,
            language="en",
            initial_prompt="prior tail",
            long_form=False,
            decode_profile="quality",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.text, "streamed")
        self.assertEqual(stt.received_initial_prompt, "prior tail")
        self.assertFalse(stt.received_long_form)


if __name__ == "__main__":
    unittest.main()
