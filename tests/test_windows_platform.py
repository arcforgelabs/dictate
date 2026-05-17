from __future__ import annotations

import ast
import os
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import platform_paths
from dictate.config import Config
from dictate.doctor import _desktop_entry_path
from dictate.outputs import PynputOutput, detect_session_type, resolve_typing_backend


class WindowsPlatformTests(unittest.TestCase):
    def test_windows_config_dir_uses_appdata(self) -> None:
        with patch("dictate.platform_paths.sys.platform", "win32"):
            with patch.dict("os.environ", {"APPDATA": r"C:\Users\sam\AppData\Roaming"}):
                self.assertEqual(
                    platform_paths.user_config_dir(),
                    Path(r"C:\Users\sam\AppData\Roaming") / "dictate",
                )

    def test_windows_session_type(self) -> None:
        with patch("dictate.outputs.sys.platform", "win32"):
            self.assertEqual(detect_session_type(), "windows")

    def test_windows_auto_typing_backend_uses_pynput(self) -> None:
        with patch("dictate.outputs.detect_session_type", return_value="windows"):
            with patch("dictate.outputs.python_module_available", return_value=True):
                self.assertIsInstance(resolve_typing_backend("auto"), PynputOutput)

    def test_windows_doctor_checks_start_menu_shortcut_path(self) -> None:
        with patch("dictate.doctor.sys.platform", "win32"):
            with patch.dict("os.environ", {"APPDATA": r"C:\Users\sam\AppData\Roaming"}):
                self.assertEqual(
                    _desktop_entry_path(),
                    Path(r"C:\Users\sam\AppData\Roaming")
                    / "Microsoft"
                    / "Windows"
                    / "Start Menu"
                    / "Programs"
                    / "Dictate.lnk",
                )

    def test_windows_control_defaults_match_repo_stt_default(self) -> None:
        source_path = Path(__file__).resolve().parents[1] / "src" / "dictate" / "windows_control.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        assignments = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"DEFAULT_BACKEND", "DEFAULT_MODELS"}
        }

        self.assertEqual(assignments["DEFAULT_BACKEND"], "faster-whisper")
        self.assertEqual(assignments["DEFAULT_MODELS"]["faster-whisper"], "turbo")

    def test_windows_controls_apply_configured_key_command(self) -> None:
        fake_tkinter = types.ModuleType("tkinter")
        fake_tkinter.messagebox = types.SimpleNamespace()
        fake_tkinter.ttk = types.SimpleNamespace()

        with (
            patch.dict("sys.modules", {"tkinter": fake_tkinter}),
            patch.dict("os.environ", {}, clear=True),
            patch(
                "dictate.windows_control.load_config",
                return_value=Config(xai_api_key_command="/usr/bin/printf key"),
            ),
        ):
            from dictate.windows_control import _apply_api_key_command_from_config

            _apply_api_key_command_from_config("xai")

            self.assertEqual(
                os.environ.get("DICTATE_XAI_API_KEY_COMMAND"),
                "/usr/bin/printf key",
            )

    def test_windows_installer_shortcut_starts_tray_launcher(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('Join-Path $ScriptsDir "dictate-tray.cmd"', script)
        self.assertIn('Join-Path $ScriptsDir "dictate-tray.vbs"', script)
        self.assertIn('"%SCRIPT_DIR%dictate.exe" --type-backend pynput %*', script)
        self.assertIn(
            'Install-StartMenuShortcut -TargetPath (Join-Path $scriptsDir "dictate-tray.vbs")',
            script,
        )

    def test_hosted_windows_bootstrap_downloads_public_source_archive(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("https://github.com/arcforgelabs/dictate/archive/refs/heads/master.zip", script)
        self.assertIn("Invoke-WebRequest -UseBasicParsing", script)
        self.assertIn("install-windows.ps1", script)

    def test_windows_control_restart_stops_tray_processes(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "src" / "dictate" / "windows_control.py"
        ).read_text(encoding="utf-8")

        self.assertIn("*dictate.exe* --type-backend pynput*", source)
        self.assertIn("*pythonw.exe* -m dictate --type-backend pynput*", source)


if __name__ == "__main__":
    unittest.main()
