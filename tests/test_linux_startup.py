from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import startup
from dictate.doctor import _check_runtime_paths, _desktop_exec_target_missing, _fix_items
from dictate.preflight import PreflightReport


def setUpModule() -> None:
    # These exercise Linux desktop-entry / launcher / autostart behavior
    # (.desktop files, ~/.local/bin targets). The functions under test
    # short-circuit on Windows, so the assertions are Linux-only.
    if not sys.platform.startswith("linux"):
        raise unittest.SkipTest("Linux desktop startup behavior")


def _which_map(mapping: dict[str, str | None]):
    return lambda name: mapping.get(name)


class LinuxExecPathTests(unittest.TestCase):
    def test_frozen_app_targets_the_shell(self) -> None:
        with patch.object(startup.sys, "frozen", True, create=True), patch.object(
            startup.shutil, "which", _which_map({"dictate-ui-shell": "/usr/bin/dictate-ui-shell"})
        ):
            self.assertEqual(startup._linux_exec_path(), "/usr/bin/dictate-ui-shell")

    def test_source_install_prefers_console_script(self) -> None:
        with patch.object(startup.sys, "frozen", False, create=True), patch.object(
            startup.shutil,
            "which",
            _which_map(
                {"dictate": "/home/u/.local/bin/dictate", "dictate-ui-shell": "/usr/bin/dictate-ui-shell"}
            ),
        ):
            self.assertEqual(startup._linux_exec_path(), "/home/u/.local/bin/dictate")


class EnsureDesktopIntegrationOnceTests(unittest.TestCase):
    def _run_frozen(self, tmp: Path) -> None:
        with patch.object(startup.sys, "frozen", True, create=True), patch.object(
            startup.sys, "platform", "linux"
        ), patch.object(startup, "user_data_dir", return_value=tmp / "data"), patch.dict(
            "os.environ",
            {"XDG_CONFIG_HOME": str(tmp / "config"), "XDG_DATA_HOME": str(tmp / "share")},
        ), patch.object(
            startup.shutil, "which", _which_map({"dictate-ui-shell": "/usr/bin/dictate-ui-shell"})
        ):
            startup.ensure_desktop_integration_once()

    def test_first_run_creates_entries_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            self._run_frozen(tmp)
            autostart = tmp / "config" / "autostart" / "dictate.desktop"
            app = tmp / "share" / "applications" / "dictate.desktop"
            marker = tmp / "data" / ".desktop-integrated"
            self.assertTrue(autostart.exists())
            self.assertTrue(app.exists())
            self.assertTrue(marker.exists())
            self.assertIn("Exec=/usr/bin/dictate-ui-shell", autostart.read_text())

    def test_existing_marker_is_not_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "data").mkdir(parents=True)
            (tmp / "data" / ".desktop-integrated").write_text("1\n")
            self._run_frozen(tmp)
            # No autostart entry recreated because the marker already existed.
            self.assertFalse((tmp / "config" / "autostart" / "dictate.desktop").exists())

    def test_noop_when_not_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            with patch.object(startup.sys, "frozen", False, create=True), patch.object(
                startup, "user_data_dir", return_value=tmp / "data"
            ), patch.dict("os.environ", {"XDG_CONFIG_HOME": str(tmp / "config")}):
                startup.ensure_desktop_integration_once()
            self.assertFalse((tmp / "data" / ".desktop-integrated").exists())


class DoctorStaleLauncherTests(unittest.TestCase):
    def test_packaged_desktop_entry_satisfies_runtime_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_entry = root / "missing" / "dictate.desktop"
            package_entry = root / "usr" / "share" / "applications" / "Dictate.desktop"
            startup_entry = root / "config" / "autostart" / "dictate.desktop"
            package_entry.parent.mkdir(parents=True)
            startup_entry.parent.mkdir(parents=True)
            package_entry.write_text("[Desktop Entry]\nExec=dictate-ui-shell\n", encoding="utf-8")
            startup_entry.write_text("[Desktop Entry]\nExec=dictate-ui-shell\n", encoding="utf-8")
            report = PreflightReport()

            with (
                patch("dictate.doctor._desktop_entry_path", return_value=source_entry),
                patch("dictate.doctor._desktop_entry_paths", return_value=[source_entry, package_entry]),
                patch("dictate.doctor.startup_entry_path", return_value=startup_entry),
                patch("dictate.doctor.shutil.which", _which_map({"dictate-ui-shell": "/usr/bin/dictate-ui-shell"})),
            ):
                _check_runtime_paths(report)

        self.assertTrue(any(f"Desktop entry: {package_entry}" == note for note in report.notes))
        self.assertFalse(any("Desktop entry not found" in warning for warning in report.warnings))

    def test_detects_missing_exec_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            entry = Path(raw) / "dictate.desktop"
            entry.write_text("[Desktop Entry]\nExec=/home/x/.local/bin/dictate\n")
            self.assertEqual(
                _desktop_exec_target_missing(entry), "/home/x/.local/bin/dictate"
            )

    def test_present_target_on_path_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            entry = Path(raw) / "dictate.desktop"
            entry.write_text("[Desktop Entry]\nExec=dictate-ui-shell\n")
            # Resolve to a path that actually exists in any environment (a real
            # file in the temp dir), since _desktop_exec_target_missing verifies
            # the resolved binary exists on disk. Hardcoding /usr/bin/... passed
            # only on machines with the packaged app already installed.
            resolved = Path(raw) / "dictate-ui-shell"
            resolved.write_text("")
            with patch("dictate.doctor.shutil.which", _which_map({"dictate-ui-shell": str(resolved)})):
                self.assertIsNone(_desktop_exec_target_missing(entry))

    def test_fix_item_offered_for_stale_target(self) -> None:
        report = PreflightReport()
        report.warnings.append(
            "Startup entry points to a missing target (/home/x/.local/bin/dictate); it will not launch."
        )
        items = _fix_items(report)
        self.assertTrue(any("repair launcher/startup entries" in i for i in items))


if __name__ == "__main__":
    unittest.main()
