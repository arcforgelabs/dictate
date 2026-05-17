from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import numpy as np

from dictate.stt.xai_backend import XAISpeechToText, _extract_text, _keyterms, xai_api_key_available


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self) -> bytes:
        return json.dumps({"text": "hello world", "duration": 1.2}).encode("utf-8")


class XAIBackendTests(unittest.TestCase):
    def test_extract_text_from_json_response(self) -> None:
        self.assertEqual(_extract_text('{"text":"hello"}'), "hello")

    def test_keyterms_are_split_for_repeated_form_fields(self) -> None:
        self.assertEqual(_keyterms("Arc Forge\nOpenBao,Pixel Forge"), ["Arc Forge", "OpenBao", "Pixel Forge"])

    def test_transcribe_posts_audio_to_configured_endpoint(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):  # noqa: ANN001
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = request.data
            captured["timeout"] = timeout
            return _FakeResponse()

        audio = np.zeros(1600, dtype=np.float32)
        with patch.dict(
            "os.environ",
            {
                "DICTATE_XAI_API_KEY": "test-key",
                "DICTATE_XAI_BASE_URL": "https://example.test/v1",
            },
            clear=False,
        ):
            stt = XAISpeechToText(model_name="grok-speech-to-text")
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                text = stt.transcribe(audio, language="en", hotwords="Arc Forge\nOpenBao")

        self.assertEqual(text, "hello world")
        self.assertEqual(captured["url"], "https://example.test/v1/stt")
        self.assertIn("Bearer test-key", captured["headers"]["Authorization"])
        body = captured["body"]
        self.assertIn(b'name="format"', body)
        self.assertIn(b"true", body)
        self.assertIn(b'name="language"', body)
        self.assertIn(b"en", body)
        self.assertEqual(body.count(b'name="keyterm"'), 2)
        self.assertIn(b"Arc Forge", body)
        self.assertIn(b"OpenBao", body)

    def test_api_key_can_come_from_command(self) -> None:
        with patch.dict(
            "os.environ",
            {"DICTATE_XAI_API_KEY_COMMAND": "/usr/bin/printf command-key"},
            clear=True,
        ):
            self.assertTrue(xai_api_key_available())


if __name__ == "__main__":
    unittest.main()
