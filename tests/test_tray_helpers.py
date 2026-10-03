from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Import tray's non-GTK dependencies up front: patch.dict restores sys.modules on
# exit, and evicting numpy there makes the next tray import fail to reload it.
import dictate.daemon  # noqa: F401


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


def _profile_self(*, active_backend: str, active_model: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        _syncing_profile_menu=False,
        _prepare_in_progress=False,
        _switch_in_progress=False,
        _active_backend=active_backend,
        _active_model=active_model,
        _stt_device="cuda",
        _stt_compute_type="int8",
        _requires_preparation=lambda **_kw: False,
        _start_switch=MagicMock(),
        _start_prepare_for_switch=MagicMock(),
        _set_active_profile_menu_item=MagicMock(),
        _set_switch_status=MagicMock(),
    )


class TrayHelperTests(unittest.TestCase):
    def test_local_backend_preserves_auto_device(self) -> None:
        tray = _import_tray_with_fake_gi()

        self.assertEqual(tray._device_for_backend("parakeet", "auto"), "auto")
        self.assertEqual(tray._device_for_backend("parakeet", "cuda"), "cuda")
        self.assertEqual(tray._device_for_backend("parakeet-pyannote", "cuda"), "auto")

    def test_profile_selection_switches_other_backend_to_local_default(self) -> None:
        tray = _import_tray_with_fake_gi()
        fake_self = _profile_self(active_backend="parakeet-pyannote", active_model="parakeet-tdt-0.6b-v3")
        item = types.SimpleNamespace(get_active=lambda: True)

        tray.TrayIcon._on_profile_selected(fake_self, item, "cpu", "int8")

        fake_self._start_switch.assert_called_once()
        kwargs = fake_self._start_switch.call_args.kwargs
        self.assertEqual(kwargs["backend"], "parakeet")
        self.assertEqual(kwargs["model"], "parakeet-tdt-0.6b-v2")
        self.assertEqual(kwargs["device"], "cpu")

    def test_profile_selection_keeps_active_local_model(self) -> None:
        tray = _import_tray_with_fake_gi()
        fake_self = _profile_self(active_backend="parakeet", active_model="parakeet-tdt-0.6b-v3")
        item = types.SimpleNamespace(get_active=lambda: True)

        tray.TrayIcon._on_profile_selected(fake_self, item, "cpu", "int8")

        fake_self._start_switch.assert_called_once()
        self.assertEqual(fake_self._start_switch.call_args.kwargs["model"], "parakeet-tdt-0.6b-v3")


if __name__ == "__main__":
    unittest.main()
