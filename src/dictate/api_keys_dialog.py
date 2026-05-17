"""GTK dialog for storing hosted STT API keys."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from dictate.api_keys import (
    API_BACKEND_LABELS,
    ApiKeyStorageError,
    clear_api_key,
    has_stored_api_key,
    save_api_key,
    secret_store_available,
    secret_store_description,
)


class ApiKeysDialog(Gtk.Dialog):
    """Modal dialog to save or clear one hosted backend API key."""

    CLEAR_RESPONSE = 1001

    def __init__(self, backend: str, parent: Gtk.Window | None = None):
        self.backend = backend
        self.saved = False
        self.cleared = False
        label = API_BACKEND_LABELS.get(backend, backend)
        super().__init__(
            title=f"{label} API Key",
            transient_for=parent,
            modal=True,
            destroy_with_parent=True,
        )
        self.set_default_size(420, 160)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Clear", self.CLEAR_RESPONSE)
        self.add_button("Save", Gtk.ResponseType.OK)

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)

        store = secret_store_description()
        if not secret_store_available():
            status = (
                f"Dictate cannot access a supported OS secret store ({store}). "
                "Configure an external API key command instead."
            )
        else:
            try:
                has_key = has_stored_api_key(backend)
            except ApiKeyStorageError as exc:
                status = f"Could not check stored key status in {store}: {exc}"
            else:
                if has_key:
                    status = f"Stored key exists in {store}. Enter a replacement key or clear it."
                else:
                    status = "No stored key. Enter the API key for this backend."
        status_label = Gtk.Label(label=status)
        status_label.set_xalign(0.0)
        status_label.set_line_wrap(True)
        content.pack_start(status_label, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_visibility(False)
        self.entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.entry.set_placeholder_text(f"{label} API key")
        self.entry.set_hexpand(True)
        content.pack_start(self.entry, False, False, 0)

        hint = Gtk.Label(
            label=(
                "Stored in the OS secret store, not in Dictate's YAML config. "
                "Environment variables still take priority at runtime."
            )
        )
        hint.set_xalign(0.0)
        hint.set_line_wrap(True)
        content.pack_start(hint, False, False, 0)

        self.show_all()
        if not secret_store_available():
            self.entry.set_sensitive(False)
            self.set_response_sensitive(Gtk.ResponseType.OK, False)

    @property
    def api_key(self) -> str:
        return self.entry.get_text().strip()

    def show_error(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="API key not saved",
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


def save_stored_key_or_error(parent: Gtk.Window | None, backend: str, api_key: str) -> bool:
    try:
        save_api_key(backend, api_key)
    except ApiKeyStorageError as exc:
        dialog = Gtk.MessageDialog(
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="API key not saved",
        )
        dialog.format_secondary_text(str(exc))
        dialog.run()
        dialog.destroy()
        return False
    return True


def clear_stored_key_or_error(parent: Gtk.Window | None, backend: str) -> bool:
    try:
        clear_api_key(backend)
    except ApiKeyStorageError as exc:
        dialog = Gtk.MessageDialog(
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="API key not cleared",
        )
        dialog.format_secondary_text(str(exc))
        dialog.run()
        dialog.destroy()
        return False
    return True
