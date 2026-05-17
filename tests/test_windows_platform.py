from __future__ import annotations

import ast
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import platform_paths
from dictate.config import Config
from dictate.doctor import (
    _desktop_entry_path,
    _fix_items,
    _install_linux_desktop_entry,
    _update_paths,
    build_parser,
)
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

    def test_doctor_parser_accepts_fix_and_update_paths(self) -> None:
        args = build_parser().parse_args(["--quick", "--fix", "--update-paths"])

        self.assertTrue(args.quick)
        self.assertTrue(args.fix)
        self.assertTrue(args.update_paths)

    def test_windows_doctor_update_paths_include_hosted_installer(self) -> None:
        with patch("dictate.doctor.sys.platform", "win32"):
            updates = _update_paths()

        self.assertTrue(any("raw.githubusercontent.com/arcforgelabs/dictate" in item for item in updates))
        self.assertTrue(any("install-windows.ps1" in item for item in updates))

    def test_doctor_fix_items_include_launcher_repair(self) -> None:
        report = types.SimpleNamespace(
            warnings=["Desktop entry not found: C:\\Users\\sam\\Dictate.lnk"],
            errors=[],
        )

        self.assertIn(
            "Run `dictate doctor --fix` to recreate Start Menu/Desktop launchers.",
            _fix_items(report),
        )

    def test_doctor_fix_can_recreate_linux_desktop_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("dictate.doctor.sys.platform", "linux"),
                patch.dict("os.environ", {"XDG_DATA_HOME": temp_dir}),
                patch("dictate.doctor.shutil.which", return_value="/usr/bin/dictate"),
                patch("dictate.doctor.subprocess.run") as run,
            ):
                _install_linux_desktop_entry()
                desktop_path = Path(temp_dir) / "applications" / "dictate.desktop"
                content = desktop_path.read_text(encoding="utf-8")

        self.assertIn("Exec=/usr/bin/dictate", content)
        run.assert_called_once()

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

    def test_windows_installer_uses_supported_python_range(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("(3, 11) <= sys.version_info < (3, 13)", script)
        self.assertIn('@("-3.12")', script)
        self.assertIn("Python 3.11 or 3.12 was not found", script)

    def test_windows_installer_repairs_vc_runtime_dependency(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("function Ensure-VcRuntime", script)
        self.assertIn("https://aka.ms/vs/17/release/vc_redist.x64.exe", script)
        self.assertIn("Ensure-VcRuntime", script)

    def test_doctor_fix_items_include_vc_runtime_hint(self) -> None:
        report = types.SimpleNamespace(
            warnings=[],
            errors=["faster-whisper package is not importable."],
        )

        with patch("dictate.doctor.sys.platform", "win32"):
            self.assertIn(
                "Install or repair the Microsoft Visual C++ runtime, then rerun `dictate doctor`.",
                _fix_items(report),
            )

    def test_doctor_fix_items_use_linux_dependency_hint(self) -> None:
        report = types.SimpleNamespace(
            warnings=[],
            errors=["faster-whisper package is not importable."],
        )

        with patch("dictate.doctor.sys.platform", "linux"):
            self.assertIn(
                "Run `./install.sh` or reinstall Dictate with local STT dependencies.",
                _fix_items(report),
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
