from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dictate.stt.openai_backend import (
    OpenAISpeechToText,
    _api_key,
    _extract_text,
    openai_api_key_available,
)


def _print_command(value: str) -> str:
    python = Path(sys.executable).as_posix()
    return f'{python} -c "import sys; sys.stdout.write({value!r})"'


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self) -> bytes:
        return json.dumps({"text": "hello world"}).encode("utf-8")


class OpenAIBackendTests(unittest.TestCase):
    def test_extract_text_from_json_response(self) -> None:
        self.assertEqual(_extract_text('{"text":"hello"}'), "hello")

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
                "DICTATE_OPENAI_API_KEY": "test-key",
                "DICTATE_OPENAI_BASE_URL": "https://example.test/v1",
            },
            clear=False,
        ):
            stt = OpenAISpeechToText(model_name="gpt-4o-mini-transcribe")
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                text = stt.transcribe(audio, language="en", prompt_context="Use Arc Forge terms.")

        self.assertEqual(text, "hello world")
        self.assertEqual(captured["url"], "https://example.test/v1/audio/transcriptions")
        self.assertIn("Bearer test-key", captured["headers"]["Authorization"])
        body = captured["body"]
        self.assertIn(b'name="model"', body)
        self.assertIn(b"gpt-4o-mini-transcribe", body)
        self.assertIn(b'name="language"', body)
        self.assertIn(b"en", body)
        self.assertIn(b'name="prompt"', body)
        self.assertIn(b"Use Arc Forge terms.", body)

    def test_api_key_can_come_from_command(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"DICTATE_OPENAI_API_KEY_COMMAND": _print_command("command-key")},
                clear=True,
            ),
            patch("dictate.stt.openai_backend.read_api_key", return_value=None),
        ):
            self.assertTrue(openai_api_key_available())

    def test_api_key_command_still_works_without_secret_tool(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"DICTATE_OPENAI_API_KEY_COMMAND": _print_command("command-key")},
                clear=True,
            ),
            patch("dictate.api_keys.shutil.which", return_value=None),
        ):
            self.assertTrue(openai_api_key_available())

    def test_api_key_command_takes_precedence_over_os_stored_key(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"DICTATE_OPENAI_API_KEY_COMMAND": _print_command("command-key")},
                clear=True,
            ),
            patch("dictate.stt.openai_backend.read_api_key", return_value="stored-key"),
        ):
            self.assertEqual(_api_key(), "command-key")


if __name__ == "__main__":
    unittest.main()
