"""Tests for `dictate config` subcommands."""

from __future__ import annotations

import io
import sys
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from dictate import __main__ as main_module
from dictate.config import load_config, CONFIG_PATH


def _run_config(argv: list[str]) -> tuple[int, str, str]:
    """Run `_handle_config_commands(argv)` and capture stdout/stderr."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main_module._handle_config_commands(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class ConfigSetKeyTests(unittest.TestCase):
    """set-key subcommand."""

    def test_invalid_backend_rejected(self) -> None:
        # argparse will error before our code runs — SystemExit raised
        with self.assertRaises(SystemExit):
            _run_config(["set-key", "unknown-backend", "xai-abc123"])

    def test_invalid_key_format_rejected(self) -> None:
        # Bad xai key format (doesn't match xai-... pattern)
        code, out, err = _run_config(["set-key", "xai", "not-a-valid-key"])
        self.assertEqual(code, 1)
        self.assertIn("error", err.lower())

    def test_valid_xai_key_saved(self) -> None:
        with patch("dictate.api_keys.save_api_key") as mock_save:
            code, out, err = _run_config(["set-key", "xai", "xai-ABCDEFGHIJKLMNOPQRSTUVWXYZ"])
        self.assertEqual(code, 0)
        self.assertIn("ok", out)
        self.assertIn("xai", out)
        mock_save.assert_called_once_with("xai", "xai-ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def test_valid_openai_key_saved(self) -> None:
        with patch("dictate.api_keys.save_api_key") as mock_save:
            code, out, _ = _run_config(["set-key", "openai", "sk-ABCDEFGHIJKLMNOPQRSTU"])
        self.assertEqual(code, 0)
        mock_save.assert_called_once_with("openai", "sk-ABCDEFGHIJKLMNOPQRSTU")

    def test_save_error_returns_1(self) -> None:
        with patch("dictate.api_keys.save_api_key", side_effect=RuntimeError("keyring unavailable")):
            code, _, err = _run_config(["set-key", "xai", "xai-ABCDEFGHIJKLMNOPQRSTUVWXYZ"])
        self.assertEqual(code, 1)
        self.assertIn("error", err.lower())


class ConfigSetProviderTests(unittest.TestCase):
    """set-provider subcommand."""

    def test_set_provider_private(self) -> None:
        with patch("dictate.__main__.set_stt_backend") as mock_set:
            code, out, _ = _run_config(["set-provider", "private"])
        self.assertEqual(code, 0)
        mock_set.assert_called_once_with("faster-whisper")
        self.assertIn("private", out)

    def test_set_provider_online(self) -> None:
        with patch("dictate.__main__.set_stt_backend") as mock_set:
            code, out, _ = _run_config(["set-provider", "online"])
        self.assertEqual(code, 0)
        mock_set.assert_called_once_with("xai")
        self.assertIn("online", out)

    def test_invalid_mode_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            _run_config(["set-provider", "bogus"])


class ConfigSetModelTests(unittest.TestCase):
    """set-model subcommand."""

    def test_set_model_persists(self) -> None:
        from dictate.config import Config
        with patch("dictate.__main__.load_config", return_value=Config(stt_backend="xai")):
            with patch("dictate.__main__.set_stt_selection") as mock_sel:
                code, out, _ = _run_config(["set-model", "grok-speech-to-text"])
        self.assertEqual(code, 0)
        mock_sel.assert_called_once_with("xai", "grok-speech-to-text")
        self.assertIn("grok-speech-to-text", out)

    def test_set_model_defaults_to_faster_whisper_backend(self) -> None:
        """When no backend is configured, falls back to faster-whisper."""
        from dictate.config import Config
        with patch("dictate.__main__.load_config", return_value=Config(stt_backend=None)):
            with patch("dictate.__main__.set_stt_selection") as mock_sel:
                code, _, _ = _run_config(["set-model", "turbo"])
        self.assertEqual(code, 0)
        mock_sel.assert_called_once_with("faster-whisper", "turbo")


class ConfigShowTests(unittest.TestCase):
    """show subcommand."""

    def test_show_private_provider(self) -> None:
        from dictate.config import Config
        with patch("dictate.__main__.load_config", return_value=Config(stt_backend="faster-whisper", stt_model="turbo")):
            with patch("dictate.api_keys.has_stored_api_key", return_value=False):
                with patch("dictate.api_keys.secret_store_available", return_value=True):
                    code, out, _ = _run_config(["show"])
        self.assertEqual(code, 0)
        self.assertIn("private", out)
        self.assertIn("faster-whisper", out)
        self.assertIn("not-set", out)

    def test_show_online_provider_with_key(self) -> None:
        from dictate.config import Config

        def _has_key(b):
            return b == "xai"

        with patch("dictate.__main__.load_config", return_value=Config(stt_backend="xai")):
            with patch("dictate.api_keys.has_stored_api_key", side_effect=_has_key):
                with patch("dictate.api_keys.secret_store_available", return_value=True):
                    code, out, _ = _run_config(["show"])
        self.assertEqual(code, 0)
        self.assertIn("online", out)
        self.assertIn("xai", out)
        # xai should show "set"; others "not-set"
        lines = out.splitlines()
        xai_line = next((l for l in lines if "key.xai" in l), "")
        self.assertIn("set", xai_line)

    def test_show_no_subcommand_returns_2(self) -> None:
        code, _, _ = _run_config([])
        self.assertEqual(code, 2)

    def test_main_dispatches_config_subcommand(self) -> None:
        """main() with 'config show' argv dispatches to _handle_config_commands."""
        from dictate.config import Config
        with patch("dictate.__main__.load_config", return_value=Config()):
            with patch("dictate.api_keys.has_stored_api_key", return_value=False):
                with patch("dictate.api_keys.secret_store_available", return_value=False):
                    code = main_module.main(["config", "show"])
        self.assertEqual(code, 0)
