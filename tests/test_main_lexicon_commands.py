from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import __main__ as main_module
from dictate.config import Config
from dictate.sync import SyncSettingsStore, decrypt_record


class MainLexiconCommandTests(unittest.TestCase):
    def test_add_lexicon_replacement_rejects_invalid_item(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--add-lexicon-replacement", "invalid"])

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = main_module._handle_hotword_commands(args)

        self.assertEqual(result, 2)
        self.assertIn("Invalid --add-lexicon-replacement", stderr.getvalue())

    def test_add_lexicon_replacement_calls_config_helper(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(
            [
                "--add-lexicon-replacement",
                "kinneri=canary",
                "--add-lexicon-replacement",
                "acme-widgit=AcmeWidget",
            ]
        )

        stderr = io.StringIO()
        with patch("dictate.__main__.add_lexicon_replacements", return_value={"kinneri": "canary"}) as add_fn:
            with contextlib.redirect_stderr(stderr):
                result = main_module._handle_hotword_commands(args)

        self.assertEqual(result, 0)
        add_fn.assert_called_once_with(
            {
                "kinneri": "canary",
                "acme-widgit": "AcmeWidget",
            }
        )

    def test_cli_hotword_add_enqueues_encrypted_lexicon_record_when_sync_enabled(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--add-hotword", "OpenClaw"])

        with tempfile.TemporaryDirectory() as d:
            settings = _sync_settings(Path(d))
            settings.enable("acct_cli", account_key=b"1" * 32, device_id="device_cli")
            outbox = settings.outbox()
            assert outbox is not None

            with patch("dictate.__main__.add_hotwords", return_value=["OpenClaw"]):
                with patch("dictate.__main__._sync_cli_outbox", return_value=outbox):
                    result = main_module._handle_hotword_commands(args)

            self.assertEqual(result, 0)
            pending = outbox.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].collection, "lexicon")
            self.assertFalse(pending[0].deleted)
            payload = decrypt_record("acct_cli", settings.account_key(), pending[0])
            self.assertEqual(payload["kind"], "hotword")
            self.assertEqual(payload["term"], "OpenClaw")

    def test_cli_replacement_remove_enqueues_encrypted_tombstone_when_sync_enabled(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--remove-lexicon-replacement", "openc law"])

        with tempfile.TemporaryDirectory() as d:
            settings = _sync_settings(Path(d))
            settings.enable("acct_cli", account_key=b"2" * 32, device_id="device_cli")
            outbox = settings.outbox()
            assert outbox is not None

            with patch("dictate.__main__.remove_lexicon_replacements", return_value=["openc law"]):
                with patch("dictate.__main__._sync_cli_outbox", return_value=outbox):
                    result = main_module._handle_hotword_commands(args)

            self.assertEqual(result, 0)
            pending = outbox.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].collection, "lexicon")
            self.assertTrue(pending[0].deleted)
            payload = decrypt_record("acct_cli", settings.account_key(), pending[0])
            self.assertEqual(payload["kind"], "replacement")
            self.assertEqual(payload["wrong"], "openc law")
            self.assertEqual(payload["right"], "")

    def test_list_lexicon_replacements_prints_rows(self) -> None:
        parser = main_module.build_parser()
        args = parser.parse_args(["--list-lexicon-replacements"])

        stdout = io.StringIO()
        with patch(
            "dictate.__main__.load_config",
            return_value=Config(lexicon_replacements={"kinneri": "canary"}),
        ):
            with contextlib.redirect_stdout(stdout):
                result = main_module._handle_hotword_commands(args)

        self.assertEqual(result, 0)
        self.assertIn("kinneri -> canary", stdout.getvalue())


def _sync_settings(base: Path) -> SyncSettingsStore:
    keys: dict[str, str] = {}
    return SyncSettingsStore(
        path=base / "sync-state.json",
        device_path=base / "sync-device.json",
        outbox_path=base / "sync-outbox.jsonl",
        save_key=lambda account_id, value: keys.__setitem__(account_id, value),
        read_key=lambda account_id: keys.get(account_id),
        clear_key=lambda account_id: keys.pop(account_id, None),
    )


if __name__ == "__main__":
    unittest.main()
