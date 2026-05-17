from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from dictate import __main__ as main_module


class MainPrepareDispatchTests(unittest.TestCase):
    def test_prepare_subcommand_dispatches_to_prepare_runner(self) -> None:
        with patch("dictate.__main__.run_prepare_model", return_value=9) as run_prepare_model:
            result = main_module.main(
                [
                    "prepare-model",
                    "--stt-backend",
                    "faster-whisper",
                    "--model",
                    "turbo",
                ]
            )
        self.assertEqual(result, 9)
        run_prepare_model.assert_called_once_with(
            [
                "--stt-backend",
                "faster-whisper",
                "--model",
                "turbo",
            ]
        )

    def test_main_with_logging_bypasses_wrapper_when_env_flag_is_set(self) -> None:
        with patch.dict(os.environ, {"DICTATE_DISABLE_STARTUP_LOG": "1"}, clear=False):
            with patch("dictate.__main__.main", return_value=4) as main_fn:
                result = main_module.main_with_logging()
        self.assertEqual(result, 4)
        main_fn.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
