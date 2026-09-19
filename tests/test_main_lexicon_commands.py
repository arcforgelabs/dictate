from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from dictate import __main__ as main_module
from dictate.config import Config


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


if __name__ == "__main__":
    unittest.main()
