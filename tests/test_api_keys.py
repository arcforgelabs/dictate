from __future__ import annotations

import subprocess
import tempfile
import unittest
import urllib.error
import os
from pathlib import Path
from contextlib import redirect_stderr
from io import BytesIO, StringIO
from unittest.mock import patch

from dictate import api_keys


class ApiKeysTests(unittest.TestCase):
    def test_secret_tool_store_receives_secret_via_stdin(self) -> None:
        calls = []

        def fake_run(args, **kwargs):  # noqa: ANN001
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args=args, returncode=0, stderr="", stdout="")

        with (
            patch("dictate.api_keys._is_windows", return_value=False),
            patch("dictate.api_keys.shutil.which", return_value="/usr/bin/secret-tool"),
            patch("dictate.api_keys.subprocess.run", side_effect=fake_run),
        ):
            api_keys.save_api_key("openai", " secret-value ")

        args, kwargs = calls[0]
        self.assertEqual(args[0:3], ["/usr/bin/secret-tool", "store", "--label"])
        self.assertIn("backend", args)
        self.assertIn("openai", args)
        self.assertEqual(kwargs["input"], "secret-value")
        self.assertNotIn("secret-value", args)

    def test_secret_tool_lookup_returns_trimmed_secret(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["secret-tool"],
            returncode=0,
            stderr="",
            stdout=" stored-key\n",
        )
        with (
            patch("dictate.api_keys._is_windows", return_value=False),
            patch("dictate.api_keys.shutil.which", return_value="/usr/bin/secret-tool"),
            patch("dictate.api_keys.subprocess.run", return_value=completed),
        ):
            self.assertEqual(api_keys.read_api_key("xai"), "stored-key")

    def test_secret_tool_lookup_miss_returns_none(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["secret-tool"],
            returncode=1,
            stderr="not found",
            stdout="",
        )
        with (
            patch("dictate.api_keys._is_windows", return_value=False),
            patch("dictate.api_keys.shutil.which", return_value="/usr/bin/secret-tool"),
            patch("dictate.api_keys.subprocess.run", return_value=completed),
        ):
            self.assertIsNone(api_keys.read_api_key("gemini"))

    def test_secret_tool_timeout_raises_storage_error(self) -> None:
        with (
            patch("dictate.api_keys._is_windows", return_value=False),
            patch("dictate.api_keys.shutil.which", return_value="/usr/bin/secret-tool"),
            patch(
                "dictate.api_keys.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["secret-tool"], timeout=20),
            ),
        ):
            with self.assertRaises(api_keys.ApiKeyStorageError):
                api_keys.save_api_key("openai", "secret")

    def test_no_secret_tool_uses_private_local_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            fallback = Path(d) / "api-keys.json"
            with (
                patch("dictate.api_keys._is_windows", return_value=False),
                patch("dictate.api_keys.shutil.which", return_value=None),
                patch("dictate.api_keys.LOCAL_API_KEYS_PATH", fallback),
            ):
                self.assertTrue(api_keys.secret_store_available())
                api_keys.save_api_key("openai", " secret ")
                self.assertEqual(api_keys.read_api_key("openai"), "secret")
                if os.name != "nt":
                    self.assertEqual(fallback.stat().st_mode & 0o777, 0o600)
                api_keys.clear_api_key("openai")
                self.assertIsNone(api_keys.read_api_key("openai"))

    def test_no_secret_tool_description_reports_local_fallback(self) -> None:
        with (
            patch("dictate.api_keys._is_windows", return_value=False),
            patch("dictate.api_keys.shutil.which", return_value=None),
        ):
            self.assertIn("private local key file", api_keys.secret_store_description())

    def test_backend_rejects_unknown_provider(self) -> None:
        with self.assertRaises(api_keys.ApiKeyStorageError):
            api_keys.save_api_key("not-a-provider", "secret")

    def test_api_key_status_reports_none_without_configured_key(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("dictate.api_keys.read_api_key", return_value=None),
        ):
            status = api_keys.api_key_status("xai")

        self.assertEqual(status.status, "None")

    def test_xai_key_format_requires_xai_prefix(self) -> None:
        self.assertIsNone(api_keys.validate_api_key_format("xai", "xai-" + "abc1234567890123456"))
        self.assertIsNotNone(api_keys.validate_api_key_format("xai", "sk-" + "abc1234567890123456"))

    def test_custom_openai_base_url_allows_non_openai_bearer_token(self) -> None:
        with patch.dict("os.environ", {"DICTATE_OPENAI_BASE_URL": "https://proxy.test/v1"}):
            self.assertIsNone(api_keys.validate_api_key_format("openai", "proxy-token-123"))

    def test_custom_xai_base_url_allows_non_xai_bearer_token(self) -> None:
        with patch.dict("os.environ", {"DICTATE_XAI_BASE_URL": "https://proxy.test/v1"}):
            self.assertIsNone(api_keys.validate_api_key_format("xai", "proxy-token-123"))

    def test_custom_gemini_base_url_allows_non_gemini_bearer_token(self) -> None:
        with patch.dict("os.environ", {"DICTATE_GEMINI_BASE_URL": "https://proxy.test/v1"}):
            self.assertIsNone(api_keys.validate_api_key_format("gemini", "proxy-token-123"))

    def test_custom_base_url_skips_provider_remote_validation_endpoint(self) -> None:
        with (
            patch.dict("os.environ", {"DICTATE_OPENAI_BASE_URL": "https://proxy.test/v1"}),
            patch("dictate.api_keys.request.urlopen") as urlopen,
        ):
            status = api_keys.api_key_status(
                "openai",
                api_key="proxy-token-123",
                validate_remote=True,
            )

        self.assertEqual(status.status, "Ready")
        urlopen.assert_not_called()

    def test_status_can_skip_api_key_commands_for_ui_rendering(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {"DICTATE_XAI_API_KEY_COMMAND": "/usr/bin/printf xai-" + "abc1234567890123456"},
                clear=True,
            ),
            patch("dictate.api_keys.read_api_key", return_value=None),
            patch("dictate.api_keys.subprocess.run") as run,
        ):
            status = api_keys.api_key_status("xai", include_command=False)

        self.assertEqual(status.status, "None")
        run.assert_not_called()

    def test_empty_api_key_command_falls_back_to_stored_key(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["secret-command"],
            returncode=0,
            stderr="",
            stdout="\n",
        )
        with (
            patch.dict(
                "os.environ",
                {"DICTATE_XAI_API_KEY_COMMAND": "/usr/bin/printf ''"},
                clear=True,
            ),
            patch("dictate.api_keys.subprocess.run", return_value=completed),
            patch("dictate.api_keys.read_api_key", return_value="xai-" + "abc1234567890123456"),
        ):
            status = api_keys.api_key_status("xai")

        self.assertEqual(status.status, "Ready")
        self.assertEqual(status.source, "secret-store")

    def test_openai_remote_validation_uses_transcription_endpoint(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):  # noqa: ANN001
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["headers"] = dict(request.header_items())
            captured["body"] = request.data
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "missing file",
                hdrs={},
                fp=BytesIO(b'{"error":"missing file"}'),
            )

        with patch("dictate.api_keys.request.urlopen", side_effect=fake_urlopen):
            status = api_keys.api_key_status(
                "openai",
                api_key="sk-" + "abc1234567890123456",
                validate_remote=True,
            )

        self.assertEqual(status.status, "Ready")
        self.assertEqual(captured["url"], "https://api.openai.com/v1/audio/transcriptions")
        self.assertEqual(captured["method"], "POST")
        self.assertIn("Bearer sk-", captured["headers"]["Authorization"])
        self.assertIn(b'gpt-4o-mini-transcribe', captured["body"])

    def test_xai_status_validates_remote_api_key_endpoint(self) -> None:
        class FakeResponse:
            def __enter__(self):  # noqa: ANN204
                return self

            def __exit__(self, *_exc):  # noqa: ANN002
                return False

            def read(self) -> bytes:
                return (
                    b'{"api_key_blocked": false, '
                    b'"api_key_disabled": false, '
                    b'"team_blocked": false}'
                )

        captured = {}

        def fake_urlopen(request, timeout):  # noqa: ANN001
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse()

        key = "xai-" + "abc1234567890123456"
        with patch("dictate.api_keys.request.urlopen", side_effect=fake_urlopen):
            status = api_keys.api_key_status("xai", api_key=key, validate_remote=True)

        self.assertEqual(status.status, "Ready")
        self.assertEqual(captured["url"], "https://api.x.ai/v1/api-key")
        self.assertIn("Bearer xai-", captured["headers"]["Authorization"])

    def test_remote_validation_failure_logs_without_key_value(self) -> None:
        key = "xai-" + "abc1234567890123456"
        stderr = StringIO()
        with (
            patch(
                "dictate.api_keys.request.urlopen",
                side_effect=urllib.error.URLError("offline"),
            ),
            redirect_stderr(stderr),
        ):
            status = api_keys.api_key_status("xai", api_key=key, validate_remote=True)

        self.assertEqual(status.status, "Invalid")
        self.assertIn("remote", stderr.getvalue())
        self.assertNotIn(key, stderr.getvalue())

    def test_status_defaults_to_local_format_check(self) -> None:
        with patch("dictate.api_keys.request.urlopen") as urlopen:
            status = api_keys.api_key_status("xai", api_key="xai-" + "abc1234567890123456")

        self.assertEqual(status.status, "Ready")
        urlopen.assert_not_called()

    def test_gemini_remote_validation_uses_header_not_query(self) -> None:
        class FakeResponse:
            def __enter__(self):  # noqa: ANN204
                return self

            def __exit__(self, *_exc):  # noqa: ANN002
                return False

            def read(self) -> bytes:
                return b"{}"

        captured = {}

        def fake_urlopen(request, timeout):  # noqa: ANN001
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            return FakeResponse()

        key = "AIza" + "abcdefghijklmnopqrstuvwxyz"
        with patch("dictate.api_keys.request.urlopen", side_effect=fake_urlopen):
            status = api_keys.api_key_status("gemini", api_key=key, validate_remote=True)

        self.assertEqual(status.status, "Ready")
        self.assertEqual(captured["url"], "https://generativelanguage.googleapis.com/v1beta/models")
        self.assertNotIn(key, captured["url"])
        self.assertEqual(captured["headers"]["X-goog-api-key"], key)

    def test_windows_clear_ignores_missing_credential(self) -> None:
        class FakeAdvapi32:
            def CredDeleteW(self, *_args):  # noqa: ANN002, N802
                return False

        with (
            patch("dictate.api_keys._is_windows", return_value=True),
            patch("dictate.api_keys._advapi32", return_value=FakeAdvapi32()),
            patch("dictate.api_keys._windows_last_error", return_value=1168),
        ):
            api_keys.clear_api_key("openai")

    def test_windows_clear_failure_raises_storage_error(self) -> None:
        class FakeAdvapi32:
            def CredDeleteW(self, *_args):  # noqa: ANN002, N802
                return False

        with (
            patch("dictate.api_keys._is_windows", return_value=True),
            patch("dictate.api_keys._advapi32", return_value=FakeAdvapi32()),
            patch("dictate.api_keys._windows_last_error", return_value=5),
        ):
            with self.assertRaises(api_keys.ApiKeyStorageError):
                api_keys.clear_api_key("openai")


class BackendStoredKeyTests(unittest.TestCase):
    def test_openai_backend_reads_os_stored_key(self) -> None:
        from dictate.stt.openai_backend import OpenAISpeechToText

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("dictate.stt.openai_backend.read_api_key", return_value="stored-openai"),
        ):
            stt = OpenAISpeechToText()

        self.assertEqual(stt.api_key, "stored-openai")

    def test_xai_backend_reads_os_stored_key(self) -> None:
        from dictate.stt.xai_backend import XAISpeechToText

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("dictate.stt.xai_backend.read_api_key", return_value="stored-xai"),
        ):
            stt = XAISpeechToText()

        self.assertEqual(stt.api_key, "stored-xai")

    def test_gemini_backend_reads_os_stored_key(self) -> None:
        from dictate.stt.gemini_backend import GeminiSpeechToText

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("dictate.stt.gemini_backend.read_api_key", return_value="stored-gemini"),
        ):
            stt = GeminiSpeechToText()

        self.assertEqual(stt.api_key, "stored-gemini")


class ApiKeyStatusLoggingTests(unittest.TestCase):
    def test_invalid_format_logs_by_default(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            status = api_keys.api_key_status("openai", api_key="not-a-key")
        self.assertEqual(status.status, "Invalid")
        self.assertIn("validation failed for openai", stderr.getvalue())

    def test_invalid_format_is_quiet_when_log_failures_disabled(self) -> None:
        stderr = StringIO()
        with redirect_stderr(stderr):
            status = api_keys.api_key_status("openai", api_key="not-a-key", log_failures=False)
        # Status is still reported as Invalid; only the noisy log is suppressed.
        self.assertEqual(status.status, "Invalid")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
