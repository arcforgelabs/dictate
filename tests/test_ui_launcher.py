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

    def test_user_install_precedes_path_binary(self) -> None:
        with patch.dict(os.environ, {"PATH": "/usr/bin"}):
            candidates = ui_launcher.shell_binary_candidates()
        suffix = ".exe" if ui_launcher.is_windows() else ""
        self.assertEqual(
            candidates[0],
            Path.home() / ".local" / "bin" / f"dictate-ui-shell{suffix}",
        )

    def test_windows_managed_source_dev_build_is_a_candidate(self) -> None:
        with (
            patch("dictate.ui_launcher.is_windows", return_value=True),
            patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\sam\AppData\Local"}, clear=True),
        ):
            candidates = ui_launcher.shell_binary_candidates()

        self.assertIn(
            Path(r"C:\Users\sam\AppData\Local")
            / "Dictate"
            / "source"
            / "ui-shell"
            / "src-tauri"
            / "target"
            / "release"
            / "dictate-ui-shell.exe",
            candidates,
        )

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
        history_calls: list[bool] = []
        transcript_calls: list[dict[str, object]] = []
        daemon.status_callback = status_calls.append
        daemon.recording_callback = recording_calls.append
        daemon.history_callback = lambda: history_calls.append(True)
        daemon.transcript_callback = transcript_calls.append
        broker = _Broker()

        ui_launcher._wire_daemon_events(daemon, broker)

        daemon.status_callback("ready")
        daemon.recording_callback(True)
        daemon.transcript_callback({"phase": "partial", "text": "hello", "stale": False})
        daemon.history_callback()

        self.assertEqual(status_calls, ["ready"])
        self.assertEqual(recording_calls, [True])
        self.assertEqual(history_calls, [True])
        self.assertEqual(transcript_calls, [{"phase": "partial", "text": "hello", "stale": False}])
        self.assertEqual(
            broker.events,
            [
                ("status", {"message": "ready"}),
                ("recording", {"active": True}),
                ("transcript", {"phase": "partial", "text": "hello", "stale": False}),
                ("history-changed", {}),
            ],
        )


def _reset_launcher_globals() -> None:
    """Reset all process-wide singletons in ui_launcher between tests."""
    if ui_launcher._supervisor is not None:
        try:
            ui_launcher._supervisor.shutdown()
        except Exception:  # noqa: BLE001
            pass
    ui_launcher._server_handle = None
    ui_launcher._server_broker = None
    ui_launcher._wired_daemon_id = None
    ui_launcher._supervisor = None


class EnsureServerStartedTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_launcher_globals()

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


class EnsureServerStartedSupervisorTests(unittest.TestCase):
    """Regression tests: live startup must wire a ProviderSupervisor, not stay inert."""

    def tearDown(self) -> None:
        _reset_launcher_globals()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_daemon(backend_name: str = "xai") -> object:
        class FakeEngine:
            health_sink = None

            class _stt:
                pass

        engine = FakeEngine()
        engine.stt = type("Stt", (), {"backend_name": backend_name})()

        class FakeDaemon:
            pass

        d = FakeDaemon()
        d.engine = engine
        d.supervisor = None
        d.history_store = None
        # Attributes that _wire_daemon_events reads via getattr
        d.status_callback = None
        d.recording_callback = None
        d.note_recording_callback = None
        d.transcript_callback = None
        d.note_callback = None
        d.history_callback = None
        return d

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_supervisor_created_and_connect_supervisor_called_on_new_server(self) -> None:
        """ensure_server_started must create a ProviderSupervisor and call connect_supervisor."""
        connect_calls: list[object] = []

        class FakeBackend:
            def __init__(self, **kwargs: object) -> None:
                pass

            def connect_supervisor(self, sup: object) -> None:
                connect_calls.append(sup)

        broker = _Broker()
        daemon = self._make_daemon("xai")

        with (
            patch("dictate.ui_server.EventBroker", return_value=broker),
            patch("dictate.ui_server.UiBackend", FakeBackend),
            patch("dictate.ui_server.serve", return_value=object()),
            patch("dictate.ui_launcher._make_probe_fn", return_value=lambda: False) as mock_probe,
        ):
            ui_launcher.ensure_server_started(daemon)

        # Probe factory was invoked for the configured backend
        mock_probe.assert_called_once_with("xai")
        # Module-level supervisor was created
        self.assertIsNotNone(ui_launcher._supervisor)
        # Daemon has the supervisor attached
        self.assertIs(daemon.supervisor, ui_launcher._supervisor)
        # connect_supervisor was called exactly once with the new supervisor
        self.assertEqual(len(connect_calls), 1)
        self.assertIs(connect_calls[0], ui_launcher._supervisor)

    def test_supervisor_probe_fn_is_xai_for_xai_backend(self) -> None:
        """_make_probe_fn('xai') returns a callable (not the no-op lambda)."""
        with patch("dictate.stt.xai_backend.make_xai_probe", return_value=lambda: True) as m:
            probe = ui_launcher._make_probe_fn("xai")
        m.assert_called_once()
        self.assertTrue(callable(probe))

    def test_supervisor_probe_fn_is_noop_for_private_backend(self) -> None:
        """_make_probe_fn('faster-whisper') returns a no-op probe."""
        probe = ui_launcher._make_probe_fn("faster-whisper")
        self.assertFalse(probe())

    def test_engine_health_sink_routes_to_supervisor(self) -> None:
        """After wiring, engine.health_sink failure calls supervisor.report_failure."""
        connect_calls: list[object] = []

        class FakeBackend:
            def __init__(self, **kwargs: object) -> None:
                pass

            def connect_supervisor(self, sup: object) -> None:
                connect_calls.append(sup)

        broker = _Broker()
        daemon = self._make_daemon("xai")

        with (
            patch("dictate.ui_server.EventBroker", return_value=broker),
            patch("dictate.ui_server.UiBackend", FakeBackend),
            patch("dictate.ui_server.serve", return_value=object()),
            patch("dictate.ui_launcher._make_probe_fn", return_value=lambda: False),
        ):
            ui_launcher.ensure_server_started(daemon)

        supervisor = ui_launcher._supervisor
        self.assertIsNotNone(supervisor)
        self.assertFalse(supervisor.is_degraded())

        # Simulate an engine health_sink call (remote failure)
        daemon.engine.health_sink(False, "unreachable")
        self.assertTrue(supervisor.is_degraded())

        # Simulate recovery
        daemon.engine.health_sink(True, None)
        self.assertFalse(supervisor.is_degraded())


if __name__ == "__main__":
    unittest.main()
