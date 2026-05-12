"""Push-to-talk hotkey parsing, formatting, and matching helpers."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PUSH_TO_TALK_COMBO = "ctrl_r"
SUPPORTED_SINGLE_KEY_ALIASES = ("ctrl_r", "ctrl_l")
_MODIFIER_ORDER = {"ctrl": 0, "ctrl_l": 1, "ctrl_r": 2, "shift": 3, "shift_l": 4, "shift_r": 5, "alt": 6, "alt_l": 7, "alt_r": 8, "super": 9, "super_l": 10, "super_r": 11}

_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "ctrl": ("ctrl", "ctrl_l", "ctrl_r"),
    "ctrl_l": ("ctrl_l",),
    "ctrl_r": ("ctrl_r",),
    "shift": ("shift", "shift_l", "shift_r"),
    "shift_l": ("shift_l",),
    "shift_r": ("shift_r",),
    "alt": ("alt", "alt_l", "alt_r"),
    "alt_l": ("alt_l",),
    "alt_r": ("alt_r",),
    "super": ("super", "super_l", "super_r", "cmd", "windows"),
    "super_l": ("super_l", "cmd_l", "windows_l"),
    "super_r": ("super_r", "cmd_r", "windows_r"),
    "space": ("space", " "),
    "enter": ("enter", "return"),
    "esc": ("esc", "escape"),
    "tab": ("tab",),
    "caps_lock": ("caps_lock",),
}

_INPUT_ALIASES: dict[str, str] = {
    "control": "ctrl",
    "control_l": "ctrl_l",
    "control_r": "ctrl_r",
    "left_ctrl": "ctrl_l",
    "right_ctrl": "ctrl_r",
    "left_control": "ctrl_l",
    "right_control": "ctrl_r",
    "left_shift": "shift_l",
    "right_shift": "shift_r",
    "left_alt": "alt_l",
    "right_alt": "alt_r",
    "option": "alt",
    "option_l": "alt_l",
    "option_r": "alt_r",
    "meta": "super",
    "cmd": "super",
    "command": "super",
    "win": "super",
    "windows": "super",
    "left_super": "super_l",
    "right_super": "super_r",
    "escape": "esc",
    "return": "enter",
}

_DISPLAY_NAMES = {
    "ctrl": "Ctrl",
    "ctrl_l": "Left Ctrl",
    "ctrl_r": "Right Ctrl",
    "shift": "Shift",
    "shift_l": "Left Shift",
    "shift_r": "Right Shift",
    "alt": "Alt",
    "alt_l": "Left Alt",
    "alt_r": "Right Alt",
    "super": "Super",
    "super_l": "Left Super",
    "super_r": "Right Super",
    "space": "Space",
    "enter": "Enter",
    "esc": "Esc",
    "tab": "Tab",
    "caps_lock": "Caps Lock",
}


class HotkeyParseError(ValueError):
    """Raised when a push-to-talk combo string cannot be parsed."""


@dataclass(frozen=True, slots=True)
class ParsedHotkey:
    combo: str
    tokens: tuple[str, ...]


def normalize_push_to_talk_key(value: str | None) -> str:
    """Backward-compatible single-key normalization."""
    return normalize_push_to_talk_combo(value)


def normalize_push_to_talk_combo(value: str | None) -> str:
    return parse_hotkey_combo(value).combo


def normalize_hotkey_token(value: str, *, allow_character: bool = False) -> str:
    return _normalize_hotkey_token(value, allow_character=allow_character)


def parse_hotkey_combo(value: str | None) -> ParsedHotkey:
    raw = (value or DEFAULT_PUSH_TO_TALK_COMBO).strip().lower()
    if not raw:
        raw = DEFAULT_PUSH_TO_TALK_COMBO

    tokens: list[str] = []
    seen: set[str] = set()
    for part in raw.split("+"):
        token = _normalize_hotkey_token(part)
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)

    if not tokens:
        raise HotkeyParseError("push-to-talk combo cannot be empty")

    ordered = tuple(sorted(tokens, key=_token_sort_key))
    return ParsedHotkey(combo="+".join(ordered), tokens=ordered)


def hotkey_display_name(value: str) -> str:
    return format_hotkey_combo(value)


def format_hotkey_combo(value: str) -> str:
    parsed = parse_hotkey_combo(value)
    return " + ".join(_DISPLAY_NAMES.get(token, token.upper()) for token in parsed.tokens)


def key_matches_push_to_talk(key: object, push_to_talk_key: str) -> bool:
    parsed = parse_hotkey_combo(push_to_talk_key)
    names = key_event_names(key)
    return any(_token_matches_names(token, names) for token in parsed.tokens)


def combo_is_active(pressed_names: set[str], push_to_talk_combo: str) -> bool:
    parsed = parse_hotkey_combo(push_to_talk_combo)
    return all(_token_matches_names(token, pressed_names) for token in parsed.tokens)


def key_event_names(key: object) -> set[str]:
    names: set[str] = set()
    for attr in ("name", "char"):
        current = getattr(key, attr, None)
        if isinstance(current, str):
            try:
                normalized = _normalize_hotkey_token(current, allow_character=True)
            except HotkeyParseError:
                continue
            names.add(normalized)
    vk = getattr(key, "vk", None)
    if isinstance(vk, int):
        if vk in _VK_TOKEN_NAMES:
            names.add(_VK_TOKEN_NAMES[vk])
        elif vk == 13:
            names.add("enter")
        elif vk == 9:
            names.add("tab")
        elif vk == 27:
            names.add("esc")
        elif vk == 32:
            names.add("space")
    return names


_VK_TOKEN_NAMES = {
    0xA2: "ctrl_l",
    0xA3: "ctrl_r",
    0xA0: "shift_l",
    0xA1: "shift_r",
    0xA4: "alt_l",
    0xA5: "alt_r",
    0x5B: "super_l",
    0x5C: "super_r",
}


def _normalize_hotkey_token(part: str, *, allow_character: bool = False) -> str:
    token = part.strip().lower()
    if not token:
        raise HotkeyParseError("empty hotkey token")
    token = token.replace(" ", "_").replace("-", "_")
    token = _INPUT_ALIASES.get(token, token)

    if token in _TOKEN_ALIASES:
        return token
    if token == " ":
        return "space"
    if token.startswith("f") and token[1:].isdigit():
        return token
    if allow_character and len(token) == 1:
        return token
    if len(token) == 1 and token.isalnum():
        return token
    raise HotkeyParseError(f"unsupported hotkey token: {part!r}")


def _token_sort_key(token: str) -> tuple[int, str]:
    return (_MODIFIER_ORDER.get(token, 100), token)


def _token_matches_names(token: str, names: set[str]) -> bool:
    aliases = _TOKEN_ALIASES.get(token, (token,))
    return any(alias in names for alias in aliases)
