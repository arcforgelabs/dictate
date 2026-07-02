"""System tray icon using AyatanaAppIndicator3."""

import gc
import os
import signal
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import AyatanaAppIndicator3, GLib, Gtk

from dictate.config import (
    load_config,
    set_push_to_talk_combo,
    set_stt_runtime_profile,
    set_stt_selection,
)
from dictate.daemon import Daemon
from dictate.hotkey import format_hotkey_combo
from dictate.hotkey_backend import (
    detect_hotkey_backend,
    HotkeyBackendUnavailableError,
    request_portal_shortcut_authorization,
)
from dictate.model_state import (
    get_model_error,
    mark_model_failed,
    mark_model_prepared,
)
from dictate.api_keys import (
    API_BACKENDS,
    API_BACKEND_LABELS,
    ApiKeyStatus,
    ApiKeyStorageError,
    api_key_status,
    clear_api_key,
)
from dictate.stt import BACKEND_REGISTRY, create_speech_to_text, resolve_default_local_model

ICON_ACTIVE = "microphone-sensitivity-high-symbolic"
ICON_PAUSED = "microphone-disabled-symbolic"
SWITCH_LOCK_SECONDS = 15
SWITCH_ABORT_SECONDS = 300
PREPARE_ABORT_SECONDS = 900
SWITCH_STATUS_CLEAR_SECONDS = 6
LOCAL_RUNTIME_PROFILES: tuple[tuple[str, str, str], ...] = (
    ("cpu", "int8", "CPU"),
    ("cuda", "int8", "GPU"),
)


def _device_for_backend(backend: str, current_device: str) -> str:
    if backend == "faster-whisper":
        return current_device if current_device in {"cpu", "cuda", "auto"} else "auto"
    return "auto"


def _compute_type_for_backend(backend: str, current_compute_type: str) -> str:
    if backend == "faster-whisper":
        if current_compute_type in {"int8", "float16", "float32"}:
            return current_compute_type
    return "int8"


def _apply_api_key_command_from_config(backend: str) -> None:
    config = load_config()
    if backend == "openai" and config.openai_api_key_command:
        os.environ.setdefault("DICTATE_OPENAI_API_KEY_COMMAND", config.openai_api_key_command)
    if backend == "xai" and config.xai_api_key_command:
        os.environ.setdefault("DICTATE_XAI_API_KEY_COMMAND", config.xai_api_key_command)
    if backend == "gemini" and config.gemini_api_key_command:
        os.environ.setdefault("DICTATE_GEMINI_API_KEY_COMMAND", config.gemini_api_key_command)


def _hotwords_available_for_backend(backend: str) -> bool:
    spec = BACKEND_REGISTRY.get(backend)  # type: ignore[arg-type]
    if spec is None:
        return False
    return spec.capabilities.supports_hotwords or spec.capabilities.supports_prompt_bias


def _api_key_available_for_backend(backend: str) -> bool:
    return backend in API_BACKENDS


def _api_key_command_configured_for_backend(backend: str) -> bool:
    command_env = f"DICTATE_{backend.upper()}_API_KEY_COMMAND"
    if os.environ.get(command_env):
        return True
    config = load_config()
    if backend == "openai":
        return bool(config.openai_api_key_command)
    if backend == "xai":
        return bool(config.xai_api_key_command)
    if backend == "gemini":
        return bool(config.gemini_api_key_command)
    return False


def _local_runtime_name(device: str) -> str:
    if device == "cuda":
        return "GPU"
    return "CPU"


class TrayIcon:
    def __init__(self, daemon: Daemon):
        self.daemon = daemon
        self._quitting = False
        self._switch_in_progress = False
        self._switch_background_mode = False
        self._switch_counter = 0
        self._latest_switch_id = 0
        self._switch_started_monotonic = 0.0
        self._switch_target_backend = ""
        self._switch_target_model = ""
        self._prepare_in_progress = False
        self._prepare_counter = 0
        self._latest_prepare_id = 0
        self._prepare_started_monotonic = 0.0
        self._prepare_target_backend = ""
        self._prepare_target_model = ""
        self._prepare_target_device = ""
        self._prepare_target_compute_type = ""
        self._prepare_process: subprocess.Popen[str] | None = None
        self._pending_switch_after_prepare: tuple[str, str, str, str] | None = None
        self._pending_api_key_clear_backend: str | None = None
        self._pending_api_key_clear_switch_id = 0
        self._syncing_model_menu = False
        self._syncing_profile_menu = False
        self._model_items: dict[tuple[str, str], Gtk.RadioMenuItem] = {}
        self._profile_items: dict[tuple[str, str], Gtk.RadioMenuItem] = {}
        self._daemon_status_counter = 0

        self.daemon.status_callback = self._on_daemon_status
        self._active_backend, self._active_model = self.daemon.current_backend_model()
        self._stt_device, self._stt_compute_type = self.daemon.runtime_stt_options()

        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "dictate",
            ICON_ACTIVE,
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)

        self._build_menu()

    def _build_menu(self):
        menu = Gtk.Menu()

        self.toggle_item = Gtk.CheckMenuItem(label="Active")
        self.toggle_item.set_active(True)
        self.toggle_item.connect("toggled", self._on_toggle)
        menu.append(self.toggle_item)

        self.model_status_item = Gtk.MenuItem()
        self.model_status_label = Gtk.Label(label="")
        self.model_status_label.set_xalign(0.0)
        self.model_status_item.add(self.model_status_label)
        self.model_status_item.set_sensitive(False)
        menu.append(self.model_status_item)

        models_item = Gtk.MenuItem(label="Select Model")
        models_item.set_submenu(self._build_model_submenu())
        menu.append(models_item)

        self.switch_status_item = Gtk.MenuItem()
        self.switch_status_label = Gtk.Label(label="")
        self.switch_status_label.set_xalign(0.0)
        self.switch_status_label.set_line_wrap(True)
        self.switch_status_label.set_max_width_chars(46)
        self.switch_status_label.set_width_chars(46)
        self.switch_status_item.add(self.switch_status_label)
        self.switch_status_item.set_sensitive(False)
        self.switch_status_item.set_no_show_all(True)
        self.switch_status_item.hide()
        menu.append(self.switch_status_item)

        push_to_talk_item = Gtk.MenuItem(label="Hotkeys")
        push_to_talk_item.connect("activate", self._on_push_to_talk)
        menu.append(push_to_talk_item)

        history_item = Gtk.MenuItem(label="Recent History")
        history_item.connect("activate", self._on_recent_history)
        menu.append(history_item)

        settings_item = Gtk.MenuItem(label="Open Settings…")
        settings_item.connect("activate", self._on_open_settings)
        menu.append(settings_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._on_quit)
        menu.append(quit_item)

        menu.show_all()
        self._sync_capability_menu_items()
        self._update_model_status_label()
        self.indicator.set_menu(menu)

    def _build_model_submenu(self) -> Gtk.Menu:
        submenu = Gtk.Menu()
        radio_group: Gtk.RadioMenuItem | None = None
        self._model_items.clear()
        self._profile_items.clear()

        def append_model_item(parent: Gtk.Menu, backend: str, model: str) -> None:
            nonlocal radio_group
            if radio_group is None:
                item = Gtk.RadioMenuItem.new_with_label(None, model)
                radio_group = item
            else:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(radio_group, model)
            item.connect("toggled", self._on_model_selected, backend, model)
            self._model_items[(backend, model)] = item
            parent.append(item)

        local_item = Gtk.MenuItem(label=f"Local ({_local_runtime_name(self._stt_device)})")
        local_menu = Gtk.Menu()
        for model in self._models_for_backend("faster-whisper"):
            append_model_item(local_menu, "faster-whisper", model)
        local_menu.append(Gtk.SeparatorMenuItem())
        self._append_local_runtime_items(local_menu)
        if _hotwords_available_for_backend("faster-whisper"):
            local_menu.append(Gtk.SeparatorMenuItem())
            hotwords_item = Gtk.MenuItem(label="Hotwords")
            hotwords_item.connect("activate", self._on_manage_hotwords, "faster-whisper")
            local_menu.append(hotwords_item)
        local_item.set_submenu(local_menu)
        submenu.append(local_item)

        for backend in API_BACKENDS:
            label = API_BACKEND_LABELS.get(backend, backend)
            status = self._api_key_status_for_backend(backend)
            provider_item = Gtk.MenuItem(label=f"{label} ({status.status})")
            provider_menu = Gtk.Menu()
            for model in self._models_for_backend(backend):
                append_model_item(provider_menu, backend, model)
            provider_menu.append(Gtk.SeparatorMenuItem())
            api_item = Gtk.MenuItem(label=f"API Key: {status.status}")
            api_item.connect("activate", self._on_api_key, backend)
            provider_menu.append(api_item)
            if _hotwords_available_for_backend(backend):
                hotwords_item = Gtk.MenuItem(label="Hotwords")
                hotwords_item.connect("activate", self._on_manage_hotwords, backend)
                provider_menu.append(hotwords_item)
            provider_item.set_submenu(provider_menu)
            submenu.append(provider_item)

        self._set_active_model_menu_item(self._active_backend, self._active_model)
        self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
        return submenu

    def _models_for_backend(self, backend: str) -> tuple[str, ...]:
        spec = BACKEND_REGISTRY.get(backend)  # type: ignore[arg-type]
        models = list(spec.model_examples if spec is not None else ())
        if self._active_backend == backend and self._active_model not in models:
            models.insert(0, self._active_model)
        return tuple(models)

    def _append_local_runtime_items(self, submenu: Gtk.Menu) -> None:
        radio_group: Gtk.RadioMenuItem | None = None
        for device, compute_type, label in LOCAL_RUNTIME_PROFILES:
            if radio_group is None:
                item = Gtk.RadioMenuItem.new_with_label(None, label)
                radio_group = item
            else:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(radio_group, label)
            item.connect("toggled", self._on_profile_selected, device, compute_type)
            self._profile_items[(device, compute_type)] = item
            submenu.append(item)

    def _on_installable_model_selected(self, _item, backend: str, model: str) -> None:
        if self._prepare_in_progress:
            self._set_switch_status("Model preparation already in progress. Please wait.")
            return
        if self._switch_in_progress:
            return
        if (backend, model) == (self._active_backend, self._active_model):
            return

        if backend in API_BACKENDS:
            status = self._api_key_status_for_backend(backend)
            if not status.ready:
                label = API_BACKEND_LABELS.get(backend, backend)
                self._set_switch_status(
                    f"{label} API key: {status.status}. "
                    "Add a valid key before selecting this model."
                )
                return

        self._start_switch(
            backend=backend,
            model=model,
            device=_device_for_backend(backend, self._stt_device),
            compute_type=_compute_type_for_backend(backend, self._stt_compute_type),
        )

    def _build_runtime_submenu(self) -> Gtk.Menu:
        submenu = Gtk.Menu()
        profiles = list(LOCAL_RUNTIME_PROFILES)
        active_key = (self._stt_device, self._stt_compute_type)
        known_profiles = {
            (device, compute_type)
            for device, compute_type, _label in LOCAL_RUNTIME_PROFILES
        }
        if active_key not in known_profiles:
            profiles.insert(
                0,
                (
                    self._stt_device,
                    self._stt_compute_type,
                    f"current / {self._stt_device} / {self._stt_compute_type}",
                ),
            )

        radio_group: Gtk.RadioMenuItem | None = None
        for device, compute_type, label in profiles:
            if radio_group is None:
                item = Gtk.RadioMenuItem.new_with_label(None, label)
                radio_group = item
            else:
                item = Gtk.RadioMenuItem.new_with_label_from_widget(radio_group, label)
            item.connect("toggled", self._on_profile_selected, device, compute_type)
            self._profile_items[(device, compute_type)] = item
            submenu.append(item)

        self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
        return submenu

    def _on_toggle(self, item):
        if item.get_active():
            self.daemon.resume()
            self.indicator.set_icon_full(ICON_ACTIVE, "Dictate active")
        else:
            self.daemon.pause()
            self.indicator.set_icon_full(ICON_PAUSED, "Dictate paused")

    def _on_manage_hotwords(self, _item, backend: str | None = None):
        from dictate.hotwords_dialog import HotwordsDialog

        dialog = HotwordsDialog()
        dialog.run()
        dialog.destroy()

        # Live-reload: update engine hotwords from saved config
        del backend
        self.daemon.set_hotwords(load_config().hotwords_for_backend(self._active_backend))

    def _on_open_settings(self, _item):
        """Open the Quiet Console (Tauri shell), falling back to native dialogs."""
        import logging

        from dictate import ui_launcher

        launched = ui_launcher.open_settings_window(
            start_server=lambda: ui_launcher.ensure_server_started(self.daemon),
        )
        if not launched:
            logging.getLogger(__name__).info(
                "Quiet Console shell not installed; using native settings dialogs."
            )

    def _on_recent_history(self, _item):
        from dictate.history_dialog import RecentHistoryDialog

        dialog = RecentHistoryDialog(store=self.daemon.history_store, output=self.daemon.output)
        dialog.run()
        dialog.destroy()

    def _on_api_key(self, _item, backend: str):
        from dictate.api_keys_dialog import (
            ApiKeysDialog,
            clear_stored_key_or_error,
            save_stored_key_or_error,
        )

        if not _api_key_available_for_backend(backend):
            return

        dialog = ApiKeysDialog(backend=backend)
        try:
            while True:
                response = dialog.run()
                if response == Gtk.ResponseType.OK:
                    if not dialog.api_key:
                        dialog.show_error("Enter an API key before saving.")
                        continue
                    if save_stored_key_or_error(dialog, backend, dialog.api_key):
                        self._build_menu()
                        if backend == self._active_backend:
                            self._set_switch_status("API key saved.")
                            self._reload_active_api_backend()
                        else:
                            label = API_BACKEND_LABELS.get(backend, backend)
                            self._set_switch_status(f"{label} API key saved.")
                        break
                    continue
                if response == ApiKeysDialog.CLEAR_RESPONSE:
                    if backend == self._active_backend:
                        self._set_switch_status(
                            "Switching to Local Whisper before clearing API key."
                        )
                        self._start_switch(
                            backend="faster-whisper",
                            model=resolve_default_local_model(self._stt_device),
                            device=_device_for_backend("faster-whisper", self._stt_device),
                            compute_type=_compute_type_for_backend(
                                "faster-whisper",
                                self._stt_compute_type,
                            ),
                        )
                        self._pending_api_key_clear_backend = backend
                        self._pending_api_key_clear_switch_id = self._latest_switch_id
                        break
                    if clear_stored_key_or_error(dialog, backend):
                        self._build_menu()
                        label = API_BACKEND_LABELS.get(backend, backend)
                        self._set_switch_status(f"{label} API key cleared.")
                        break
                    continue
                break
        finally:
            dialog.destroy()

    def _on_push_to_talk(self, _item):
        from dictate.push_to_talk_dialog import PushToTalkDialog

        dialog = PushToTalkDialog(current_combo=self.daemon.push_to_talk_combo)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            if detect_hotkey_backend() == "portal":
                authorized, error = request_portal_shortcut_authorization(dialog.result_combo)
                if not authorized:
                    self._set_switch_status(
                        f"Hotkey not authorized by GNOME: {error}"
                    )
                    dialog.destroy()
                    return
            set_push_to_talk_combo(dialog.result_combo)
            try:
                self.daemon.set_push_to_talk_combo(dialog.result_combo)
            except HotkeyBackendUnavailableError as exc:
                self._set_switch_status(
                    f"Hotkey saved but not active yet: {exc}"
                )
            else:
                self._set_switch_status(
                    f"Hotkey updated: {format_hotkey_combo(dialog.result_combo)}"
                )
        dialog.destroy()

    def _on_model_selected(self, item, backend: str, model: str) -> None:
        if self._syncing_model_menu:
            return
        if not item.get_active():
            return
        if self._prepare_in_progress:
            self._set_active_model_menu_item(self._active_backend, self._active_model)
            self._set_switch_status("Model preparation already in progress. Please wait.")
            return
        if self._switch_in_progress:
            return
        if (backend, model) == (self._active_backend, self._active_model):
            return

        if backend in API_BACKENDS:
            status = self._api_key_status_for_backend(backend)
            if not status.ready:
                label = API_BACKEND_LABELS.get(backend, backend)
                self._set_active_model_menu_item(self._active_backend, self._active_model)
                self._set_switch_status(
                    f"{label} API key: {status.status}. "
                    "Add a valid key before selecting this model."
                )
                return

        if self._requires_preparation(
            backend=backend,
            model=model,
            device=self._stt_device,
            compute_type=self._stt_compute_type,
        ):
            self._set_active_model_menu_item(self._active_backend, self._active_model)
            self._start_prepare_for_switch(
                backend=backend,
                model=model,
                device=self._stt_device,
                compute_type=self._stt_compute_type,
            )
            return

        self._start_switch(
            backend=backend,
            model=model,
            device=_device_for_backend(backend, self._stt_device),
            compute_type=_compute_type_for_backend(backend, self._stt_compute_type),
        )

    def _on_profile_selected(self, item, device: str, compute_type: str) -> None:
        if self._syncing_profile_menu:
            return
        if not item.get_active():
            return
        if self._prepare_in_progress:
            self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
            self._set_switch_status("Model preparation already in progress. Please wait.")
            return
        if self._switch_in_progress:
            return
        target_backend = "faster-whisper"
        # Keep the active model only when the user EXPLICITLY saved one; otherwise
        # (including a resolver-chosen turbo on a CUDA box) resolve for the NEWLY
        # selected device, so picking the CPU profile can't pin turbo on a weak CPU.
        saved_model = load_config().stt_model
        target_model = (
            self._active_model
            if (self._active_backend == "faster-whisper" and saved_model)
            else resolve_default_local_model(device)
        )
        if (
            self._active_backend == target_backend
            and (device, compute_type) == (self._stt_device, self._stt_compute_type)
        ):
            return

        if self._requires_preparation(
            backend=target_backend,
            model=target_model,
            device=device,
            compute_type=compute_type,
        ):
            self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
            self._start_prepare_for_switch(
                backend=target_backend,
                model=target_model,
                device=device,
                compute_type=compute_type,
            )
            return

        self._start_switch(
            backend=target_backend,
            model=target_model,
            device=device,
            compute_type=compute_type,
        )

    def _requires_preparation(
        self,
        *,
        backend: str,
        model: str,
        device: str,
        compute_type: str,
    ) -> bool:
        del backend, model, device, compute_type
        return False

    def _start_prepare_for_switch(
        self,
        *,
        backend: str,
        model: str,
        device: str,
        compute_type: str,
    ) -> None:
        self._prepare_counter += 1
        prepare_id = self._prepare_counter
        self._latest_prepare_id = prepare_id
        self._prepare_in_progress = True
        self._prepare_started_monotonic = time.monotonic()
        self._prepare_target_backend = backend
        self._prepare_target_model = model
        self._prepare_target_device = device
        self._prepare_target_compute_type = compute_type
        self._pending_switch_after_prepare = (backend, model, device, compute_type)
        self._set_switch_status(
            self._build_prepare_status_message(
                backend=backend,
                model=model,
                elapsed_seconds=0,
            )
        )
        env = os.environ.copy()
        env["DICTATE_DISABLE_STARTUP_LOG"] = "1"
        env.setdefault("HF_HUB_DISABLE_XET", "1")
        cmd = [
            sys.executable,
            "-m",
            "dictate",
            "prepare-model",
            "--stt-backend",
            backend,
            "--model",
            model,
            "--device",
            device,
            "--compute-type",
            compute_type,
        ]
        try:
            self._prepare_process = subprocess.Popen(
                cmd,
                env=env,
            )
        except Exception as exc:  # noqa: BLE001
            self._prepare_in_progress = False
            self._prepare_process = None
            self._pending_switch_after_prepare = None
            mark_model_failed(
                backend=backend,
                model=model,
                device=device,
                compute_type=compute_type,
                error_message=str(exc),
            )
            self._set_switch_status("Failed to start model preparation subprocess.")
            dialog = Gtk.MessageDialog(
                transient_for=None,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                text=f"Failed to prepare {backend} / {model} ({device}, {compute_type})",
            )
            dialog.format_secondary_text(str(exc))
            dialog.run()
            dialog.destroy()
            return
        GLib.timeout_add_seconds(1, self._poll_prepare_process, prepare_id)
        GLib.timeout_add_seconds(PREPARE_ABORT_SECONDS, self._on_prepare_timeout, prepare_id)

    def _poll_prepare_process(self, prepare_id: int) -> bool:
        if prepare_id != self._latest_prepare_id:
            return GLib.SOURCE_REMOVE

        process = self._prepare_process
        if process is None:
            return GLib.SOURCE_REMOVE

        if process.poll() is None:
            self._set_switch_status(
                self._build_prepare_status_message(
                    backend=self._prepare_target_backend,
                    model=self._prepare_target_model,
                    elapsed_seconds=int(time.monotonic() - self._prepare_started_monotonic),
                )
            )
            return True

        return_code = process.returncode
        self._prepare_process = None
        self._prepare_in_progress = False

        backend = self._prepare_target_backend
        model = self._prepare_target_model
        device = self._prepare_target_device
        compute_type = self._prepare_target_compute_type

        if return_code == 0:
            mark_model_prepared(
                backend=backend,
                model=model,
                device=device,
                compute_type=compute_type,
            )
            print(
                f"Model prepared: {backend}/{model} ({device}/{compute_type})",
                file=sys.stderr,
            )
            pending = self._pending_switch_after_prepare
            self._pending_switch_after_prepare = None
            if pending is not None:
                self._start_switch(
                    backend=pending[0],
                    model=pending[1],
                    device=pending[2],
                    compute_type=pending[3],
                )
            else:
                self._set_switch_status("Model preparation complete.")
                GLib.timeout_add_seconds(
                    SWITCH_STATUS_CLEAR_SECONDS,
                    self._clear_status_for_switch_id,
                    self._latest_switch_id,
                )
            return GLib.SOURCE_REMOVE

        error_message = (
            get_model_error(
                backend=backend,
                model=model,
                device=device,
                compute_type=compute_type,
            )
            or f"prepare command exited with code {return_code}"
        )
        mark_model_failed(
            backend=backend,
            model=model,
            device=device,
            compute_type=compute_type,
            error_message=error_message,
        )
        self._pending_switch_after_prepare = None
        self._set_active_model_menu_item(self._active_backend, self._active_model)
        self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
        self._set_switch_status("Model preparation failed. Keeping previous model.")
        GLib.timeout_add_seconds(
            SWITCH_STATUS_CLEAR_SECONDS,
            self._clear_status_for_switch_id,
            self._latest_switch_id,
        )
        dialog = Gtk.MessageDialog(
            transient_for=None,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=f"Failed to prepare {backend} / {model} ({device}, {compute_type})",
        )
        dialog.format_secondary_text(error_message)
        dialog.run()
        dialog.destroy()
        return GLib.SOURCE_REMOVE

    def _on_prepare_timeout(self, prepare_id: int) -> bool:
        if prepare_id != self._latest_prepare_id:
            return GLib.SOURCE_REMOVE
        if not self._prepare_in_progress:
            return GLib.SOURCE_REMOVE

        process = self._prepare_process
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            error_message = (
                get_model_error(
                    backend=self._prepare_target_backend,
                    model=self._prepare_target_model,
                    device=self._prepare_target_device,
                    compute_type=self._prepare_target_compute_type,
                )
                or f"prepare command timed out after {PREPARE_ABORT_SECONDS}s"
            )
        else:
            error_message = f"timed out after {PREPARE_ABORT_SECONDS}s"

        backend = self._prepare_target_backend
        model = self._prepare_target_model
        device = self._prepare_target_device
        compute_type = self._prepare_target_compute_type
        mark_model_failed(
            backend=backend,
            model=model,
            device=device,
            compute_type=compute_type,
            error_message=error_message,
        )
        self._prepare_process = None
        self._prepare_in_progress = False
        self._pending_switch_after_prepare = None
        self._set_active_model_menu_item(self._active_backend, self._active_model)
        self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
        self._set_switch_status(
            "Model preparation timed out. Keeping previous backend."
        )
        GLib.timeout_add_seconds(
            SWITCH_STATUS_CLEAR_SECONDS,
            self._clear_status_for_switch_id,
            self._latest_switch_id,
        )
        return GLib.SOURCE_REMOVE

    def _start_switch(
        self,
        *,
        backend: str,
        model: str,
        device: str,
        compute_type: str,
    ) -> None:
        self._switch_counter += 1
        switch_id = self._switch_counter
        self._latest_switch_id = switch_id
        self._switch_in_progress = True
        self._switch_background_mode = False
        self._switch_started_monotonic = time.monotonic()
        self._switch_target_backend = backend
        self._switch_target_model = model
        # Keep checkmarks on the currently active selection until the new backend/model is ready.
        self._set_active_model_menu_item(self._active_backend, self._active_model)
        self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
        self._set_switch_status(self._build_switch_status_message(backend, model))
        self._set_switch_menu_sensitive(False)
        threading.Thread(
            target=self._switch_worker,
            args=(switch_id, backend, model, device, compute_type),
            daemon=True,
        ).start()
        GLib.timeout_add_seconds(1, self._tick_switch_status, switch_id)
        GLib.timeout_add_seconds(
            SWITCH_LOCK_SECONDS,
            self._on_switch_timeout,
            switch_id,
            backend,
            model,
            device,
            compute_type,
        )
        GLib.timeout_add_seconds(
            SWITCH_ABORT_SECONDS,
            self._on_switch_abort_timeout,
            switch_id,
            backend,
            model,
            device,
            compute_type,
        )

    def _switch_worker(
        self,
        switch_id: int,
        backend: str,
        model: str,
        device: str,
        compute_type: str,
    ) -> None:
        print(
            f"Switching STT to {backend} / {model} on {device} ({compute_type})...",
            file=sys.stderr,
        )
        loaded_device = device
        loaded_compute_type = compute_type
        try:
            _apply_api_key_command_from_config(backend)
            if backend in API_BACKENDS:
                status = api_key_status(backend, validate_remote=True)
                if not status.ready:
                    label = API_BACKEND_LABELS.get(backend, backend)
                    raise RuntimeError(f"{label} API key status: {status.status}")
            stt = create_speech_to_text(
                backend=backend,  # type: ignore[arg-type]
                model=model,
                device=device,  # type: ignore[arg-type]
                compute_type=compute_type,  # type: ignore[arg-type]
            )
            _ = stt.model
        except Exception as exc:  # noqa: BLE001
            if self._should_retry_switch_on_cpu(exc, backend=backend, requested_device=device):
                print(
                    (
                        f"Switch failed on {device} for {backend}/{model}: {exc}. "
                        "Retrying activation on CPU."
                    ),
                    file=sys.stderr,
                )
                try:
                    loaded_device = "cpu"
                    loaded_compute_type = "int8"
                    stt = create_speech_to_text(
                        backend=backend,  # type: ignore[arg-type]
                        model=model,
                        device=loaded_device,  # type: ignore[arg-type]
                        compute_type=loaded_compute_type,  # type: ignore[arg-type]
                    )
                    _ = stt.model
                except Exception as retry_exc:  # noqa: BLE001
                    GLib.idle_add(
                        self._finalize_switch,
                        switch_id,
                        False,
                        backend,
                        model,
                        device,
                        compute_type,
                        str(retry_exc),
                        True,
                        None,
                    )
                    return
            else:
                GLib.idle_add(
                    self._finalize_switch,
                    switch_id,
                    False,
                    backend,
                    model,
                    device,
                    compute_type,
                    str(exc),
                    True,
                    None,
                )
                return

        GLib.idle_add(
            self._finalize_switch,
            switch_id,
            True,
            backend,
            model,
            loaded_device,
            loaded_compute_type,
            "",
            True,
            stt,
        )

    def _finalize_switch(
        self,
        switch_id: int,
        ok: bool,
        backend: str,
        model: str,
        device: str,
        compute_type: str,
        error_message: str,
        notify_failure: bool,
        loaded_stt: object | None,
    ) -> bool:
        if switch_id != self._latest_switch_id:
            if loaded_stt is not None:
                self._release_cuda_memory_best_effort()
            return GLib.SOURCE_REMOVE
        try:
            if ok:
                if loaded_stt is not None:
                    self.daemon.switch_speech_to_text(
                        loaded_stt,  # type: ignore[arg-type]
                        hotwords=load_config().hotwords_for_backend(backend),
                    )
                set_stt_selection(backend=backend, model=model)
                set_stt_runtime_profile(device=device, compute_type=compute_type)
                self._active_backend = backend
                self._active_model = model
                self._stt_device = device
                self._stt_compute_type = compute_type
                mark_model_prepared(
                    backend=backend,
                    model=model,
                    device=device,
                    compute_type=compute_type,
                )
                print(
                    f"STT switched to {backend} / {model} on {device} ({compute_type})",
                    file=sys.stderr,
                )
                self._set_active_model_menu_item(backend, model)
                self._set_active_profile_menu_item(device, compute_type)
                self._sync_capability_menu_items()
                self._update_model_status_label()
                self._set_switch_status(f"Switched to {backend} / {model}.")
                self._complete_pending_api_key_clear(switch_id)
                GLib.timeout_add_seconds(
                    SWITCH_STATUS_CLEAR_SECONDS,
                    self._clear_status_for_switch_id,
                    switch_id,
                )
            else:
                print(
                    (
                        f"STT switch failed ({backend}/{model} "
                        f"{device}/{compute_type}): {error_message}"
                    ),
                    file=sys.stderr,
                )
                mark_model_failed(
                    backend=backend,
                    model=model,
                    device=device,
                    compute_type=compute_type,
                    error_message=error_message,
                )
                self._set_active_model_menu_item(self._active_backend, self._active_model)
                self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
                self._clear_pending_api_key_clear(switch_id)
                self._set_switch_status("Switch failed. Keeping previous model.")
                GLib.timeout_add_seconds(
                    SWITCH_STATUS_CLEAR_SECONDS,
                    self._clear_status_for_switch_id,
                    switch_id,
                )
                if notify_failure:
                    dialog = Gtk.MessageDialog(
                        transient_for=None,
                        flags=0,
                        message_type=Gtk.MessageType.ERROR,
                        buttons=Gtk.ButtonsType.CLOSE,
                        text=f"Failed to switch to {backend} / {model} ({device}, {compute_type})",
                    )
                    dialog.format_secondary_text(error_message)
                    dialog.run()
                    dialog.destroy()
                self._release_cuda_memory_best_effort()
        finally:
            # Always release the UI lock even if GTK menu updates/dialog handling fail.
            self._switch_in_progress = False
            self._switch_background_mode = False
            self._set_switch_menu_sensitive(True)
        return GLib.SOURCE_REMOVE

    def _on_switch_timeout(
        self,
        switch_id: int,
        backend: str,
        model: str,
        device: str,
        compute_type: str,
    ) -> bool:
        if switch_id != self._latest_switch_id:
            return GLib.SOURCE_REMOVE
        if not self._switch_in_progress:
            return GLib.SOURCE_REMOVE

        print(
            (
                f"STT switch still running after {SWITCH_LOCK_SECONDS}s "
                f"({backend}/{model} {device}/{compute_type}); unlocking menu."
            ),
            file=sys.stderr,
        )
        self._switch_in_progress = False
        self._switch_background_mode = True
        self._set_switch_menu_sensitive(True)
        self._set_switch_status(
            "Still downloading/loading in background. "
            "You can keep using current model or choose another."
        )
        return GLib.SOURCE_REMOVE

    def _on_switch_abort_timeout(
        self,
        switch_id: int,
        backend: str,
        model: str,
        device: str,
        compute_type: str,
    ) -> bool:
        if switch_id != self._latest_switch_id:
            return GLib.SOURCE_REMOVE
        if not self._switch_in_progress and not self._switch_background_mode:
            return GLib.SOURCE_REMOVE

        print(
            (
                f"STT switch timed out after {SWITCH_ABORT_SECONDS}s "
                f"({backend}/{model} {device}/{compute_type}); abandoning attempt."
            ),
            file=sys.stderr,
        )
        mark_model_failed(
            backend=backend,
            model=model,
            device=device,
            compute_type=compute_type,
            error_message=f"switch timed out after {SWITCH_ABORT_SECONDS}s",
        )

        # Invalidate this pending switch so any late worker completion is ignored.
        self._switch_counter += 1
        self._latest_switch_id = self._switch_counter
        self._switch_in_progress = False
        self._switch_background_mode = False
        self._clear_pending_api_key_clear(switch_id)
        self._set_switch_menu_sensitive(True)
        self._set_active_model_menu_item(self._active_backend, self._active_model)
        self._set_active_profile_menu_item(self._stt_device, self._stt_compute_type)
        self._set_switch_status(
            "Switch timed out. Keeping previous backend."
        )
        self._release_cuda_memory_best_effort()
        GLib.timeout_add_seconds(
            SWITCH_STATUS_CLEAR_SECONDS,
            self._clear_status_for_switch_id,
            self._latest_switch_id,
        )
        return GLib.SOURCE_REMOVE

    def _tick_switch_status(self, switch_id: int) -> bool:
        if switch_id != self._latest_switch_id:
            return GLib.SOURCE_REMOVE
        if self._switch_in_progress:
            self._set_switch_status(
                self._build_switch_status_message(
                    self._switch_target_backend,
                    self._switch_target_model,
                    elapsed_seconds=int(time.monotonic() - self._switch_started_monotonic),
                )
            )
            return True
        if self._switch_background_mode:
            self._set_switch_status(
                self._build_switch_status_message(
                    self._switch_target_backend,
                    self._switch_target_model,
                    elapsed_seconds=int(time.monotonic() - self._switch_started_monotonic),
                    background=True,
                )
            )
            return True
        return GLib.SOURCE_REMOVE

    def _clear_status_for_switch_id(self, switch_id: int) -> bool:
        if switch_id != self._latest_switch_id:
            return GLib.SOURCE_REMOVE
        if self._switch_in_progress or self._switch_background_mode or self._prepare_in_progress:
            return GLib.SOURCE_REMOVE
        self._set_switch_status(None)
        return GLib.SOURCE_REMOVE

    def _set_switch_menu_sensitive(self, sensitive: bool) -> None:
        for item in self._model_items.values():
            item.set_sensitive(sensitive)
        for item in self._profile_items.values():
            item.set_sensitive(sensitive)

    def _sync_capability_menu_items(self) -> None:
        self._update_model_status_label()

    def _complete_pending_api_key_clear(self, switch_id: int) -> None:
        backend = self._pending_api_key_clear_backend
        if backend is None or switch_id != self._pending_api_key_clear_switch_id:
            return
        self._clear_pending_api_key_clear(switch_id)
        try:
            clear_api_key(backend)
        except ApiKeyStorageError as exc:
            label = API_BACKEND_LABELS.get(backend, backend)
            self._set_switch_status(f"Local Whisper active; {label} API key not cleared.")
            dialog = Gtk.MessageDialog(
                transient_for=None,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                text=f"{label} API key not cleared",
            )
            dialog.format_secondary_text(str(exc))
            dialog.run()
            dialog.destroy()
            return
        label = API_BACKEND_LABELS.get(backend, backend)
        self._build_menu()
        self._set_switch_status(f"{label} API key cleared.")

    def _clear_pending_api_key_clear(self, switch_id: int) -> None:
        if switch_id != self._pending_api_key_clear_switch_id:
            return
        self._pending_api_key_clear_backend = None
        self._pending_api_key_clear_switch_id = 0

    def _reload_active_api_backend(self) -> None:
        if self._switch_in_progress or self._prepare_in_progress:
            return
        if not _api_key_available_for_backend(self._active_backend):
            return
        self._start_switch(
            backend=self._active_backend,
            model=self._active_model,
            device=_device_for_backend(self._active_backend, self._stt_device),
            compute_type=_compute_type_for_backend(self._active_backend, self._stt_compute_type),
        )

    def _api_key_status_for_backend(self, backend: str) -> ApiKeyStatus:
        if backend not in API_BACKENDS:
            return ApiKeyStatus(backend=backend, status="None")
        status = api_key_status(backend, include_command=False, log_failures=False)
        if (
            _api_key_command_configured_for_backend(backend)
            and status.source in {None, "secret-store"}
        ):
            return ApiKeyStatus(backend=backend, status="Ready", source="api-key-command")
        return status

    def _update_model_status_label(self) -> None:
        if not hasattr(self, "model_status_label"):
            return
        if self._active_backend == "faster-whisper":
            label = f"Model: Local / {self._active_model} ({_local_runtime_name(self._stt_device)})"
        else:
            provider = API_BACKEND_LABELS.get(self._active_backend, self._active_backend)
            label = f"Model: {provider} / {self._active_model}"
        self.model_status_label.set_text(label)

    def _set_switch_status(self, message: str | None) -> None:
        if not hasattr(self, "switch_status_item"):
            return
        if message:
            self.switch_status_label.set_text(message)
            self.switch_status_item.show_all()
            return
        self.switch_status_item.hide()

    def _on_daemon_status(self, message: str | None) -> None:
        GLib.idle_add(self._show_daemon_status, message)

    def _show_daemon_status(self, message: str | None) -> bool:
        self._daemon_status_counter += 1
        status_id = self._daemon_status_counter
        self._set_switch_status(message)
        if message:
            GLib.timeout_add_seconds(
                SWITCH_STATUS_CLEAR_SECONDS,
                self._clear_daemon_status,
                status_id,
            )
        return GLib.SOURCE_REMOVE

    def _clear_daemon_status(self, status_id: int) -> bool:
        if status_id != self._daemon_status_counter:
            return GLib.SOURCE_REMOVE
        if self._switch_in_progress or self._switch_background_mode or self._prepare_in_progress:
            return GLib.SOURCE_REMOVE
        self._set_switch_status(None)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _build_switch_status_message(
        backend: str,
        model: str,
        *,
        elapsed_seconds: int | None = None,
        background: bool = False,
    ) -> str:
        model_label = model.split("/")[-1]
        elapsed = ""
        if elapsed_seconds is not None:
            minutes, seconds = divmod(max(elapsed_seconds, 0), 60)
            elapsed = f" ({minutes:02d}:{seconds:02d})"
        if background:
            return f"{backend} / {model_label} still loading{elapsed}. You can use current model."
        return f"Switching to {backend} / {model_label}{elapsed}..."

    @staticmethod
    def _build_prepare_status_message(
        *,
        backend: str,
        model: str,
        elapsed_seconds: int,
    ) -> str:
        model_label = model.split("/")[-1]
        minutes, seconds = divmod(max(elapsed_seconds, 0), 60)
        elapsed = f"{minutes:02d}:{seconds:02d}"
        return f"Preparing {backend} / {model_label} ({elapsed})..."

    @staticmethod
    def _should_retry_switch_on_cpu(exc: Exception, *, backend: str, requested_device: str) -> bool:
        if backend != "faster-whisper":
            return False
        if requested_device not in {"auto", "cuda"}:
            return False
        message = str(exc).lower()
        return any(
            token in message
            for token in (
                "cuda-capable device(s) is/are busy or unavailable",
                "cuda is not available",
                "cuda failed",
                "cuda unavailable",
                "cuda out of memory",
                "out of memory",
            )
        )

    @staticmethod
    def _release_cuda_memory_best_effort() -> None:
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:  # noqa: BLE001
            return

    def _set_active_model_menu_item(self, backend: str, model: str) -> None:
        item = self._model_items.get((backend, model))
        if item is None:
            return
        self._syncing_model_menu = True
        try:
            item.set_active(True)
        finally:
            self._syncing_model_menu = False

    def _set_active_profile_menu_item(self, device: str, compute_type: str) -> None:
        item = self._profile_items.get((device, compute_type))
        if item is None:
            return
        self._syncing_profile_menu = True
        try:
            item.set_active(True)
        finally:
            self._syncing_profile_menu = False

    def _on_quit(self, _item):
        if self._quitting:
            return
        self._quitting = True

        try:
            self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.PASSIVE)
            self.indicator.set_menu(None)
        except Exception:  # noqa: BLE001
            pass

        GLib.idle_add(Gtk.main_quit)

        def shutdown_background() -> None:
            try:
                self.daemon.shutdown()
            except Exception as exc:  # noqa: BLE001
                print(f"Tray shutdown error: {exc}", file=sys.stderr)

        threading.Thread(target=shutdown_background, daemon=True).start()

    def run(self):
        """Start daemon threads, then run GTK main loop (blocks)."""
        try:
            self.daemon.start()
        except HotkeyBackendUnavailableError as exc:
            self._set_switch_status(
                f"Hotkey not active yet: {exc}. Open Hotkeys to retry authorization."
            )
            print(f"Hotkey backend unavailable: {exc}", file=sys.stderr)

        # Allow terminal or launcher shutdown signals to exit cleanly.
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._quit_from_signal)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._quit_from_signal)

        print("dictate running (tray icon active)", file=sys.stderr)
        print(
            f"  Hold {format_hotkey_combo(self.daemon.push_to_talk_combo)} to dictate",
            file=sys.stderr,
        )
        Gtk.main()

    def _quit_from_signal(self):
        self._on_quit(None)
        return GLib.SOURCE_REMOVE
