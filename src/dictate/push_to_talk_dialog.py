"""GTK 3 dialog for configuring the push-to-talk combo."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk

from dictate.hotkey import (
    HotkeyParseError,
    format_hotkey_combo,
    normalize_hotkey_token,
    normalize_push_to_talk_combo,
    parse_hotkey_combo,
)

PRESET_COMBOS: tuple[tuple[str, str], ...] = (
    ("Right Ctrl", "ctrl_r"),
    ("Left Ctrl", "ctrl_l"),
    ("Ctrl + Space", "ctrl+space"),
    ("Ctrl + Shift", "ctrl+shift"),
    ("Left Ctrl + Space", "ctrl_l+space"),
    ("Right Alt", "alt_r"),
    ("Left Alt", "alt_l"),
)


class PushToTalkDialog(Gtk.Dialog):
    """Modal dialog to edit and validate the push-to-talk combo."""

    def __init__(self, current_combo: str, parent: Gtk.Window | None = None):
        super().__init__(
            title="Hotkeys",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(420, 220)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save", Gtk.ResponseType.OK)

        self.result_combo = normalize_push_to_talk_combo(current_combo)
        self._capture_active = False
        self._capture_pressed_tokens: set[str] = set()
        self._capture_combo_tokens: set[str] = set()

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)

        info = Gtk.Label(
            label="Choose a preset or capture a holdable combo such as ctrl_r, ctrl_l, ctrl+space, or ctrl+shift.",
            xalign=0.0,
        )
        info.set_line_wrap(True)
        content.pack_start(info, False, False, 0)

        preset_label = Gtk.Label(label="Preset", xalign=0.0)
        content.pack_start(preset_label, False, False, 0)

        self.preset_combo = Gtk.ComboBoxText()
        self.preset_combo.append("custom", "Custom")
        current_preset = "custom"
        for label, combo in PRESET_COMBOS:
            self.preset_combo.append(combo, f"{label} ({format_hotkey_combo(combo)})")
            if combo == self.result_combo:
                current_preset = combo
        self.preset_combo.set_active_id(current_preset)
        self.preset_combo.connect("changed", self._on_preset_changed)
        content.pack_start(self.preset_combo, False, False, 0)

        entry_label = Gtk.Label(label="Combo", xalign=0.0)
        content.pack_start(entry_label, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_text(self.result_combo)
        self.entry.set_placeholder_text("ctrl_r or ctrl+space")
        self.entry.set_hexpand(True)
        content.pack_start(self.entry, False, False, 0)

        self.capture_button = Gtk.Button(label="Capture Shortcut")
        self.capture_button.connect("clicked", self._on_capture_clicked)
        content.pack_start(self.capture_button, False, False, 0)

        self.capture_status = Gtk.Label(
            label="",
            xalign=0.0,
        )
        self.capture_status.set_line_wrap(True)
        self.capture_status.set_no_show_all(True)
        self.capture_status.hide()
        content.pack_start(self.capture_status, False, False, 0)

        examples = Gtk.Label(
            label="Supported tokens include ctrl, ctrl_l, ctrl_r, shift, alt, super, space, enter, tab, esc, and single letters or digits.",
            xalign=0.0,
        )
        examples.set_line_wrap(True)
        content.pack_start(examples, False, False, 0)

        self.connect("key-press-event", self._on_key_press)
        self.connect("key-release-event", self._on_key_release)
        self.show_all()

    def run(self) -> int:
        while True:
            response = super().run()
            if response != Gtk.ResponseType.OK:
                return response
            try:
                self.result_combo = normalize_push_to_talk_combo(self.entry.get_text())
                return response
            except HotkeyParseError as exc:
                self._show_error(str(exc))

    def _on_preset_changed(self, widget: Gtk.ComboBoxText) -> None:
        active_id = widget.get_active_id()
        if active_id and active_id != "custom":
            self.entry.set_text(active_id)

    def _on_capture_clicked(self, _button: Gtk.Button) -> None:
        self._capture_active = True
        self._capture_pressed_tokens.clear()
        self._capture_combo_tokens.clear()
        self.capture_button.set_sensitive(False)
        self.entry.set_sensitive(False)
        self.capture_status.set_text("Capture active. Press and hold the new shortcut, then release it.")
        self.capture_status.show()
        self.grab_focus()

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if not self._capture_active:
            return False
        token = _event_to_token(event)
        if token is None:
            return True
        self._capture_pressed_tokens.add(token)
        self._capture_combo_tokens.add(token)
        self.capture_status.set_text(
            f"Capturing: {format_hotkey_combo('+'.join(sorted(self._capture_combo_tokens)))}"
        )
        return True

    def _on_key_release(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if not self._capture_active:
            return False
        token = _event_to_token(event)
        if token is not None:
            self._capture_pressed_tokens.discard(token)
        if self._capture_pressed_tokens:
            return True
        self._finish_capture()
        return True

    def _finish_capture(self) -> None:
        self._capture_active = False
        self.capture_button.set_sensitive(True)
        self.entry.set_sensitive(True)
        self.entry.grab_focus()
        try:
            if not self._capture_combo_tokens:
                raise HotkeyParseError("No keys were captured.")
            combo = parse_hotkey_combo("+".join(sorted(self._capture_combo_tokens))).combo
        except HotkeyParseError as exc:
            self.capture_status.hide()
            self._show_error(str(exc))
            return
        self.entry.set_text(combo)
        self.capture_status.set_text(f"Captured: {format_hotkey_combo(combo)}")
        self.capture_status.show()
        self._sync_preset_selection(combo)

    def _sync_preset_selection(self, combo: str) -> None:
        active_id = "custom"
        for _label, preset_combo in PRESET_COMBOS:
            if preset_combo == combo:
                active_id = preset_combo
                break
        self.preset_combo.set_active_id(active_id)

    def _show_error(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Invalid push-to-talk combo",
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


def _event_to_token(event: Gdk.EventKey) -> str | None:
    key_name = Gdk.keyval_name(event.keyval)
    if not key_name:
        return None
    try:
        return normalize_hotkey_token(key_name, allow_character=True)
    except HotkeyParseError:
        return None
