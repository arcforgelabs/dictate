from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import ui_launcher


class _Broker:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def publish(self, event_type: str, **payload: object) -> None:
        self.events.append((event_type, payload))


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
        binary = Path("/usr/bin/dictate-ui-shell")
        self.assertEqual(ui_launcher.build_launch_command(binary), [str(binary)])


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
        binary = Path("/usr/bin/dictate-ui-shell")
        ok = ui_launcher.open_settings_window(
            find_binary=lambda: binary,
            spawn=lambda cmd: spawned.append(cmd),
            start_server=lambda: started.append(True),
        )
        self.assertTrue(ok)
        self.assertEqual(spawned, [[str(binary)]])
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


class WireDaemonEventsTests(unittest.TestCase):
    def test_chains_existing_callbacks_and_publishes_events(self) -> None:
        class Daemon:
            pass

        daemon = Daemon()
        status_calls: list[str | None] = []
        recording_calls: list[bool] = []
        daemon.status_callback = status_calls.append
        daemon.recording_callback = recording_calls.append
        broker = _Broker()

        ui_launcher._wire_daemon_events(daemon, broker)

        daemon.status_callback("ready")
        daemon.recording_callback(True)
        daemon.history_callback()

        self.assertEqual(status_calls, ["ready"])
        self.assertEqual(recording_calls, [True])
        self.assertEqual(
            broker.events,
            [
                ("status", {"message": "ready"}),
                ("recording", {"active": True}),
                ("history-changed", {}),
            ],
        )


class EnsureServerStartedTests(unittest.TestCase):
    def tearDown(self) -> None:
        ui_launcher._server_handle = None
        ui_launcher._server_broker = None
        ui_launcher._wired_daemon_id = None

    def test_existing_server_can_be_wired_to_daemon_later(self) -> None:
        class Daemon:
            pass

        broker = _Broker()
        handle = object()
        ui_launcher._server_handle = handle
        ui_launcher._server_broker = broker
        daemon = Daemon()
        daemon.status_callback = None
        daemon.recording_callback = None

        self.assertIs(ui_launcher.ensure_server_started(daemon), handle)

        daemon.history_callback()
        self.assertEqual(broker.events, [("history-changed", {})])
        self.assertEqual(ui_launcher._wired_daemon_id, id(daemon))

    def test_new_server_uses_shared_history_store_when_daemon_is_available(self) -> None:
        class Daemon:
            pass

        daemon = Daemon()
        daemon.history_store = object()

        class UiBackend:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs

        broker = _Broker()

        with (
            patch("dictate.ui_server.EventBroker", return_value=broker),
            patch("dictate.ui_server.UiBackend", UiBackend),
            patch("dictate.ui_server.serve", return_value=object()) as serve,
        ):
            ui_launcher.ensure_server_started(daemon)

        backend = serve.call_args.kwargs["backend"]
        self.assertIs(backend.kwargs["history_store"], daemon.history_store)


if __name__ == "__main__":
    unittest.main()
