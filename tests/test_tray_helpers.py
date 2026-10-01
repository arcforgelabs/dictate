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


class TrayHelperTests(unittest.TestCase):
    def test_local_backend_keeps_cpu_compute_type(self) -> None:
        tray = _import_tray_with_fake_gi()

        self.assertEqual(tray._compute_type_for_backend("parakeet", "float32"), "float32")
        self.assertEqual(tray._compute_type_for_backend("parakeet", "float16"), "int8")
        self.assertEqual(tray._compute_type_for_backend("parakeet-pyannote", "float32"), "int8")

    def test_tray_has_no_device_profiles(self) -> None:
        tray = _import_tray_with_fake_gi()

        self.assertFalse(hasattr(tray, "LOCAL_RUNTIME_PROFILES"))
        self.assertFalse(hasattr(tray.TrayIcon, "_on_profile_selected"))
        self.assertFalse(hasattr(tray.TrayIcon, "_should_retry_switch_on_cpu"))

    def test_model_selection_switches_without_a_device(self) -> None:
        tray = _import_tray_with_fake_gi()
        fake_self = types.SimpleNamespace(
            _syncing_model_menu=False,
            _prepare_in_progress=False,
            _switch_in_progress=False,
            _active_backend="parakeet",
            _active_model="parakeet-tdt-0.6b-v2",
            _stt_compute_type="int8",
            _requires_preparation=lambda **_kw: False,
            _start_switch=MagicMock(),
            _start_prepare_for_switch=MagicMock(),
            _set_active_model_menu_item=MagicMock(),
            _set_switch_status=MagicMock(),
        )
        item = types.SimpleNamespace(get_active=lambda: True)

        tray.TrayIcon._on_model_selected(fake_self, item, "parakeet", "parakeet-tdt-0.6b-v3")

        fake_self._start_switch.assert_called_once_with(
            backend="parakeet",
            model="parakeet-tdt-0.6b-v3",
            compute_type="int8",
        )


if __name__ == "__main__":
    unittest.main()
