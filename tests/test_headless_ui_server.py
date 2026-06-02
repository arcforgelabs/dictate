from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from dictate.__main__ import _maybe_start_ui_server


class HeadlessUiServerGateTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("dictate.ui_server.serve") as serve:
                self.assertIsNone(_maybe_start_ui_server(object()))
                serve.assert_not_called()

    def test_starts_when_env_set(self) -> None:
        sentinel = object()
        with patch.dict(os.environ, {"DICTATE_UI_SERVER": "1"}, clear=True):
            with patch("dictate.ui_server.serve", return_value=sentinel) as serve:
                self.assertIs(_maybe_start_ui_server(object()), sentinel)
                serve.assert_called_once()

    def test_server_failure_is_swallowed(self) -> None:
        with patch.dict(os.environ, {"DICTATE_UI_SERVER": "1"}, clear=True):
            with patch("dictate.ui_server.serve", side_effect=RuntimeError("boom")):
                # must not raise — dictation continues even if the server fails
                self.assertIsNone(_maybe_start_ui_server(object()))


if __name__ == "__main__":
    unittest.main()
