from __future__ import annotations

import types
import unittest
from unittest.mock import patch

import numpy as np

from dictate.stt.whisperx_backend import (
    WhisperXSpeechToText,
    _diarized_segments_text,
    _segments_text,
)


class WhisperXBackendTests(unittest.TestCase):
    def test_segments_text_joins_segment_text(self) -> None:
        result = {"segments": [{"text": " hello"}, {"text": "world "}]}
        self.assertEqual(_segments_text(result), "hello world")

    def test_diarized_segments_text_groups_contiguous_speakers(self) -> None:
        result = {
            "segments": [
                {"speaker": "SPEAKER_00", "text": "Hello."},
                {"speaker": "SPEAKER_00", "text": "Still me."},
                {"speaker": "SPEAKER_01", "text": "Reply."},
            ]
        }
        self.assertEqual(
            _diarized_segments_text(result),
            "Speaker 1: Hello. Still me.\nSpeaker 2: Reply.",
        )

    def test_transcribe_uses_whisperx_model(self) -> None:
        fake_model = types.SimpleNamespace(
            transcribe=lambda *args, **kwargs: {
                "segments": [{"text": "local transcript"}],
                "language": "en",
            }
        )
        fake_whisperx = types.SimpleNamespace(
            load_model=lambda *args, **kwargs: fake_model,
            load_audio=lambda path: np.zeros(160, dtype=np.float32),
        )
        with patch.dict("sys.modules", {"whisperx": fake_whisperx}):
            stt = WhisperXSpeechToText(model_name="large-v3", device="cpu")
            text = stt.transcribe(np.zeros(160, dtype=np.float32), language="en")
        self.assertEqual(text, "local transcript")

    def test_transcribe_diarized_requires_huggingface_token(self) -> None:
        fake_model = types.SimpleNamespace(
            transcribe=lambda *args, **kwargs: {
                "segments": [{"text": "local transcript"}],
                "language": "en",
            }
        )
        fake_whisperx = types.SimpleNamespace(load_model=lambda *args, **kwargs: fake_model)
        with (
            patch.dict("sys.modules", {"whisperx": fake_whisperx}),
            patch.dict(
                "os.environ",
                {"DICTATE_HF_TOKEN": "", "HUGGINGFACE_HUB_TOKEN": "", "HF_TOKEN": ""},
            ),
        ):
            stt = WhisperXSpeechToText(model_name="large-v3", device="cpu")
            with self.assertRaisesRegex(RuntimeError, "Hugging Face token"):
                stt.transcribe_diarized(np.zeros(160, dtype=np.float32), language="en")


if __name__ == "__main__":
    unittest.main()
