from __future__ import annotations

import unittest

from dictate.hotkey import (
    DEFAULT_PUSH_TO_TALK_COMBO,
    combo_is_active,
    format_hotkey_combo,
    key_event_names,
    normalize_push_to_talk_combo,
    parse_hotkey_combo,
)
from dictate.hotkey_backend import _normalize_evdev_keycode


class _FakeKey:
    def __init__(
        self,
        name: str | None = None,
        char: str | None = None,
        vk: int | None = None,
    ):
        self.name = name
        self.char = char
        self.vk = vk


class HotkeyTests(unittest.TestCase):
    def test_normalize_defaults_invalid_values(self) -> None:
        self.assertEqual(normalize_push_to_talk_combo(None), DEFAULT_PUSH_TO_TALK_COMBO)
        with self.assertRaises(ValueError):
            parse_hotkey_combo("bad-token-name")

    def test_parse_combo_orders_and_deduplicates(self) -> None:
        parsed = parse_hotkey_combo("space+ctrl+ctrl")
        self.assertEqual(parsed.combo, "ctrl+space")
        self.assertEqual(parsed.tokens, ("ctrl", "space"))

    def test_combo_is_active_with_generic_modifier_accepts_either_side(self) -> None:
        self.assertTrue(combo_is_active({"ctrl_l", "space"}, "ctrl+space"))
        self.assertTrue(combo_is_active({"ctrl_r", "space"}, "ctrl+space"))
        self.assertFalse(combo_is_active({"ctrl"}, "ctrl+space"))

    def test_combo_is_active_respects_side_specific_modifiers(self) -> None:
        self.assertTrue(combo_is_active({"ctrl_r", "space"}, "ctrl_r+space"))
        self.assertFalse(combo_is_active({"ctrl_l", "space"}, "ctrl_r+space"))
        self.assertTrue(combo_is_active({"ctrl_l", "space"}, "ctrl_l+space"))
        self.assertFalse(combo_is_active({"ctrl_r", "space"}, "ctrl_l+space"))

    def test_key_event_names_extracts_characters(self) -> None:
        self.assertEqual(key_event_names(_FakeKey(char="a")), {"a"})
        self.assertEqual(key_event_names(_FakeKey(name="space")), {"space"})

    def test_key_event_names_extracts_windows_modifier_sides_from_vk(self) -> None:
        self.assertEqual(key_event_names(_FakeKey(name="ctrl", vk=0xA2)), {"ctrl", "ctrl_l"})
        self.assertEqual(key_event_names(_FakeKey(name="ctrl", vk=0xA3)), {"ctrl", "ctrl_r"})
        self.assertTrue(
            combo_is_active(key_event_names(_FakeKey(name="ctrl", vk=0xA3)), "ctrl_r")
        )
        self.assertFalse(
            combo_is_active(key_event_names(_FakeKey(name="ctrl", vk=0xA2)), "ctrl_r")
        )

    def test_evdev_modifier_keycodes_keep_left_and_right_distinct(self) -> None:
        self.assertEqual(_normalize_evdev_keycode("KEY_LEFTCTRL"), "ctrl_l")
        self.assertEqual(_normalize_evdev_keycode("KEY_RIGHTCTRL"), "ctrl_r")

    def test_display_name_is_human_readable(self) -> None:
        self.assertEqual(format_hotkey_combo("ctrl_r"), "Right Ctrl")
        self.assertEqual(format_hotkey_combo("ctrl+space"), "Ctrl + Space")


if __name__ == "__main__":
    unittest.main()
