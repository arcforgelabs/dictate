from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dictate.stt.gemini_backend import GeminiSpeechToText, _extract_text, gemini_api_key_available


def _print_command(value: str) -> str:
    python = Path(sys.executable).as_posix()
    return f'{python} -c "import sys; sys.stdout.write({value!r})"'


class _FakeResponse:
    status = 200

    def __init__(self, body: str):
        self.body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class GeminiBackendTests(unittest.TestCase):
    def test_transcribe_posts_inline_audio_to_generate_content(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            captured["body"] = request.data
            body = json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "hello from gemini"},
                                ]
                            }
                        }
                    ]
                }
            )
            return _FakeResponse(body)

        audio = np.zeros(16000, dtype=np.float32)
        with patch.dict(os.environ, {"DICTATE_GEMINI_API_KEY": "test-key"}, clear=True):
            with patch("dictate.stt.gemini_backend.urllib.request.urlopen", fake_urlopen):
                stt = GeminiSpeechToText(model_name="gemini-3-flash-preview")
                text = stt.transcribe(audio, language="en", prompt_context="Use Arc Forge terms.")

        self.assertEqual(text, "hello from gemini")
        self.assertIn("/models/gemini-3-flash-preview:generateContent", captured["url"])
        self.assertEqual(captured["headers"]["X-goog-api-key"], "test-key")
        payload = json.loads(captured["body"].decode())
        parts = payload["contents"][0]["parts"]
        self.assertIn("Return only the spoken transcript", parts[0]["text"])
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "audio/wav")
        self.assertTrue(parts[1]["inlineData"]["data"])

    def test_api_key_can_come_from_command(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"DICTATE_GEMINI_API_KEY_COMMAND": _print_command("command-key")},
                clear=True,
            ),
            patch("dictate.stt.gemini_backend.read_api_key", return_value=None),
        ):
            self.assertTrue(gemini_api_key_available())

    def test_extract_text_reads_candidate_parts(self) -> None:
        response = json.dumps(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "first"}, {"text": "second"}]}}
                ]
            }
        )

        self.assertEqual(_extract_text(response), "first\nsecond")


if __name__ == "__main__":
    unittest.main()
