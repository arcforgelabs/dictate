from __future__ import annotations

import subprocess
import unittest
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

    def test_no_secret_tool_reports_unavailable(self) -> None:
        with (
            patch("dictate.api_keys._is_windows", return_value=False),
            patch("dictate.api_keys.shutil.which", return_value=None),
        ):
            self.assertFalse(api_keys.secret_store_available())
            self.assertIsNone(api_keys.read_api_key("openai"))
            with self.assertRaises(api_keys.ApiKeyStorageError):
                api_keys.save_api_key("openai", "secret")

    def test_backend_rejects_unknown_provider(self) -> None:
        with self.assertRaises(api_keys.ApiKeyStorageError):
            api_keys.save_api_key("not-a-provider", "secret")

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


if __name__ == "__main__":
    unittest.main()
