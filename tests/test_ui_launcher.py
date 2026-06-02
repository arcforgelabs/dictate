from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import ui_launcher


class FindShellBinaryTests(unittest.TestCase):
    def test_returns_first_existing_candidate(self) -> None:
        a, b = Path("/opt/dictate-ui-shell"), Path("/usr/bin/dictate-ui-shell")
        found = ui_launcher.find_shell_binary(exists=lambda p: p == b, candidates=[a, b])
        self.assertEqual(found, b)

    def test_returns_none_when_absent(self) -> None:
        self.assertIsNone(
            ui_launcher.find_shell_binary(exists=lambda p: False, candidates=[Path("/x")])
        )

    def test_env_override_is_first_candidate(self) -> None:
        with patch.dict(os.environ, {"DICTATE_UI_SHELL": "/custom/shell"}):
            self.assertEqual(ui_launcher.shell_binary_candidates()[0], Path("/custom/shell"))

    def test_build_launch_command(self) -> None:
        self.assertEqual(
            ui_launcher.build_launch_command(Path("/usr/bin/dictate-ui-shell")),
            ["/usr/bin/dictate-ui-shell"],
        )


class OpenSettingsWindowTests(unittest.TestCase):
    def test_returns_false_without_binary(self) -> None:
        spawned: list[list[str]] = []
        ok = ui_launcher.open_settings_window(
            find_binary=lambda: None,
            spawn=lambda cmd: spawned.append(cmd),
            start_server=lambda: None,
        )
        self.assertFalse(ok)
        self.assertEqual(spawned, [])

    def test_spawns_and_starts_server_when_present(self) -> None:
        spawned: list[list[str]] = []
        started: list[bool] = []
        ok = ui_launcher.open_settings_window(
            find_binary=lambda: Path("/usr/bin/dictate-ui-shell"),
            spawn=lambda cmd: spawned.append(cmd),
            start_server=lambda: started.append(True),
        )
        self.assertTrue(ok)
        self.assertEqual(spawned, [["/usr/bin/dictate-ui-shell"]])
        self.assertEqual(started, [True])

    def test_server_failure_does_not_block_launch(self) -> None:
        spawned: list[list[str]] = []

        def boom() -> None:
            raise RuntimeError("server down")

        ok = ui_launcher.open_settings_window(
            find_binary=lambda: Path("/bin/dictate-ui-shell"),
            spawn=lambda cmd: spawned.append(cmd),
            start_server=boom,
        )
        self.assertTrue(ok)
        self.assertEqual(len(spawned), 1)

    def test_spawn_failure_returns_false(self) -> None:
        def boom(cmd: list[str]) -> None:
            raise OSError("no exec")

        ok = ui_launcher.open_settings_window(
            find_binary=lambda: Path("/bin/dictate-ui-shell"),
            spawn=boom,
            start_server=lambda: None,
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
