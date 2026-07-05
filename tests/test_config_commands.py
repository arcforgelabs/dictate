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

    def test_set_meeting_model_defaults_to_parakeet_pyannote_backend(self) -> None:
        with patch("dictate.__main__.set_meeting_stt_selection") as mock_sel:
            code, out, _ = _run_config(["set-meeting-model", "parakeet-tdt-0.6b-v2"])
        self.assertEqual(code, 0)
        mock_sel.assert_called_once_with("parakeet-pyannote", "parakeet-tdt-0.6b-v2")
        self.assertIn("meeting_model=parakeet-tdt-0.6b-v2", out)

    def test_set_meeting_model_accepts_backend_prefix(self) -> None:
        with patch("dictate.__main__.set_meeting_stt_selection") as mock_sel:
            code, out, _ = _run_config(
                ["set-meeting-model", "parakeet-pyannote/parakeet-tdt-0.6b-v3"]
            )
        self.assertEqual(code, 0)
        mock_sel.assert_called_once_with("parakeet-pyannote", "parakeet-tdt-0.6b-v3")
        self.assertIn("parakeet-pyannote", out)

    def test_set_meeting_model_rejects_unknown_backend(self) -> None:
        code, _, err = _run_config(["set-meeting-model", "unknown/model"])
        self.assertEqual(code, 1)
        self.assertIn("unknown meeting backend", err)


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
        self.assertIn("meeting_model: parakeet-pyannote/parakeet-tdt-0.6b-v2", out)
        self.assertIn("update_channel: stable", out)
        self.assertIn("not-set", out)

    def test_show_redacts_hotword_values(self) -> None:
        from dictate.config import Config

        cfg = Config(
            stt_backend="faster-whisper",
            hotwords=["PrivateProject", "PatientSurname"],
        )
        with patch("dictate.__main__.load_config", return_value=cfg):
            with patch("dictate.api_keys.has_stored_api_key", return_value=False):
                with patch("dictate.api_keys.secret_store_available", return_value=True):
                    code, out, _ = _run_config(["show"])

        self.assertEqual(code, 0)
        self.assertIn("hotwords: 2 configured terms", out)
        self.assertNotIn("PrivateProject", out)
        self.assertNotIn("PatientSurname", out)

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

    def test_set_update_channel_unstable(self) -> None:
        with patch("dictate.__main__.set_update_channel", return_value="unstable") as mock_set:
            code, out, _ = _run_config(["set-update-channel", "unstable"])
        self.assertEqual(code, 0)
        mock_set.assert_called_once_with("unstable")
        self.assertIn("update_channel=unstable", out)

    def test_set_update_channel_invalid_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            _run_config(["set-update-channel", "nightly"])

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


class ConfigDailySettingsTests(unittest.TestCase):
    """CLI parity for the settings the GUI no longer exposes: shortcut, hotwords,
    theme, startup, behaviour."""

    def test_set_shortcut_valid(self) -> None:
        with patch("dictate.config.set_push_to_talk_combo") as m:
            code, out, _ = _run_config(["set-shortcut", "ctrl+d"])
        self.assertEqual(code, 0)
        self.assertIn("ctrl+d", out)
        m.assert_called_once()

    def test_set_shortcut_invalid_rejected(self) -> None:
        from dictate.hotkey import HotkeyParseError

        with patch(
            "dictate.hotkey.normalize_push_to_talk_combo",
            side_effect=HotkeyParseError("bad"),
        ):
            code, _, err = _run_config(["set-shortcut", "%%%"])
        self.assertEqual(code, 1)
        self.assertIn("error", err.lower())

    def test_hotwords_list(self) -> None:
        from dictate.config import Config

        with patch("dictate.__main__.load_config", return_value=Config(hotwords=["Foo", "Bar"])):
            code, out, _ = _run_config(["hotwords"])
        self.assertEqual(code, 0)
        self.assertIn("Foo", out)
        self.assertIn("Bar", out)

    def test_hotwords_add(self) -> None:
        from dictate.config import Config

        with patch("dictate.__main__.add_hotwords") as add, patch(
            "dictate.__main__.load_config", return_value=Config(hotwords=["Baz"])
        ), patch("dictate.__main__._sync_cli_outbox", return_value=None):
            code, out, _ = _run_config(["hotwords", "--add", "Baz"])
        self.assertEqual(code, 0)
        add.assert_called_once_with(["Baz"])

    def test_hotwords_clear(self) -> None:
        from dictate.config import Config

        with patch("dictate.__main__.remove_hotwords") as rm, patch(
            "dictate.__main__.load_config", return_value=Config(hotwords=["X", "Y"])
        ), patch("dictate.__main__._sync_cli_outbox", return_value=None):
            code, out, _ = _run_config(["hotwords", "--clear"])
        self.assertEqual(code, 0)
        rm.assert_called_once_with(["X", "Y"])
        self.assertIn("cleared", out)

    def test_set_theme_persists_pref(self) -> None:
        with patch("dictate.__main__._config_set_ui_pref") as m:
            code, out, _ = _run_config(["set-theme", "dark"])
        self.assertEqual(code, 0)
        m.assert_called_once_with("theme", "dark")

    def test_set_theme_invalid_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            _run_config(["set-theme", "blue"])

    def test_set_startup_on(self) -> None:
        with patch("dictate.startup.set_startup_enabled") as m:
            code, out, _ = _run_config(["set-startup", "on"])
        self.assertEqual(code, 0)
        m.assert_called_once_with(True)

    def test_set_behavior_tray(self) -> None:
        with patch("dictate.__main__._config_set_ui_pref") as m:
            code, out, _ = _run_config(["set-behavior", "tray", "off"])
        self.assertEqual(code, 0)
        m.assert_called_once_with("trayOnly", False)
