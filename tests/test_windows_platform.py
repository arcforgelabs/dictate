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
from dictate.startup import set_startup_enabled, startup_enabled, startup_entry_path


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
        with patch("dictate.startup.sys.platform", "win32"):
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
            warnings=[
                "Desktop entry not found: C:\\Users\\sam\\Dictate.lnk",
                "Settings entry not found: C:\\Users\\sam\\Dictate Controls.lnk",
                "Startup entry not found: C:\\Users\\sam\\Startup\\Dictate.lnk",
            ],
            errors=[],
        )

        self.assertIn(
            "Run `dictate doctor --fix` to recreate Start Menu/Desktop launchers.",
            _fix_items(report),
        )
        self.assertIn(
            "Run `dictate doctor --fix` to restore launch-on-startup integration.",
            _fix_items(report),
        )
        self.assertIn(
            "Run `dictate doctor --fix` to recreate the Settings launcher.",
            _fix_items(report),
        )

    def test_doctor_fix_can_recreate_linux_desktop_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "share"
            config_dir = Path(temp_dir) / "config"
            with (
                patch("dictate.startup.sys.platform", "linux"),
                patch.dict(
                    "os.environ",
                    {"XDG_DATA_HOME": str(data_dir), "XDG_CONFIG_HOME": str(config_dir)},
                ),
                patch("dictate.startup.shutil.which", return_value="/usr/bin/dictate"),
                patch("dictate.startup.subprocess.run") as run,
            ):
                _install_linux_desktop_entry()
                desktop_path = data_dir / "applications" / "dictate.desktop"
                settings_path = data_dir / "applications" / "dictate-settings.desktop"
                startup_path = config_dir / "autostart" / "dictate.desktop"
                content = desktop_path.read_text(encoding="utf-8")
                settings_content = settings_path.read_text(encoding="utf-8")
                startup_content = startup_path.read_text(encoding="utf-8")

        self.assertIn("Exec=/usr/bin/dictate", content)
        self.assertIn("Icon=", content)
        self.assertIn("Terminal=false", content)
        self.assertIn("Name=Dictate Settings", settings_content)
        self.assertIn("Exec=/usr/bin/dictate controls", settings_content)
        self.assertIn("X-GNOME-Autostart-enabled=true", startup_content)
        run.assert_called_once()

    def test_linux_startup_toggle_writes_and_removes_autostart_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "config"
            with (
                patch("dictate.startup.sys.platform", "linux"),
                patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config_dir)}),
                patch("dictate.startup.shutil.which", return_value="/usr/bin/dictate"),
            ):
                self.assertFalse(startup_enabled())
                set_startup_enabled(True)
                path = startup_entry_path()
                content = path.read_text(encoding="utf-8")

                self.assertTrue(startup_enabled())
                self.assertIn("Exec=/usr/bin/dictate", content)
                self.assertIn("X-GNOME-Autostart-enabled=true", content)

                set_startup_enabled(False)

                self.assertFalse(startup_enabled())
                self.assertFalse(path.exists())

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

        self.assertIn("[switch]$NoStartup", script)
        self.assertIn('Join-Path $ScriptsDir "dictate-tray.cmd"', script)
        self.assertIn('Join-Path $ScriptsDir "dictate-tray.vbs"', script)
        self.assertIn('"%SCRIPT_DIR%dictate.exe" --type-backend pynput %*', script)
        self.assertIn(
            'Install-StartMenuShortcut -TargetPath (Join-Path $scriptsDir "dictate-tray.vbs")',
            script,
        )
        self.assertIn(
            'Install-StartupShortcut -TargetPath (Join-Path $scriptsDir "dictate-tray.vbs")',
            script,
        )
        self.assertIn("Register-InstalledApp", script)
        self.assertIn(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate", script)

    def test_linux_installer_creates_searchable_launcher_icon_and_autostart(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")

        self.assertIn("--no-startup", script)
        self.assertIn('ICON_PATH="$ICON_DIR/dictate.png"', script)
        self.assertIn('install -m 644 "$SCRIPT_DIR/assets/dictate-controls.png" "$ICON_PATH"', script)
        self.assertIn('cat > "$DESKTOP_DIR/dictate.desktop"', script)
        self.assertIn('cat > "$DESKTOP_DIR/dictate-settings.desktop"', script)
        self.assertIn("Name=Dictate Settings", script)
        self.assertIn('Exec=$HOME/.local/bin/dictate controls', script)
        self.assertIn('cat > "$AUTOSTART_DIR/dictate.desktop"', script)
        self.assertIn("X-GNOME-Autostart-enabled=true", script)
        self.assertIn("Terminal=false", script)

    def test_windows_uninstaller_removes_discovery_entries(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "uninstall-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('Join-Path $programsDir "Dictate.lnk"', script)
        self.assertIn('Join-Path $startupDir "Dictate.lnk"', script)
        self.assertIn(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate", script)

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

    def test_control_panel_exposes_launch_on_startup_setting(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "src" / "dictate" / "windows_control.py"
        ).read_text(encoding="utf-8")

        self.assertIn("Launch on start up", source)
        self.assertIn("startup_enabled()", source)
        self.assertIn("set_startup_enabled(self.launch_on_startup_var.get())", source)

    def test_doctor_windows_fix_repairs_startup_and_installed_apps_entries(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "src" / "dictate" / "doctor.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("Start Dictate automatically at sign-in", source)
        self.assertIn(r"HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Dictate", source)


if __name__ == "__main__":
    unittest.main()
