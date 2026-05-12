from __future__ import annotations

import unittest
from unittest.mock import patch

from dictate.hotkey_backend import (
    HotkeyBackendUnavailableError,
    _portal_trigger,
    detect_hotkey_backend,
)


class HotkeyBackendSelectionTests(unittest.TestCase):
    def test_wayland_prefers_portal_backend(self) -> None:
        with patch("dictate.hotkey_backend.detect_session_type", return_value="wayland"):
            with patch("dictate.hotkey_backend.evdev_available", return_value=False):
                with patch("dictate.hotkey_backend.portal_global_shortcuts_available", return_value=True):
                    with patch("dictate.hotkey_backend.pynput_available", return_value=True):
                        self.assertEqual(detect_hotkey_backend(), "portal")

    def test_evdev_backend_wins_when_available(self) -> None:
        with patch("dictate.hotkey_backend.detect_session_type", return_value="wayland"):
            with patch("dictate.hotkey_backend.evdev_available", return_value=True):
                with patch("dictate.hotkey_backend.portal_global_shortcuts_available", return_value=True):
                    with patch("dictate.hotkey_backend.pynput_available", return_value=True):
                        self.assertEqual(detect_hotkey_backend(), "evdev")

    def test_x11_uses_pynput_backend(self) -> None:
        with patch("dictate.hotkey_backend.detect_session_type", return_value="x11"):
            with patch("dictate.hotkey_backend.evdev_available", return_value=False):
                with patch("dictate.hotkey_backend.portal_global_shortcuts_available", return_value=True):
                    with patch("dictate.hotkey_backend.pynput_available", return_value=True):
                        self.assertEqual(detect_hotkey_backend(), "pynput")

    def test_wayland_without_portal_raises(self) -> None:
        with patch("dictate.hotkey_backend.detect_session_type", return_value="wayland"):
            with patch("dictate.hotkey_backend.evdev_available", return_value=False):
                with patch("dictate.hotkey_backend.portal_global_shortcuts_available", return_value=False):
                    with patch("dictate.hotkey_backend.pynput_available", return_value=False):
                        with self.assertRaises(HotkeyBackendUnavailableError):
                            detect_hotkey_backend()

    def test_portal_trigger_formats_combo(self) -> None:
        self.assertEqual(_portal_trigger("ctrl+space"), "CTRL+space")
        self.assertEqual(_portal_trigger("ctrl+shift+r"), "CTRL+SHIFT+r")

    def test_portal_trigger_formats_side_specific_single_modifier_keys(self) -> None:
        self.assertEqual(_portal_trigger("ctrl_l"), "Control_L")
        self.assertEqual(_portal_trigger("ctrl_r"), "Control_R")


if __name__ == "__main__":
    unittest.main()
