from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from dictate.__main__ import _maybe_start_ui_server


class HeadlessUiServerGateTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("dictate.ui_launcher.ensure_server_started") as start:
                self.assertIsNone(_maybe_start_ui_server(object()))
                start.assert_not_called()

    def test_starts_when_env_set(self) -> None:
        sentinel = object()
        daemon = object()
        with patch.dict(os.environ, {"DICTATE_UI_SERVER": "1"}, clear=True):
            with patch("dictate.ui_launcher.ensure_server_started", return_value=sentinel) as start:
                self.assertIs(_maybe_start_ui_server(daemon), sentinel)
                start.assert_called_once_with(daemon)

    def test_server_failure_is_swallowed(self) -> None:
        with patch.dict(os.environ, {"DICTATE_UI_SERVER": "1"}, clear=True):
            with patch("dictate.ui_launcher.ensure_server_started", side_effect=RuntimeError("boom")):
                # must not raise — dictation continues even if the server fails
                self.assertIsNone(_maybe_start_ui_server(object()))


if __name__ == "__main__":
    unittest.main()
