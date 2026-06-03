from __future__ import annotations

import ast
import ctypes
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
from dictate.windows_tray import (
    NIF_ICON,
    NIF_TIP,
    NIM_MODIFY,
    WM_RECORDING_CHANGED,
    WindowsTrayIcon,
    _NOTIFYICONDATAW,
)


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

    def test_windows_doctor_update_paths_label_hosted_installer_as_developer_bootstrap(self) -> None:
        with patch("dictate.doctor.sys.platform", "win32"):
            updates = _update_paths()

        self.assertTrue(
            any(
                "Developer bootstrap install/update" in item
                and "cdn.jsdelivr.net/npm/@arcforgelabs/dictate" in item
                for item in updates
            )
        )
        self.assertTrue(any("install-windows.ps1" in item for item in updates))
        self.assertTrue(any("install-windows-wizard.ps1" in item for item in updates))
        self.assertTrue(any("update-windows.ps1" in item for item in updates))
        self.assertTrue(any("uninstall-windows.ps1" in item for item in updates))

    def test_doctor_fix_items_include_launcher_repair(self) -> None:
        report = types.SimpleNamespace(
            warnings=[
                "Desktop entry not found: C:\\Users\\sam\\Dictate.lnk",
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
                startup_content = startup_path.read_text(encoding="utf-8")

        self.assertIn("Exec=/usr/bin/dictate", content)
        self.assertIn("Icon=", content)
        self.assertIn("Terminal=false", content)
        self.assertFalse(settings_path.exists())
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
        self.assertIn('$wscript = Join-Path $env:WINDIR "System32\\wscript.exe"', script)
        self.assertIn('Install-StartMenuShortcut -TargetPath $wscript -Arguments $trayArgs', script)
        self.assertIn('Install-StartupShortcut -TargetPath $wscript -Arguments $trayArgs', script)
        self.assertIn('Join-Path $programsDir "Dictate Controls.lnk"', script)
        self.assertIn('Remove-Item -Force -ErrorAction SilentlyContinue -Path $shortcutPath, $legacyShortcutPath', script)
        self.assertIn('Remove-Item -Force $shortcutPath', script)
        self.assertIn('Removed startup shortcut', script)
        self.assertIn("Register-InstalledApp", script)
        self.assertIn(r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate", script)

    def test_windows_installer_prunes_stale_user_install_surfaces(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("function Remove-StaleUserInstallSurface", script)
        self.assertIn("Remove-StaleUserInstallSurface -CurrentInstallLocation $PSScriptRoot", script)
        self.assertIn(r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs", script)
        self.assertIn('Join-Path $startupDir "Dictate.lnk"', script)
        self.assertIn('Join-Path $programsDir "Dictate Controls.lnk"', script)
        self.assertIn(r"AppData\Local\Dictate\source", script)
        self.assertIn("install-windows.ps1", script)
        self.assertIn("Registry::HKEY_USERS", script)
        self.assertIn(r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Dictate", script)
        self.assertIn("Removed stale Dictate Installed Apps entry", script)
        self.assertIn("Removed stale Dictate managed source", script)

    def test_linux_installer_creates_searchable_launcher_icon_and_autostart(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")

        self.assertIn("--no-startup", script)
        self.assertIn('ICON_PATH="$ICON_DIR/dictate-simple.png"', script)
        self.assertIn('install -m 644 "$SCRIPT_DIR/assets/dictate.png" "$ICON_PATH"', script)
        self.assertIn('rm -f "$ICON_DIR/dictate-controls.png" "$ICON_DIR/dictate.png"', script)
        self.assertIn('rm -f "$DESKTOP_DIR/dictate-settings.desktop"', script)
        self.assertIn('cat > "$DESKTOP_DIR/dictate.desktop"', script)
        self.assertIn('cat > "$AUTOSTART_DIR/dictate.desktop"', script)
        self.assertIn("X-GNOME-Autostart-enabled=true", script)
        self.assertIn("Terminal=false", script)

    def test_linux_update_script_migrates_legacy_entries_and_runs_installer(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "update.sh").read_text(encoding="utf-8")

        self.assertIn('rm -f "$DESKTOP_DIR/dictate-settings.desktop"', script)
        self.assertIn('rm -f "$ICON_DIR/dictate-controls.png" "$ICON_DIR/dictate.png"', script)
        self.assertIn('git -C "$SCRIPT_DIR" pull --ff-only', script)
        self.assertIn('AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"', script)
        self.assertIn('AUTOSTART_PATH="$AUTOSTART_DIR/dictate.desktop"', script)
        self.assertIn('args=("$@")', script)
        self.assertIn('args+=("--no-startup")', script)
        self.assertIn('"$SCRIPT_DIR/install.sh" "${args[@]}"', script)

    def test_linux_uninstaller_removes_runtime_and_preserves_data_by_default(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "uninstall.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("--remove-user-data", script)
        self.assertIn('remove_file "$DESKTOP_DIR/dictate.desktop"', script)
        self.assertIn('remove_file "$DESKTOP_DIR/dictate-settings.desktop"', script)
        self.assertIn('remove_file "$AUTOSTART_DIR/dictate.desktop"', script)
        self.assertIn('rm -rf "$INSTALL_DIR/venv" "$INSTALL_DIR/share/icons"', script)
        self.assertIn("Preserved user config/data", script)
        # Hardened cleanup: stop a running source daemon and remove the
        # dictate-ui-server symlink + legacy logs (still preserving user data).
        self.assertIn("stop_source_processes", script)
        self.assertIn("UI_SERVER_BIN_PATH", script)
        self.assertIn('remove_managed_symlink "$UI_SERVER_BIN_PATH"', script)
        self.assertIn('"$INSTALL_DIR/logs"', script)

    def test_linux_installer_warns_on_packaged_conflict(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install.sh").read_text(
            encoding="utf-8"
        )
        # Source install should warn (not silently double up) when the .deb/.rpm
        # package is already installed.
        self.assertIn("dpkg-query -W -f='${Status}' dictate", script)
        self.assertIn("rpm -q dictate", script)
        self.assertIn("sudo apt remove dictate", script)

    def test_windows_update_script_migrates_legacy_shortcut_and_runs_installer(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "update-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('Join-Path $programsDir "Dictate Controls.lnk"', script)
        self.assertIn("git -C $PSScriptRoot pull --ff-only", script)
        self.assertIn("function Stop-DictateProcesses", script)
        self.assertIn("Stop-DictateProcesses", script)
        self.assertIn('Join-Path $PSScriptRoot "install-windows.ps1"', script)
        self.assertIn("[switch]$ForceStartup", script)
        self.assertIn("function Get-StartupShortcutPath", script)
        self.assertIn("-not (Test-Path (Get-StartupShortcutPath))", script)

    def test_windows_uninstaller_removes_discovery_entries(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "uninstall-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('Join-Path $programsDir "Dictate.lnk"', script)
        self.assertIn('Join-Path $programsDir "Dictate Controls.lnk"', script)
        self.assertIn('Join-Path $startupDir "Dictate.lnk"', script)
        self.assertIn("function Stop-DictateProcesses", script)
        self.assertIn("Stop-DictateProcesses", script)
        self.assertIn("[switch]$RemoveUserData", script)
        self.assertIn("User config/data preserved", script)
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

        self.assertIn('$DictateVersion = "2026.6.3"', script)
        self.assertIn("https://github.com/arcforgelabs/dictate/archive/refs/tags/v$DictateVersion.zip", script)
        self.assertIn("Copy-Item -Force -LiteralPath $ArchiveUrl", script)
        self.assertIn("Invoke-WebRequest -UseBasicParsing", script)
        self.assertIn("install-windows.ps1", script)
        self.assertIn("install-windows-wizard.ps1", script)
        self.assertIn("[switch]$Wizard", script)

    def test_windows_wizard_exposes_lifecycle_actions(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "install-windows-wizard.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("Install Dictate", script)
        self.assertIn("Update Dictate", script)
        self.assertIn("Repair launchers and runtime checks (doctor --fix)", script)
        self.assertIn("Uninstall Dictate", script)
        self.assertIn("Launch on startup", script)
        self.assertIn("Create Start Menu entry", script)
        self.assertIn("I understand Dictate has real-world risks and agree to the Arc Forge terms", script)
        self.assertIn("Support and maintenance are best-effort", script)
        self.assertIn("BeginOutputReadLine", script)
        self.assertIn("BeginErrorReadLine", script)
        self.assertIn("function Invoke-DictateUpdate", script)
        self.assertIn("$HostedWindowsUpdateUrl", script)
        self.assertIn("Updating Dictate from hosted source", script)
        self.assertIn('Test-Path (Join-Path $PSScriptRoot ".git")', script)
        self.assertIn("-WorkingDirectory $workingDirectory", script)
        self.assertIn("Add_CheckedChanged({ Sync-ShortcutOptions })", script)
        self.assertIn('$startupCheck.Enabled = $false', script)
        self.assertIn("function Get-StartupShortcutPath", script)
        self.assertIn('$InitialAction -eq "Update"', script)
        self.assertIn("$startupCheck.Checked = Test-Path (Get-StartupShortcutPath)", script)
        self.assertIn("https://arcforge.au/terms", script)
        self.assertIn("https://github.com/arcforgelabs/dictate#readme", script)
        self.assertIn("Please acknowledge the Dictate terms before continuing.", script)
        self.assertIn("update-windows.ps1", script)
        self.assertIn("uninstall-windows.ps1", script)
        self.assertIn("doctor --quick --fix --type-backend pynput", script)
        self.assertIn("-ForceStartup", script)
        self.assertIn("Invoke-DictateUpdate $updateArgs", script)

    def test_release_uploads_lifecycle_scripts(self) -> None:
        workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("install-windows-wizard.ps1", workflow)
        self.assertIn("update-windows.ps1", workflow)
        self.assertIn("uninstall-windows.ps1", workflow)
        self.assertIn("update.sh", workflow)
        self.assertIn("uninstall.sh", workflow)

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

    def test_control_panel_exposes_about_version_and_update_status(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "src" / "dictate" / "windows_control.py"
        ).read_text(encoding="utf-8")

        self.assertIn('ttk.LabelFrame(outer, text="About"', source)
        self.assertIn("Version: {RELEASE_VERSION}", source)
        self.assertIn("Check for Updates", source)
        self.assertIn("Update", source)
        self.assertIn("DOCUMENTATION_URL", source)
        self.assertIn("TERMS_URL", source)
        self.assertIn("check_update_status()", source)
        self.assertIn("subprocess.Popen(command", source)
        self.assertIn("_update_working_directory()", source)
        self.assertIn("self.root.after(500, self.root.destroy)", source)
        self.assertIn("install-windows-wizard.ps1", source)
        self.assertIn("HOSTED_WINDOWS_UPDATE_COMMAND", source)
        self.assertIn("update.ps1 | iex", source)
        self.assertIn('(root / ".git").exists()', source)
        self.assertIn('"Update"', source)

    def test_non_windows_update_command_requires_dictate_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_root = Path(temp_dir) / "bad"
            good_root = Path(temp_dir) / "good"
            bad_root.mkdir()
            good_root.mkdir()
            (bad_root / "update.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (good_root / "update.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (good_root / "pyproject.toml").write_text("[project]\nname='dictate'\n", encoding="utf-8")
            (good_root / "src" / "dictate").mkdir(parents=True)

            fake_tkinter = types.ModuleType("tkinter")
            fake_tkinter.messagebox = types.SimpleNamespace()
            fake_tkinter.ttk = types.SimpleNamespace()

            with (
                patch.dict("sys.modules", {"tkinter": fake_tkinter}),
            ):
                from dictate import windows_control

            with (
                patch.object(windows_control.sys, "platform", "linux"),
                patch.object(windows_control, "_candidate_source_roots", return_value=[bad_root, good_root]),
            ):
                self.assertEqual(
                    windows_control._update_command(),
                    ["bash", str(good_root / "update.sh")],
                )

    def test_hosted_windows_update_stops_dictate_before_replacing_source(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "update.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn('$DictateVersion = "2026.6.3"', script)
        self.assertIn("https://github.com/arcforgelabs/dictate/archive/refs/tags/v$DictateVersion.zip", script)
        self.assertIn("Copy-Item -Force -LiteralPath $ArchiveUrl", script)
        self.assertIn('[System.IO.Directory]::GetCurrentDirectory()', script)
        self.assertIn('$candidateSource = Join-Path $currentDirectory "source"', script)
        self.assertIn('Join-Path $candidateSource "update-windows.ps1"', script)
        self.assertIn('Join-Path $candidateSource "src\\dictate"', script)
        self.assertIn("function Stop-DictateProcesses", script)
        self.assertIn("Stop-DictateProcesses", script)
        self.assertIn("[switch]$ForceStartup", script)
        self.assertIn('if ($ForceStartup) { $updaterArgs += "-ForceStartup" }', script)
        self.assertLess(script.index("Stop-DictateProcesses"), script.index("Remove-Item -Recurse -Force $sourceDir"))

    def test_doctor_windows_fix_repairs_startup_and_installed_apps_entries(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "src" / "dictate" / "doctor.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("Start Dictate automatically at sign-in", source)
        self.assertIn("Dictate Controls.lnk", source)
        self.assertIn(r"HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Dictate", source)

    def test_windows_tray_modifies_icon_when_recording(self) -> None:
        calls: list[tuple[int, int, int, str]] = []

        def notify_icon(message: int, data_pointer) -> int:  # noqa: ANN001
            data = ctypes.cast(data_pointer, ctypes.POINTER(_NOTIFYICONDATAW)).contents
            calls.append((message, data.uFlags, data.hIcon, data.szTip))
            return 1

        tray = WindowsTrayIcon.__new__(WindowsTrayIcon)
        tray.daemon = types.SimpleNamespace(
            active=True,
            current_backend_model=lambda: ("faster-whisper", "turbo"),
        )
        tray._hwnd = 123
        tray._recording = True
        tray._shell32 = types.SimpleNamespace(Shell_NotifyIconW=notify_icon)
        tray._load_icon = lambda recording=False: 222 if recording else 111

        tray._modify_icon()

        self.assertEqual(calls[0][0], NIM_MODIFY)
        self.assertTrue(calls[0][1] & NIF_ICON)
        self.assertTrue(calls[0][1] & NIF_TIP)
        self.assertEqual(calls[0][2], 222)
        self.assertIn("recording", calls[0][3])

    def test_windows_tray_recording_callback_posts_icon_update(self) -> None:
        posted: list[tuple[int, int, int]] = []
        tray = WindowsTrayIcon.__new__(WindowsTrayIcon)
        tray._hwnd = 123
        tray._recording = False
        tray._user32 = types.SimpleNamespace(
            PostMessageW=lambda hwnd, message, wparam, lparam: posted.append(
                (message, wparam, lparam)
            )
        )

        tray._on_recording_changed(True)

        self.assertTrue(tray._recording)
        self.assertEqual(posted, [(WM_RECORDING_CHANGED, 1, 0)])

    def test_windows_tray_recording_message_refreshes_icon(self) -> None:
        modified_states: list[bool] = []
        tray = WindowsTrayIcon.__new__(WindowsTrayIcon)
        tray._recording = False
        tray._modify_icon = lambda: modified_states.append(tray._recording)

        result = tray._window_proc(123, WM_RECORDING_CHANGED, 1, 0)

        self.assertEqual(result, 0)
        self.assertEqual(modified_states, [True])

    def test_ci_includes_windows_user_smoke_gate(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("Windows user install smoke", workflow)
        self.assertIn(r".\scripts\windows-user-smoke.ps1", workflow)
        # The package job gates on the core suites; the UI build/test job was
        # added to that gate alongside tests/windows-user-smoke/npm.
        self.assertRegex(
            workflow,
            r"needs: \[tests, windows-user-smoke, npm(?:, ui)?\]",
        )
        self.assertIn("windows-user-smoke", workflow)

    def test_npm_package_exposes_public_installer_shim(self) -> None:
        package_json = (Path(__file__).resolve().parents[1] / "package.json").read_text(
            encoding="utf-8"
        )

        self.assertIn('"name": "@arcforgelabs/dictate"', package_json)
        self.assertIn('"version": "2026.6.3"', package_json)
        self.assertIn('"dictate-install": "npm/dictate-lifecycle.mjs"', package_json)
        self.assertIn('"access": "public"', package_json)
        self.assertIn('"provenance": true', package_json)


if __name__ == "__main__":
    unittest.main()
