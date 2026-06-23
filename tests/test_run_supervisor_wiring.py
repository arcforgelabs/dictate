"""Regression tests: _run_headless and _run_tray construct a ProviderSupervisor
and pass it to Daemon at startup.

All probes are mocked — this suite never hits the network.
"""

from __future__ import annotations

import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

from dictate import __main__ as main_module
from dictate.stt import SttCapabilities


def tearDownModule() -> None:
    """Cancel probe Timers left alive by supervisors so no daemon thread
    survives to interpreter shutdown (a Windows STATUS_DLL_INIT_FAILED hazard)."""
    for t in threading.enumerate():
        if isinstance(t, threading.Timer) and t.is_alive():
            t.cancel()


# ---------------------------------------------------------------------------
# Minimal fakes
# ---------------------------------------------------------------------------


class _FakeStt:
    backend_name = "xai"
    model_name = "grok-2-audio"
    capabilities = SttCapabilities(supports_language_hint=True)


class _FakeSupervisor:
    """Minimal stand-in that tracks construction and shutdown."""

    instances: list["_FakeSupervisor"] = []

    def __init__(self, preferred: str, *, probe_fn, **kw) -> None:
        self.preferred = preferred
        self.probe_fn = probe_fn
        self.shut_down = False
        _FakeSupervisor.instances.append(self)

    def probe_now(self) -> None:
        pass

    def shutdown(self) -> None:
        self.shut_down = True


class _FakeDaemon:
    """Stand-in for Daemon — records keyword args and returns immediately from run()."""

    def __init__(self, stt, **kwargs) -> None:
        self.stt = stt
        self.kwargs = kwargs
        self.supervisor = kwargs.get("supervisor")

    def run(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_resolve_output(type_backend: str):  # noqa: ANN202
    return object()


# ---------------------------------------------------------------------------
# _run_headless
# ---------------------------------------------------------------------------


class RunHeadlessSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeSupervisor.instances.clear()

    def test_creates_supervisor_with_correct_backend(self) -> None:
        """_run_headless must construct a ProviderSupervisor(preferred='xai')."""
        with (
            patch("dictate.daemon.Daemon", _FakeDaemon),
            patch(
                "dictate.provider_supervisor.ProviderSupervisor",
                _FakeSupervisor,
            ),
            patch(
                "dictate.provider_supervisor.make_remote_probe",
                return_value=lambda: False,
            ),
            patch.object(
                main_module,
                "_resolve_typing_output_or_exit",
                side_effect=_fake_resolve_output,
            ),
            patch.object(main_module, "_maybe_start_ui_server"),
        ):
            main_module._run_headless(
                _FakeStt(),
                type_backend="xdotool",
                language=None,
                hotwords=None,
                lexicon_mode=None,
                lexicon_replacements=None,
                push_to_talk_combo="ctrl+d",
                stt_backend="xai",
            )

        self.assertEqual(len(_FakeSupervisor.instances), 1)
        self.assertEqual(_FakeSupervisor.instances[0].preferred, "xai")

    def test_supervisor_passed_to_daemon(self) -> None:
        """The constructed supervisor must be forwarded to Daemon(supervisor=...)."""
        captured: list[object] = []

        class CaptureDaemon(_FakeDaemon):
            def __init__(self, stt, **kwargs) -> None:
                super().__init__(stt, **kwargs)
                captured.append(kwargs.get("supervisor"))

        with (
            patch("dictate.daemon.Daemon", CaptureDaemon),
            patch(
                "dictate.provider_supervisor.ProviderSupervisor",
                _FakeSupervisor,
            ),
            patch(
                "dictate.provider_supervisor.make_remote_probe",
                return_value=lambda: False,
            ),
            patch.object(
                main_module,
                "_resolve_typing_output_or_exit",
                side_effect=_fake_resolve_output,
            ),
            patch.object(main_module, "_maybe_start_ui_server"),
        ):
            main_module._run_headless(
                _FakeStt(),
                type_backend="xdotool",
                language=None,
                hotwords=None,
                lexicon_mode=None,
                lexicon_replacements=None,
                push_to_talk_combo="ctrl+d",
                stt_backend="xai",
            )

        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0], _FakeSupervisor)

    def test_supervisor_shutdown_on_exit(self) -> None:
        """supervisor.shutdown() must be called when daemon.run() returns."""
        with (
            patch("dictate.daemon.Daemon", _FakeDaemon),
            patch(
                "dictate.provider_supervisor.ProviderSupervisor",
                _FakeSupervisor,
            ),
            patch(
                "dictate.provider_supervisor.make_remote_probe",
                return_value=lambda: False,
            ),
            patch.object(
                main_module,
                "_resolve_typing_output_or_exit",
                side_effect=_fake_resolve_output,
            ),
            patch.object(main_module, "_maybe_start_ui_server"),
        ):
            main_module._run_headless(
                _FakeStt(),
                type_backend="xdotool",
                language=None,
                hotwords=None,
                lexicon_mode=None,
                lexicon_replacements=None,
                push_to_talk_combo="ctrl+d",
                stt_backend="xai",
            )

        self.assertTrue(_FakeSupervisor.instances[0].shut_down)

    def test_make_remote_probe_called_for_backend(self) -> None:
        """make_remote_probe must be called with the stt_backend string."""
        probe_calls: list[str] = []

        def _fake_make_probe(backend: str):
            probe_calls.append(backend)
            return lambda: False

        with (
            patch("dictate.daemon.Daemon", _FakeDaemon),
            patch(
                "dictate.provider_supervisor.ProviderSupervisor",
                _FakeSupervisor,
            ),
            patch(
                "dictate.provider_supervisor.make_remote_probe",
                side_effect=_fake_make_probe,
            ),
            patch.object(
                main_module,
                "_resolve_typing_output_or_exit",
                side_effect=_fake_resolve_output,
            ),
            patch.object(main_module, "_maybe_start_ui_server"),
        ):
            main_module._run_headless(
                _FakeStt(),
                type_backend="xdotool",
                language=None,
                hotwords=None,
                lexicon_mode=None,
                lexicon_replacements=None,
                push_to_talk_combo="ctrl+d",
                stt_backend="gemini",
            )

        self.assertEqual(probe_calls, ["gemini"])


# ---------------------------------------------------------------------------
# _run_tray
# ---------------------------------------------------------------------------


class RunTraySupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeSupervisor.instances.clear()

    def _run_tray_headless(self, stt_backend: str = "xai") -> None:
        """Run _run_tray with the Windows path so we avoid GTK/AppIndicator imports."""

        class _FakeWindowsTray:
            def __init__(self, daemon) -> None:
                self.daemon = daemon

            def run(self) -> None:
                pass

        with (
            patch("dictate.daemon.Daemon", _FakeDaemon),
            patch(
                "dictate.provider_supervisor.ProviderSupervisor",
                _FakeSupervisor,
            ),
            patch(
                "dictate.provider_supervisor.make_remote_probe",
                return_value=lambda: False,
            ),
            patch.object(
                main_module,
                "_resolve_typing_output_or_exit",
                side_effect=_fake_resolve_output,
            ),
            patch("sys.platform", "win32"),
            patch("dictate.windows_tray.WindowsTrayIcon", _FakeWindowsTray),
        ):
            main_module._run_tray(
                _FakeStt(),
                type_backend="xdotool",
                language=None,
                hotwords=None,
                lexicon_mode=None,
                lexicon_replacements=None,
                push_to_talk_combo="ctrl+d",
                stt_backend=stt_backend,
            )

    def test_creates_supervisor_with_correct_backend(self) -> None:
        self._run_tray_headless("xai")
        self.assertEqual(len(_FakeSupervisor.instances), 1)
        self.assertEqual(_FakeSupervisor.instances[0].preferred, "xai")

    def test_supervisor_passed_to_daemon(self) -> None:
        captured: list[object] = []

        class CaptureDaemon(_FakeDaemon):
            def __init__(self, stt, **kwargs) -> None:
                super().__init__(stt, **kwargs)
                captured.append(kwargs.get("supervisor"))

        class _FakeWindowsTray:
            def __init__(self, daemon) -> None:
                pass

            def run(self) -> None:
                pass

        with (
            patch("dictate.daemon.Daemon", CaptureDaemon),
            patch(
                "dictate.provider_supervisor.ProviderSupervisor",
                _FakeSupervisor,
            ),
            patch(
                "dictate.provider_supervisor.make_remote_probe",
                return_value=lambda: False,
            ),
            patch.object(
                main_module,
                "_resolve_typing_output_or_exit",
                side_effect=_fake_resolve_output,
            ),
            patch("sys.platform", "win32"),
            patch("dictate.windows_tray.WindowsTrayIcon", _FakeWindowsTray),
        ):
            main_module._run_tray(
                _FakeStt(),
                type_backend="xdotool",
                language=None,
                hotwords=None,
                lexicon_mode=None,
                lexicon_replacements=None,
                push_to_talk_combo="ctrl+d",
                stt_backend="xai",
            )

        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0], _FakeSupervisor)

    def test_supervisor_shutdown_on_exit(self) -> None:
        self._run_tray_headless()
        self.assertTrue(_FakeSupervisor.instances[0].shut_down)


# ---------------------------------------------------------------------------
# ensure_server_started with a pre-existing daemon.supervisor
# ---------------------------------------------------------------------------


class _Broker:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def publish(self, event_type: str, **payload: object) -> None:
        self.events.append((event_type, payload))


def _reset_launcher() -> None:
    from dictate import ui_launcher

    if ui_launcher._supervisor is not None:
        try:
            ui_launcher._supervisor.shutdown()
        except Exception:  # noqa: BLE001
            pass
    ui_launcher._server_handle = None
    ui_launcher._server_broker = None
    ui_launcher._wired_daemon_id = None
    ui_launcher._supervisor = None


class EnsureServerStartedReusesSupervisorTests(unittest.TestCase):
    """ensure_server_started must call connect_supervisor with the daemon's existing supervisor."""

    def tearDown(self) -> None:
        _reset_launcher()

    def _make_daemon(self) -> object:
        class FakeEngine:
            health_sink = None

            class _stt:
                pass

        engine = FakeEngine()
        engine.stt = type("Stt", (), {"backend_name": "xai"})()

        class FakeDaemon:
            pass

        d = FakeDaemon()
        d.engine = engine
        d.history_store = None
        d.status_callback = None
        d.recording_callback = None
        d.note_recording_callback = None
        d.transcript_callback = None
        d.note_callback = None
        d.history_callback = None
        return d

    def test_connect_supervisor_called_with_existing_supervisor(self) -> None:
        """When daemon.supervisor is already set, connect_supervisor is called with it."""
        from dictate import ui_launcher

        connect_calls: list[object] = []

        class FakeBackend:
            def __init__(self, **kwargs: object) -> None:
                pass

            def connect_supervisor(self, sup: object) -> None:
                connect_calls.append(sup)

        class ExistingSupervisor:
            pass

        broker = _Broker()
        daemon = self._make_daemon()
        existing_sup = ExistingSupervisor()
        daemon.supervisor = existing_sup  # type: ignore[attr-defined]

        with (
            patch("dictate.ui_server.EventBroker", return_value=broker),
            patch("dictate.ui_server.UiBackend", FakeBackend),
            patch("dictate.ui_server.serve", return_value=object()),
        ):
            ui_launcher.ensure_server_started(daemon)

        self.assertEqual(len(connect_calls), 1)
        self.assertIs(connect_calls[0], existing_sup)

    def test_existing_supervisor_becomes_module_level_supervisor(self) -> None:
        """_supervisor module variable must be updated to the daemon's existing supervisor."""
        from dictate import ui_launcher

        class FakeBackend:
            def __init__(self, **kwargs: object) -> None:
                pass

            def connect_supervisor(self, sup: object) -> None:
                pass

        class ExistingSupervisor:
            pass

        broker = _Broker()
        daemon = self._make_daemon()
        existing_sup = ExistingSupervisor()
        daemon.supervisor = existing_sup  # type: ignore[attr-defined]

        with (
            patch("dictate.ui_server.EventBroker", return_value=broker),
            patch("dictate.ui_server.UiBackend", FakeBackend),
            patch("dictate.ui_server.serve", return_value=object()),
        ):
            ui_launcher.ensure_server_started(daemon)

        self.assertIs(ui_launcher._supervisor, existing_sup)

    def test_no_new_supervisor_created_when_existing(self) -> None:
        """_make_probe_fn must NOT be called when daemon already has a supervisor."""
        from dictate import ui_launcher

        class FakeBackend:
            def __init__(self, **kwargs: object) -> None:
                pass

            def connect_supervisor(self, sup: object) -> None:
                pass

        class ExistingSupervisor:
            pass

        broker = _Broker()
        daemon = self._make_daemon()
        daemon.supervisor = ExistingSupervisor()  # type: ignore[attr-defined]

        with (
            patch("dictate.ui_server.EventBroker", return_value=broker),
            patch("dictate.ui_server.UiBackend", FakeBackend),
            patch("dictate.ui_server.serve", return_value=object()),
            patch("dictate.ui_launcher._make_probe_fn") as mock_probe_fn,
        ):
            ui_launcher.ensure_server_started(daemon)

        mock_probe_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
