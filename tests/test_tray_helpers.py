from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _import_tray_with_fake_gi():
    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_args, **_kwargs: None
    fake_repository = types.ModuleType("gi.repository")
    fake_repository.AyatanaAppIndicator3 = types.SimpleNamespace()
    fake_repository.GLib = types.SimpleNamespace(SOURCE_REMOVE=False)
    fake_repository.Gtk = types.SimpleNamespace(
        Menu=object,
        RadioMenuItem=object,
        Widget=object,
        Window=object,
    )
    with patch.dict(
        sys.modules,
        {
            "gi": fake_gi,
            "gi.repository": fake_repository,
        },
    ):
        sys.modules.pop("dictate.tray", None)
        return importlib.import_module("dictate.tray")


class TrayHelperTests(unittest.TestCase):
    def test_local_backend_preserves_auto_device(self) -> None:
        tray = _import_tray_with_fake_gi()

        self.assertEqual(tray._device_for_backend("faster-whisper", "auto"), "auto")
        self.assertEqual(tray._device_for_backend("faster-whisper", "cuda"), "cuda")
        self.assertEqual(tray._device_for_backend("openai", "cuda"), "auto")

    def test_command_status_overrides_stale_stored_key_status(self) -> None:
        tray = _import_tray_with_fake_gi()

        with (
            patch(
                "dictate.tray.api_key_status",
                return_value=tray.ApiKeyStatus(
                    backend="xai",
                    status="Invalid",
                    source="secret-store",
                ),
            ),
            patch("dictate.tray._api_key_command_configured_for_backend", return_value=True),
        ):
            status = tray.TrayIcon._api_key_status_for_backend(object(), "xai")

        self.assertEqual(status.status, "Ready")
        self.assertEqual(status.source, "api-key-command")

    def test_profile_selection_resolves_local_model_for_new_device(self) -> None:
        # P2-2: selecting the CPU profile (on a box whose current device is cuda)
        # must resolve the local model for the NEWLY selected device, not the stale
        # self._stt_device — otherwise turbo gets pinned on the weak CPU.
        tray = _import_tray_with_fake_gi()

        resolved_devices: list[str] = []

        def fake_resolve(device: str) -> str:
            resolved_devices.append(device)
            return "small"

        fake_self = types.SimpleNamespace(
            _syncing_profile_menu=False,
            _prepare_in_progress=False,
            _switch_in_progress=False,
            _active_backend="xai",  # not faster-whisper -> resolver branch
            _active_model="grok-speech-to-text",
            _stt_device="cuda",  # STALE current device
            _stt_compute_type="int8",
            _requires_preparation=lambda **_kw: False,
            _start_switch=MagicMock(),
            _start_prepare_for_switch=MagicMock(),
            _set_active_profile_menu_item=MagicMock(),
            _set_switch_status=MagicMock(),
        )
        item = types.SimpleNamespace(get_active=lambda: True)

        with (
            patch("dictate.tray.resolve_default_local_model", side_effect=fake_resolve),
            patch("dictate.tray.load_config", return_value=types.SimpleNamespace(stt_model=None)),
        ):
            tray.TrayIcon._on_profile_selected(fake_self, item, "cpu", "int8")

        self.assertEqual(resolved_devices, ["cpu"])
        fake_self._start_switch.assert_called_once()
        self.assertEqual(fake_self._start_switch.call_args.kwargs["model"], "small")

    def test_profile_selection_resolves_when_no_explicit_saved_model(self) -> None:
        # P3-B: active model is a resolver-chosen turbo (no explicit saved model) on
        # a CUDA box; selecting the CPU profile must re-resolve for CPU (-> small),
        # NOT keep the stale turbo, which would run turbo on the weak CPU.
        tray = _import_tray_with_fake_gi()

        resolved_devices: list[str] = []

        def fake_resolve(device: str) -> str:
            resolved_devices.append(device)
            return "small"

        fake_self = types.SimpleNamespace(
            _syncing_profile_menu=False,
            _prepare_in_progress=False,
            _switch_in_progress=False,
            _active_backend="faster-whisper",  # already local...
            _active_model="turbo",  # ...but this was resolver-chosen, not saved
            _stt_device="cuda",  # STALE current device
            _stt_compute_type="int8",
            _requires_preparation=lambda **_kw: False,
            _start_switch=MagicMock(),
            _start_prepare_for_switch=MagicMock(),
            _set_active_profile_menu_item=MagicMock(),
            _set_switch_status=MagicMock(),
        )
        item = types.SimpleNamespace(get_active=lambda: True)

        with (
            patch("dictate.tray.resolve_default_local_model", side_effect=fake_resolve),
            patch("dictate.tray.load_config", return_value=types.SimpleNamespace(stt_model=None)),
        ):
            tray.TrayIcon._on_profile_selected(fake_self, item, "cpu", "int8")

        self.assertEqual(resolved_devices, ["cpu"])
        fake_self._start_switch.assert_called_once()
        self.assertEqual(fake_self._start_switch.call_args.kwargs["model"], "small")

    def test_profile_selection_keeps_explicit_saved_local_model(self) -> None:
        # P3-B: an EXPLICIT saved local model is preserved across a profile switch.
        tray = _import_tray_with_fake_gi()

        fake_self = types.SimpleNamespace(
            _syncing_profile_menu=False,
            _prepare_in_progress=False,
            _switch_in_progress=False,
            _active_backend="faster-whisper",
            _active_model="medium",  # explicitly saved
            _stt_device="cuda",
            _stt_compute_type="int8",
            _requires_preparation=lambda **_kw: False,
            _start_switch=MagicMock(),
            _start_prepare_for_switch=MagicMock(),
            _set_active_profile_menu_item=MagicMock(),
            _set_switch_status=MagicMock(),
        )
        item = types.SimpleNamespace(get_active=lambda: True)

        with (
            patch("dictate.tray.resolve_default_local_model", side_effect=AssertionError("should not resolve")),
            patch("dictate.tray.load_config", return_value=types.SimpleNamespace(stt_model="medium")),
        ):
            tray.TrayIcon._on_profile_selected(fake_self, item, "cpu", "int8")

        fake_self._start_switch.assert_called_once()
        self.assertEqual(fake_self._start_switch.call_args.kwargs["model"], "medium")


if __name__ == "__main__":
    unittest.main()
