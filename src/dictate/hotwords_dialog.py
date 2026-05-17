"""GTK 3 dialog for managing hotwords."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, Gtk

from dictate.config import add_hotwords, load_config, remove_hotwords


class HotwordsDialog(Gtk.Dialog):
    """Modal dialog to view, add, and remove saved hotwords."""

    def __init__(self, parent: Gtk.Window | None = None):
        super().__init__(
            title="Hotwords",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(350, 400)
        self.add_button("Close", Gtk.ResponseType.CLOSE)

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)

        # --- Scrollable hotword list ---
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)
        scrolled.set_vexpand(True)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        scrolled.add(self.listbox)
        content.pack_start(scrolled, True, True, 0)

        # --- Add row: entry + button ---
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("New hotword...")
        self.entry.set_hexpand(True)
        self.entry.connect("activate", self._on_add)
        add_box.pack_start(self.entry, True, True, 0)

        add_btn = Gtk.Button(label="Add")
        add_btn.connect("clicked", self._on_add)
        add_box.pack_start(add_btn, False, False, 0)
        content.pack_start(add_box, False, False, 0)

        # --- Remove button ---
        remove_btn = Gtk.Button(label="Remove Selected")
        remove_btn.connect("clicked", self._on_remove)
        content.pack_start(remove_btn, False, False, 0)

        self.connect("key-press-event", self._on_key_press)

        self._populate()
        self.show_all()

    def _populate(self) -> None:
        """Load hotwords from config and fill the listbox."""
        for row in self.listbox.get_children():
            self.listbox.remove(row)

        for word in load_config().hotwords:
            self._add_row(word)

    def _add_row(self, word: str) -> None:
        """Append a single row to the listbox."""
        row = Gtk.ListBoxRow()
        label = Gtk.Label(label=word, xalign=0.0)
        label.set_margin_start(8)
        label.set_margin_end(8)
        label.set_margin_top(4)
        label.set_margin_bottom(4)
        row.add(label)
        self.listbox.add(row)
        row.show_all()

    def _on_add(self, _widget: Gtk.Widget) -> None:
        """Add hotword(s) from entry field. Supports comma-separated input."""
        text = self.entry.get_text().strip()
        if not text:
            return

        words = [w.strip() for w in text.split(",") if w.strip()]
        added = add_hotwords(words)

        for word in added:
            self._add_row(word)

        self.entry.set_text("")
        self.entry.grab_focus()

    def _on_remove(self, _widget: Gtk.Widget | None) -> None:
        """Remove the selected hotword."""
        row = self.listbox.get_selected_row()
        if row is None:
            return

        word = row.get_child().get_text()
        remove_hotwords([word])
        self.listbox.remove(row)

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        """Handle Delete key to remove selected hotword."""
        if event.keyval == Gdk.KEY_Delete:
            self._on_remove(None)
            return True
        return False
