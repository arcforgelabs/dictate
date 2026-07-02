from __future__ import annotations

import unittest

import numpy as np

from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModel:
    """Records the kwargs faster-whisper's ``WhisperModel.transcribe`` receives."""

    def __init__(self, response_text: str = "hello world") -> None:
        self.response_text = response_text
        self.calls: list[dict[str, object]] = []

    def transcribe(self, audio, **kwargs):  # noqa: ANN001
        self.calls.append(kwargs)
        return [_FakeSegment(self.response_text)], None


class FasterWhisperDecodeParamsTests(unittest.TestCase):
    """P1: decode quality params — beam_size and VAD padding forwarded to the model."""

    def _make_stt(self, fake_model: _FakeModel) -> FasterWhisperSpeechToText:
        stt = FasterWhisperSpeechToText(model_name="turbo", device="cpu", compute_type="int8")
        # Bypass the lazy-loading ``model`` property (which would try to import and
        # download faster-whisper) by injecting the fake model directly.
        stt._model = fake_model  # type: ignore[attr-defined]
        return stt

    def test_transcribe_forwards_beam_size_five(self) -> None:
        fake_model = _FakeModel()
        stt = self._make_stt(fake_model)

        text = stt.transcribe(np.zeros(16000, dtype=np.float32), language="en")

        self.assertEqual(text, "hello world")
        self.assertEqual(len(fake_model.calls), 1)
        self.assertEqual(fake_model.calls[0]["beam_size"], 5)

    def test_transcribe_forwards_generous_vad_padding(self) -> None:
        fake_model = _FakeModel()
        stt = self._make_stt(fake_model)

        stt.transcribe(np.zeros(16000, dtype=np.float32), language="en")

        vad_parameters = fake_model.calls[0]["vad_parameters"]
        self.assertAlmostEqual(vad_parameters["speech_pad_ms"], 400)
        self.assertGreaterEqual(vad_parameters["min_silence_duration_ms"], 500)
        self.assertTrue(fake_model.calls[0]["vad_filter"])

    def test_transcribe_threads_initial_prompt_and_long_form(self) -> None:
        fake_model = _FakeModel()
        stt = self._make_stt(fake_model)

        stt.transcribe(
            np.zeros(16000, dtype=np.float32),
            language="en",
            initial_prompt="previous chunk tail",
            long_form=True,
        )

        call = fake_model.calls[0]
        self.assertEqual(call["initial_prompt"], "previous chunk tail")
        self.assertTrue(call["condition_on_previous_text"])

    def test_transcribe_disables_conditioning_when_long_form_false(self) -> None:
        fake_model = _FakeModel()
        stt = self._make_stt(fake_model)

        stt.transcribe(np.zeros(16000, dtype=np.float32), language="en", long_form=False)

        self.assertFalse(fake_model.calls[0]["condition_on_previous_text"])

    def test_note_profile_decodes_with_master_params(self) -> None:
        fake_model = _FakeModel()
        stt = self._make_stt(fake_model)

        stt.transcribe(np.zeros(16000, dtype=np.float32), language="en", decode_profile="note")

        call = fake_model.calls[0]
        self.assertEqual(call["beam_size"], 1)
        self.assertEqual(call["vad_parameters"]["min_silence_duration_ms"], 300)
        self.assertEqual(call["vad_parameters"]["speech_pad_ms"], 50)

    def test_dictation_default_profile_decodes_with_quality_params(self) -> None:
        fake_model = _FakeModel()
        stt = self._make_stt(fake_model)

        # Default profile is "quality" — dictation and any non-note caller.
        stt.transcribe(np.zeros(16000, dtype=np.float32), language="en")

        call = fake_model.calls[0]
        self.assertEqual(call["beam_size"], 5)
        self.assertEqual(call["vad_parameters"]["min_silence_duration_ms"], 500)
        self.assertEqual(call["vad_parameters"]["speech_pad_ms"], 400)


if __name__ == "__main__":
    unittest.main()
