from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from dictate.outputs import (
    ClipboardOutput,
    PasteOutput,
    WtypeOutput,
    XdotoolOutput,
    resolve_typing_backend,
)


class PasteOutputTests(unittest.TestCase):
    def test_paste_output_copies_before_sending_shortcut(self) -> None:
        clipboard = Mock()
        typing = XdotoolOutput()
        with patch("dictate.outputs._send_paste_shortcut") as shortcut:
            PasteOutput(typing, clipboard).send("complete dictation")

        clipboard.send.assert_called_once_with("complete dictation")
        shortcut.assert_called_once_with(typing, plain_text=False)

    def test_xdotool_pastes_instead_of_typing_characters(self) -> None:
        with (
            patch("dictate.outputs.command_exists", side_effect=lambda command: command == "xdotool"),
            patch("dictate.outputs.detect_session_type", return_value="x11"),
        ):
            output = resolve_typing_backend("auto")

        self.assertIsInstance(output, PasteOutput)
        self.assertIsInstance(output.typing_output, XdotoolOutput)
        self.assertIsInstance(output.clipboard_output, ClipboardOutput)
        self.assertEqual(output.name, "paste/xdotool")

    def test_xdotool_uses_shift_insert_when_the_focused_window_is_a_terminal(self) -> None:
        with (
            patch("dictate.outputs._focused_window_wants_plain_paste", return_value=True),
            patch("dictate.outputs.command_exists", return_value=True),
            patch("dictate.outputs._set_x_selection") as selection,
            patch("dictate.outputs.subprocess.run") as run,
        ):
            PasteOutput(XdotoolOutput(), Mock()).send("hello from dictate")

        selection.assert_called_once_with("primary", "hello from dictate")
        run.assert_called_once_with(
            ["xdotool", "key", "--clearmodifiers", "shift+Insert"],
            check=True,
        )

    def test_xdotool_keeps_ctrl_v_for_ordinary_windows(self) -> None:
        with (
            patch("dictate.outputs._focused_window_wants_plain_paste", return_value=False),
            patch("dictate.outputs.subprocess.run") as run,
        ):
            PasteOutput(XdotoolOutput(), Mock()).send("hello")

        run.assert_called_once_with(
            ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
            check=True,
        )

    def test_wtype_paste_uses_control_v_key_chord(self) -> None:
        with patch("dictate.outputs.subprocess.run") as run:
            from dictate.outputs import _send_paste_shortcut

            _send_paste_shortcut(WtypeOutput())

        run.assert_called_once_with(
            ["wtype", "-M", "ctrl", "-P", "v", "-p", "v", "-m", "ctrl"],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
