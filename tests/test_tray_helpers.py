from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch


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


if __name__ == "__main__":
    unittest.main()
