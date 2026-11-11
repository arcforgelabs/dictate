from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from dictate.outputs import (
    BackendUnavailableError,
    ClipboardOutput,
    PasteOutput,
    PynputOutput,
    WtypeOutput,
    XdotoolOutput,
    YdotoolOutput,
    detect_session_type,
    resolve_typing_backend,
)


class SessionDetectionTests(unittest.TestCase):
    def test_linux_session_uses_explicit_type_before_display_hints(self) -> None:
        for session, expected in (("X11", "x11"), ("WAYLAND", "wayland")):
            with (
                self.subTest(session=session),
                patch("dictate.outputs.sys.platform", "linux"),
                patch.dict(
                    os.environ,
                    {
                        "XDG_SESSION_TYPE": session,
                        "WAYLAND_DISPLAY": "wayland-test",
                        "DISPLAY": ":99",
                    },
                    clear=True,
                ),
            ):
                self.assertEqual(detect_session_type(), expected)

    def test_linux_display_fallback_prefers_wayland_and_handles_no_display(self) -> None:
        cases = (
            ({"WAYLAND_DISPLAY": "wayland-test", "DISPLAY": ":99"}, "wayland"),
            ({"DISPLAY": ":99"}, "x11"),
            ({"XDG_SESSION_TYPE": "tty", "DISPLAY": ":99"}, "x11"),
            ({"XDG_SESSION_TYPE": "tty"}, "unknown"),
            ({}, "unknown"),
        )
        for environment, expected in cases:
            with (
                self.subTest(environment=environment),
                patch("dictate.outputs.sys.platform", "linux"),
                patch.dict(os.environ, environment, clear=True),
            ):
                self.assertEqual(detect_session_type(), expected)

    def test_macos_ignores_linux_display_hints(self) -> None:
        with (
            patch("dictate.outputs.sys.platform", "darwin"),
            patch.dict(
                os.environ,
                {
                    "XDG_SESSION_TYPE": "wayland",
                    "WAYLAND_DISPLAY": "wayland-test",
                    "DISPLAY": ":99",
                },
                clear=True,
            ),
        ):
            self.assertEqual(detect_session_type(), "macos")


class TypingBackendSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        keeper = patch("dictate.outputs.default_clipboard_keeper", return_value=None)
        keeper.start()
        self.addCleanup(keeper.stop)

    def test_auto_selection_uses_desktop_order_and_skips_missing_tools(self) -> None:
        cases = (
            ("x11", {"xdotool", "wtype", "ydotool"}, XdotoolOutput),
            ("x11", {"wtype", "ydotool"}, WtypeOutput),
            ("x11", {"ydotool"}, YdotoolOutput),
            ("wayland", {"xdotool", "wtype", "ydotool"}, WtypeOutput),
            ("wayland", {"xdotool", "ydotool"}, YdotoolOutput),
            ("wayland", {"xdotool"}, XdotoolOutput),
            ("unknown", set(), PynputOutput),
        )
        for session, commands, expected in cases:
            with (
                self.subTest(session=session, commands=commands),
                patch("dictate.outputs.detect_session_type", return_value=session),
                patch("dictate.outputs.command_exists", side_effect=commands.__contains__),
                patch("dictate.outputs.python_module_available", return_value=True),
            ):
                output = resolve_typing_backend("auto")

            self.assertIsInstance(output, PasteOutput)
            self.assertIsInstance(output.typing_output, expected)
            self.assertIsInstance(output.clipboard_output, ClipboardOutput)

    def test_auto_selection_reports_when_no_supported_tool_is_available(self) -> None:
        for session in ("x11", "wayland", "windows", "unknown"):
            with (
                self.subTest(session=session),
                patch("dictate.outputs.detect_session_type", return_value=session),
                patch("dictate.outputs.command_exists", return_value=session == "windows"),
                patch("dictate.outputs.python_module_available", return_value=False),
            ):
                with self.assertRaisesRegex(BackendUnavailableError, "no typing backend found"):
                    resolve_typing_backend("auto")

    def test_explicit_selection_overrides_desktop_order(self) -> None:
        cases = (
            ("xdotool", XdotoolOutput),
            ("wtype", WtypeOutput),
            ("ydotool", YdotoolOutput),
            ("pynput", PynputOutput),
        )
        for preferred, expected in cases:
            with (
                self.subTest(preferred=preferred),
                patch("dictate.outputs.detect_session_type", return_value="wayland"),
                patch("dictate.outputs.command_exists", return_value=True),
                patch("dictate.outputs.python_module_available", return_value=True),
            ):
                output = resolve_typing_backend(preferred)

            self.assertIsInstance(output, PasteOutput)
            self.assertIsInstance(output.typing_output, expected)
            self.assertEqual(output.name, f"paste/{preferred}")

    def test_explicit_selection_reports_the_missing_tool_without_fallback(self) -> None:
        for preferred in ("xdotool", "wtype", "ydotool", "pynput"):
            with (
                self.subTest(preferred=preferred),
                patch("dictate.outputs.detect_session_type", return_value="wayland"),
                patch("dictate.outputs.command_exists", side_effect=lambda name: name != preferred),
                patch("dictate.outputs.python_module_available", return_value=False),
            ):
                with self.assertRaisesRegex(
                    BackendUnavailableError,
                    f"requested typing backend '{preferred}' is not installed",
                ):
                    resolve_typing_backend(preferred)


class PasteOutputTests(unittest.TestCase):
    def test_paste_output_copies_before_sending_shortcut(self) -> None:
        clipboard = Mock()
        typing = XdotoolOutput()
        with patch("dictate.outputs._send_paste_shortcut") as shortcut:
            PasteOutput(typing, clipboard).send("complete dictation")

        clipboard.send.assert_called_once_with("complete dictation")
        shortcut.assert_called_once_with(typing, plain_text=False)

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
