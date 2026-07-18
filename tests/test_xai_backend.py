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
            with (
                patch("urllib.request.urlopen", side_effect=fake_urlopen),
                patch(
                    "dictate.stt.xai_backend.load_config",
                    return_value=Config(cloud_provider_preference="personal-first"),
                ),
            ):
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
            with (
                patch("urllib.request.urlopen", side_effect=fake_urlopen),
                patch(
                    "dictate.stt.xai_backend.load_config",
                    return_value=Config(cloud_provider_preference="personal-first"),
                ),
            ):
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
            # The split now happens inside dictate.api_keys.split_api_key_command,
            # so os.name is read from that module, not xai_backend's.
            patch("dictate.api_keys.os.name", "nt"),
            patch("dictate.stt.xai_backend.subprocess.run", side_effect=fake_run),
        ):
            result = _api_key_from_command()

        self.assertEqual(captured["argv"], [r"C:\Tools\getkey.exe", "--arg"])
        self.assertEqual(result, "command-key")

    def test_api_key_command_strips_quotes_on_windows(self) -> None:
        """A quoted command (that worked under the old posix=True split) must
        still work now that Windows uses posix=False for backslash paths."""
        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return subprocess.CompletedProcess(args=argv, returncode=0, stdout="command-key\n", stderr="")

        with (
            patch.dict(
                "os.environ",
                {"DICTATE_XAI_API_KEY_COMMAND": r'"C:\Program Files\getkey.exe" --arg'},
                clear=True,
            ),
            patch("dictate.api_keys.os.name", "nt"),
            patch("dictate.stt.xai_backend.subprocess.run", side_effect=fake_run),
        ):
            result = _api_key_from_command()

        self.assertEqual(captured["argv"], [r"C:\Program Files\getkey.exe", "--arg"])
        self.assertEqual(result, "command-key")

    def test_cloud_router_never_falls_back_from_pro_to_personal_key(self) -> None:
        stt = XAISpeechToText()
        with (
            patch(
                "dictate.stt.xai_backend.load_config",
                return_value=Config(cloud_provider_preference="pro-first"),
            ),
            patch.object(
                stt, "_transcribe_pro", side_effect=RuntimeError("Pro unavailable")
            ) as pro,
            patch.object(stt, "_transcribe_personal", return_value="personal result") as personal,
        ):
            with self.assertRaisesRegex(RuntimeError, "Pro unavailable"):
                stt.transcribe(np.zeros(1600, dtype=np.float32))
        pro.assert_called_once()
        personal.assert_not_called()

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

    def test_hosted_pro_consumes_encrypted_result_without_plaintext_route(self) -> None:
        class FakeProClient:
            def __init__(self) -> None:
                self.key_registered = False
                self.created: dict[str, object] | None = None
                self.consumed: dict[str, str] | None = None
                self.accepted: list[str] = []

            def get_state(self):  # noqa: ANN201
                return {"signedIn": True, "entitlements": {"active": True}}

            def ensure_hosted_result_key(self) -> None:
                self.key_registered = True

            def create_meeting(self, **kwargs):  # noqa: ANN003, ANN201
                self.created = kwargs
                return {
                    "job": {
                        "job_id": "job_1",
                        "request_id": "request_1",
                        "correlation_id": "correlation_1",
                    }
                }

            def upload_meeting_audio(self, job_id, path):  # noqa: ANN001, ANN201
                return {"job_id": job_id, "path": str(path)}

            def get_meeting(self, job_id):  # noqa: ANN001, ANN201
                return {"job": {"job_id": job_id, "state": "completed"}}

            def consume_hosted_result(self, job_id, *, request_id, correlation_id):  # noqa: ANN001, ANN201
                self.consumed = {
                    "job_id": job_id,
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                }
                return {"text": "encrypted transcript"}

            def get_transcript(self, job_id):  # noqa: ANN001, ANN201
                raise AssertionError(f"plaintext transcript route called for {job_id}")

            def accept_hosted_result(self, job_id: str) -> None:
                self.accepted.append(job_id)

        client = FakeProClient()
        stt = XAISpeechToText()
        with (
            patch("dictate.stt.xai_backend.ProClient", return_value=client),
            patch(
                "dictate.stt.xai_backend.load_config",
                return_value=Config(cloud_provider_preference="pro-first"),
            ),
        ):
            result = stt.transcribe(np.zeros(1600, dtype=np.float32), language="en")

        self.assertEqual(result, "encrypted transcript")
        self.assertTrue(client.key_registered)
        self.assertEqual(client.created["requested_diarization"], False)
        self.assertEqual(
            client.consumed,
            {"job_id": "job_1", "request_id": "request_1", "correlation_id": "correlation_1"},
        )
        self.assertEqual(client.accepted, ["job_1"])

    def test_default_diarized_route_is_managed_and_has_no_personal_fallback(self) -> None:
        stt = XAISpeechToText()
        with (
            patch(
                "dictate.stt.xai_backend.load_config",
                return_value=Config(cloud_provider_preference="pro-first"),
            ),
            patch.object(stt, "_transcribe_pro", return_value="managed diarized") as pro,
            patch.object(stt, "_transcribe_personal_diarized") as personal,
        ):
            result = stt.transcribe_diarized(np.zeros(1600, dtype=np.float32))
        self.assertEqual(result, "managed diarized")
        self.assertTrue(pro.call_args.kwargs["requested_diarization"])
        personal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
