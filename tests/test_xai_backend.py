from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import numpy as np
from dictate.config import Config

from dictate.stt.xai_backend import (
    XAISpeechToText,
    _api_key_from_command,
    _extract_diarized_text,
    _extract_text,
    xai_api_key_available,
    _keyterms,
)


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self) -> bytes:
        return json.dumps({"text": "hello world", "duration": 1.2}).encode("utf-8")


class _FakeDiarizedResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {
                "text": "hello there yes",
                "duration": 1.2,
                "words": [
                    {"text": "hello", "start": 0.0, "end": 0.2, "speaker": 0},
                    {"text": "there", "start": 0.2, "end": 0.5, "speaker": 0},
                    {"text": "yes", "start": 0.6, "end": 0.8, "speaker": 1},
                ],
            }
        ).encode("utf-8")


class XAIBackendTests(unittest.TestCase):
    def test_extract_text_from_json_response(self) -> None:
        self.assertEqual(_extract_text('{"text":"hello"}'), "hello")

    def test_keyterms_are_split_for_repeated_form_fields(self) -> None:
        self.assertEqual(_keyterms("AcmeWidget\nProjectNova,TeamAtlas"), ["AcmeWidget", "ProjectNova", "TeamAtlas"])

    def test_extract_diarized_text_groups_speaker_turns(self) -> None:
        response = json.dumps(
            {
                "text": "hello there yes",
                "words": [
                    {"text": "hello", "speaker": 3},
                    {"text": "there", "speaker": 3},
                    {"text": "yes", "speaker": 8},
                    {"text": "!", "speaker": 8},
                ],
            }
        )
        self.assertEqual(
            _extract_diarized_text(response),
            "Speaker 1: hello there\nSpeaker 2: yes!",
        )

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
                text = stt.transcribe(audio, language="en", hotwords="AcmeWidget\nProjectNova")

        self.assertEqual(text, "hello world")
        self.assertEqual(captured["url"], "https://example.test/v1/stt")
        self.assertIn("Bearer test-key", captured["headers"]["Authorization"])
        body = captured["body"]
        self.assertIn(b'name="format"', body)
        self.assertIn(b"true", body)
        self.assertIn(b'name="language"', body)
        self.assertIn(b"en", body)
        self.assertEqual(body.count(b'name="keyterm"'), 2)
        self.assertIn(b"AcmeWidget", body)
        self.assertIn(b"ProjectNova", body)

    def test_transcribe_diarized_requests_diarization(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):  # noqa: ANN001
            captured["body"] = request.data
            return _FakeDiarizedResponse()

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
                text = stt.transcribe_diarized(audio, language="en", hotwords="AcmeWidget")

        self.assertEqual(text, "Speaker 1: hello there\nSpeaker 2: yes")
        body = captured["body"]
        self.assertIn(b'name="diarize"', body)
        self.assertIn(b"true", body)
        self.assertEqual(body.count(b'name="keyterm"'), 1)

    def test_api_key_can_come_from_command(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"DICTATE_XAI_API_KEY_COMMAND": "dictate-xai-key"},
                clear=True,
            ),
            patch("dictate.stt.xai_backend._api_key_from_command", return_value="command-key"),
            patch("dictate.stt.xai_backend.read_api_key", return_value=None),
        ):
            self.assertTrue(xai_api_key_available())

    def test_api_key_command_uses_non_posix_split_on_windows(self) -> None:
        """On Windows, backslash paths in the command must survive shlex.split intact."""
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="command-key\n", stderr="")

        with (
            patch.dict(
                "os.environ",
                {"DICTATE_XAI_API_KEY_COMMAND": r"C:\Tools\getkey.exe --arg"},
                clear=True,
            ),
            patch("dictate.stt.xai_backend.os.name", "nt"),
            patch("dictate.stt.xai_backend.subprocess.run", side_effect=fake_run),
        ):
            result = _api_key_from_command()

        self.assertEqual(captured["argv"], [r"C:\Tools\getkey.exe", "--arg"])
        self.assertEqual(result, "command-key")

    def test_cloud_router_prefers_pro_and_falls_back_to_personal_key(self) -> None:
        stt = XAISpeechToText()
        with (
            patch("dictate.stt.xai_backend.load_config", return_value=Config(cloud_provider_preference="pro-first")),
            patch.object(stt, "_transcribe_pro", side_effect=RuntimeError("Pro unavailable")) as pro,
            patch.object(stt, "_transcribe_personal", return_value="personal result") as personal,
        ):
            result = stt.transcribe(np.zeros(1600, dtype=np.float32))
        self.assertEqual(result, "personal result")
        pro.assert_called_once()
        personal.assert_called_once()

    def test_cloud_router_can_prefer_personal_key(self) -> None:
        stt = XAISpeechToText()
        with (
            patch("dictate.stt.xai_backend.load_config", return_value=Config(cloud_provider_preference="personal-first")),
            patch.object(stt, "_transcribe_personal", return_value="personal result") as personal,
            patch.object(stt, "_transcribe_pro") as pro,
        ):
            result = stt.transcribe(np.zeros(1600, dtype=np.float32))
        self.assertEqual(result, "personal result")
        personal.assert_called_once()
        pro.assert_not_called()


if __name__ == "__main__":
    unittest.main()
