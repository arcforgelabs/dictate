"""GTK 3 dialog showing recent dictation history with copy-to-clipboard."""

from __future__ import annotations

import sys
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk

from dictate.history import HistoryEntry, HistoryStore
from dictate.outputs import ClipboardOutput, OutputError, TextOutput

PAGE_SIZE = 5


class RecentHistoryDialog(Gtk.Dialog):
    """Modal dialog listing recent dictations with a Copy action."""

    def __init__(
        self,
        store: HistoryStore,
        parent: Gtk.Window | None = None,
        output: TextOutput | None = None,
    ):
        super().__init__(
            title="History",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(420, 300)
        self.add_button("Close", Gtk.ResponseType.CLOSE)

        self._store = store
        self._output = output
        self._entries = store.load()
        self._page = 0

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)

        self._rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.pack_start(self._rows_box, True, True, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._previous_btn = Gtk.Button(label="Previous")
        self._previous_btn.connect("clicked", self._on_previous)
        controls.pack_start(self._previous_btn, False, False, 0)
        self._page_label = Gtk.Label(label="")
        self._page_label.set_hexpand(True)
        controls.pack_start(self._page_label, True, True, 0)
        self._next_btn = Gtk.Button(label="Next")
        self._next_btn.connect("clicked", self._on_next)
        controls.pack_start(self._next_btn, False, False, 0)
        content.pack_start(controls, False, False, 0)

        self._render_page()

        self.show_all()

    def _render_page(self) -> None:
        for child in self._rows_box.get_children():
            self._rows_box.remove(child)

        if not self._entries:
            empty_label = Gtk.Label(label="No recent dictations.")
            empty_label.set_xalign(0.0)
            self._rows_box.pack_start(empty_label, False, False, 0)
            self._page_label.set_text("No history")
            self._previous_btn.set_sensitive(False)
            self._next_btn.set_sensitive(False)
            self.show_all()
            return

        max_page = (len(self._entries) - 1) // PAGE_SIZE
        self._page = min(self._page, max_page)
        start = self._page * PAGE_SIZE
        page_entries = self._entries[start : start + PAGE_SIZE]
        for offset, entry in enumerate(page_entries, start=1):
            self._add_entry_row(start + offset, entry)

        self._page_label.set_text(
            f"Page {self._page + 1} of {max_page + 1} ({len(self._entries)} entries)"
        )
        self._previous_btn.set_sensitive(self._page > 0)
        self._next_btn.set_sensitive(self._page < max_page)
        self.show_all()

    def _add_entry_row(self, idx: int, entry: HistoryEntry) -> None:
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)

        timestamp = _format_timestamp(entry.created_at)
        header_label = Gtk.Label(label=f"{idx}. {timestamp}")
        header_label.set_xalign(0.0)
        header_label.set_markup(f"<b>{idx}.</b> {timestamp}")
        info_box.pack_start(header_label, False, False, 0)

        preview = _truncate(entry.text, max_chars=80)
        preview_label = Gtk.Label(label=preview)
        preview_label.set_xalign(0.0)
        preview_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        preview_label.set_max_width_chars(60)
        info_box.pack_start(preview_label, False, False, 0)

        row_box.pack_start(info_box, True, True, 0)

        copy_btn = Gtk.Button(label="Copy")
        copy_btn.connect("clicked", self._on_copy, entry)
        row_box.pack_start(copy_btn, False, False, 0)

        if self._output is not None:
            paste_btn = Gtk.Button(label="Paste")
            paste_btn.connect("clicked", self._on_paste, entry)
            row_box.pack_start(paste_btn, False, False, 0)

        self._rows_box.pack_start(row_box, False, False, 0)

    def _on_previous(self, _button: Gtk.Button) -> None:
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def _on_next(self, _button: Gtk.Button) -> None:
        if self._entries and self._page < (len(self._entries) - 1) // PAGE_SIZE:
            self._page += 1
            self._render_page()

    def _on_copy(self, _button: Gtk.Button, entry: HistoryEntry) -> None:
        try:
            ClipboardOutput().send(entry.text)
        except OutputError as exc:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                text="Clipboard copy failed",
            )
            dialog.format_secondary_text(
                f"{exc}\n\nMake sure a clipboard backend is installed (xclip or pyperclip)."
            )
            dialog.run()
            dialog.destroy()

    def _on_paste(self, _button: Gtk.Button, entry: HistoryEntry) -> None:
        if self._output is None:
            return
        output = self._output
        text = entry.text
        try:
            ClipboardOutput().send(text)
        except OutputError:
            pass

        self.hide()
        self.response(Gtk.ResponseType.CLOSE)

        def send_after_focus_restore() -> bool:
            try:
                output.send(text)
            except Exception as exc:  # noqa: BLE001
                print(f"History paste failed: {exc}", file=sys.stderr)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(150, send_after_focus_restore)


def _format_timestamp(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return iso_str


def _truncate(text: str, *, max_chars: int = 80) -> str:
    single_line = text.replace("\n", " ").strip()
    if len(single_line) <= max_chars:
        return single_line
    return single_line[: max_chars - 1] + "\u2026"
