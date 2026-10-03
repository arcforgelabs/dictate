"""Engine startup order (#155).

The desktop window's engine (``--no-tray`` with ``DICTATE_UI_SERVER``) starts
its UI server and writes the ``ui-server.json`` handshake first, then loads the
speech model on a background thread. These tests use a fake backend whose model
load blocks until the test releases it.
"""

from __future__ import annotations

import contextlib
import functools
import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np

# Stub out heavy dependencies so tests work without pynput / sounddevice
# (same stubs as test_daemon_history).
_stub_modules = {
    "pynput": {},
    "pynput.keyboard": {"Listener": MagicMock, "Key": MagicMock()},
    "sounddevice": {"InputStream": MagicMock},
}
for _mod_name, _attrs in _stub_modules.items():
    if _mod_name not in sys.modules:
        _mod = types.ModuleType(_mod_name)
        for _attr_name, _attr_val in _attrs.items():
            setattr(_mod, _attr_name, _attr_val)
        sys.modules[_mod_name] = _mod

from dictate import __main__ as main_module  # noqa: E402
from dictate import ui_launcher, ui_server  # noqa: E402
from dictate.config import Config  # noqa: E402
from dictate.daemon import Daemon  # noqa: E402
from dictate.history import HistoryStore  # noqa: E402
from dictate.note_store import NoteStore  # noqa: E402
from dictate.stt import check_backend_readiness  # noqa: E402
from dictate.stt.base import SttCapabilities  # noqa: E402

MODEL = "parakeet-tdt-0.6b-v2"


class _SlowStt:
    """A backend whose model load blocks until the test sets ``release_load``."""

    backend_name = "parakeet"
    model_name = MODEL
    capabilities = SttCapabilities()

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.release_load = threading.Event()
        self.load_started = threading.Event()
        self.loaded = threading.Event()
        self.fail_with = fail_with
        self.transcribe_calls: list[tuple[int, bool]] = []
        self.released = False

    @property
    def model(self):
        self.load_started.set()
        if not self.release_load.wait(timeout=10):
            raise TimeoutError("the test never released the model load")
        if self.fail_with is not None:
            raise self.fail_with
        self.loaded.set()
        return object()

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del args, kwargs
        self.transcribe_calls.append((len(audio), self.loaded.is_set()))
        return "queued words"

    def release(self) -> None:
        self.released = True


class _Recorder:
    """Records one second of audio per press, with no device."""

    truncated = False

    def __init__(self) -> None:
        self.is_recording = False

    def start(self, on_chunk=None, recording_id=None, **kwargs) -> None:  # noqa: ANN001
        del on_chunk, recording_id, kwargs
        self.is_recording = True

    def stop(self) -> np.ndarray:
        self.is_recording = False
        return np.full(16000, 0.1, dtype=np.float32)


class _Broker:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def publish(self, event_type: str, **data: object) -> None:
        self.events.append((event_type, data))


def _wait_until(predicate, timeout: float = 5.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class DaemonModelLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.statuses: list[str | None] = []
        self.transcripts: list[dict[str, object]] = []
        self.model_events: list[dict[str, object]] = []
        self.output = MagicMock()
        self.output.name = "mock"

    def _daemon(self, stt: _SlowStt) -> Daemon:
        daemon = Daemon(
            stt,
            output=self.output,
            history_store=HistoryStore(self.tmp / "history.json"),
            note_store=NoteStore(self.tmp / "notes"),
            recorder=_Recorder(),
            status_callback=self.statuses.append,
            transcript_callback=self.transcripts.append,
            model_status_callback=self.model_events.append,
            model_loaded=False,
        )
        self.addCleanup(stt.release_load.set)
        self.addCleanup(daemon.shutdown)
        return daemon

    def test_daemon_is_ready_by_default(self) -> None:
        daemon = Daemon(
            _SlowStt(),
            output=self.output,
            history_store=HistoryStore(self.tmp / "history.json"),
            note_store=NoteStore(self.tmp / "notes"),
            recorder=_Recorder(),
        )
        self.assertTrue(daemon.model_ready)
        self.assertEqual(daemon.model_status, {"ready": True, "phase": "ready", "error": None})

    def test_reports_loading_until_the_model_has_loaded(self) -> None:
        stt = _SlowStt()
        daemon = self._daemon(stt)
        self.assertEqual(daemon.model_status, {"ready": False, "phase": "loading", "error": None})

        thread = daemon.start_model_load()
        self.assertTrue(stt.load_started.wait(timeout=5))
        self.assertFalse(daemon.model_ready)

        stt.release_load.set()
        thread.join(timeout=5)

        self.assertTrue(daemon.model_ready)
        self.assertEqual(daemon.model_status, {"ready": True, "phase": "ready", "error": None})
        self.assertEqual(self.model_events[-1], {"ready": True, "phase": "ready", "error": None})
        self.assertEqual(self.model_events[0]["phase"], "loading")

    def test_recording_made_while_loading_is_transcribed_once_ready(self) -> None:
        stt = _SlowStt()
        daemon = self._daemon(stt)
        daemon._ensure_worker_started()
        daemon.start_model_load()
        self.assertTrue(stt.load_started.wait(timeout=5))

        # A shortcut press and release while the model loads.
        self.assertTrue(daemon._start_recording())
        daemon._finalize_recording()
        time.sleep(0.3)

        # Held, not dropped: nothing transcribed or typed yet, nothing failed.
        self.assertEqual(stt.transcribe_calls, [])
        self.output.send.assert_not_called()
        self.assertEqual(daemon._audio_queue.qsize(), 1)

        stt.release_load.set()
        self.assertTrue(_wait_until(lambda: self.output.send.called))

        self.output.send.assert_called_once_with("queued words")
        self.assertEqual(stt.transcribe_calls, [(16000, True)])
        self.assertFalse(any("failed" in (s or "").lower() for s in self.statuses), self.statuses)
        self.assertFalse(any(event.get("stale") for event in self.transcripts), self.transcripts)

    def test_note_recording_made_while_loading_is_saved_once_ready(self) -> None:
        stt = _SlowStt()
        daemon = self._daemon(stt)
        notes: list[dict[str, object]] = []
        daemon.note_callback = notes.append
        daemon._ensure_worker_started()
        daemon.start_model_load()

        self.assertTrue(daemon.start_note_recording())
        self.assertTrue(daemon.stop_note_recording())
        time.sleep(0.2)
        self.assertEqual(notes, [])

        stt.release_load.set()
        self.assertTrue(_wait_until(lambda: bool(notes)))
        self.assertEqual(notes[0]["status"], "ok")
        self.assertEqual(notes[0]["text"], "queued words")
        self.output.send.assert_not_called()

    def test_load_failure_fails_waiting_recordings_and_refuses_new_ones(self) -> None:
        stt = _SlowStt(fail_with=RuntimeError("model.onnx is missing"))
        daemon = self._daemon(stt)
        daemon._ensure_worker_started()
        daemon.start_model_load()

        self.assertTrue(daemon._start_recording())
        daemon._finalize_recording()
        stt.release_load.set()

        self.assertTrue(_wait_until(lambda: daemon.model_status["phase"] == "failed"))
        self.assertEqual(
            daemon.model_status,
            {"ready": False, "phase": "failed", "error": "model.onnx is missing"},
        )
        self.assertTrue(_wait_until(lambda: daemon._audio_queue.qsize() == 0))
        self.assertEqual(self.model_events[-1]["phase"], "failed")
        self.assertIn("Speech model failed to load: model.onnx is missing", self.statuses)
        stale = [event for event in self.transcripts if event.get("stale")]
        self.assertEqual([event.get("reason") for event in stale], ["model-unavailable"])
        self.assertEqual(stt.transcribe_calls, [])
        self.output.send.assert_not_called()

        # A later press is refused with the same message, not silently dropped.
        self.statuses.clear()
        self.assertFalse(daemon._start_recording())
        self.assertEqual(self.statuses, ["Speech model failed to load: model.onnx is missing"])
        self.assertFalse(daemon.recorder.is_recording)

    def test_load_failure_while_the_key_is_held_discards_that_recording(self) -> None:
        stt = _SlowStt(fail_with=RuntimeError("no runtime"))
        daemon = self._daemon(stt)
        daemon._ensure_worker_started()
        daemon.start_model_load()

        self.assertTrue(daemon._start_recording())
        stt.release_load.set()
        self.assertTrue(_wait_until(lambda: daemon.model_status["phase"] == "failed"))

        daemon._finalize_recording()
        time.sleep(0.2)

        self.assertFalse(daemon.recorder.is_recording)
        self.assertIsNone(daemon._active_recording_id)
        self.assertEqual(stt.transcribe_calls, [])
        self.output.send.assert_not_called()
        self.assertIn("Speech model failed to load: no runtime", self.statuses)


class HeadlessStartupOrderTests(unittest.TestCase):
    """``_run_headless`` with a model load: UI server and handshake come first."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.stt = _SlowStt()
        self.addCleanup(self.stt.release_load.set)
        self.stderr = io.StringIO()
        self.daemons: list[Daemon] = []

    def _run_headless(self, run) -> None:  # noqa: ANN001
        def record_daemon(daemon: Daemon) -> None:
            self.daemons.append(daemon)
            self.addCleanup(daemon.shutdown)
            run(daemon)

        model_load = functools.partial(
            main_module._load_stt_model,
            stt_backend="parakeet",
            model_name=MODEL,
            compute_type="int8",
        )
        with (
            patch.dict(os.environ, {"DICTATE_UI_SERVER": "1"}),
            patch(
                "dictate.daemon.HistoryStore",
                side_effect=lambda *a, **k: HistoryStore(self.tmp / "history.json"),
            ),
            patch(
                "dictate.daemon.NoteStore",
                side_effect=lambda *a, **k: NoteStore(self.tmp / "notes"),
            ),
            patch.object(main_module, "_resolve_typing_output_or_exit", return_value=Mock(name="output")),
            patch.object(Daemon, "run", autospec=True, side_effect=record_daemon),
        ):
            main_module._run_headless(
                self.stt,
                type_backend="auto",
                language=None,
                hotwords=None,
                lexicon_mode="native",
                lexicon_replacements=None,
                push_to_talk_combo="ctrl_r",
                stt_backend="parakeet",
                model_load=model_load,
            )

    def test_handshake_is_written_before_the_model_load_completes(self) -> None:
        handshake = self.tmp / "ui-server.json"
        order: list[tuple[str, bool, bool]] = []

        def start_server(daemon: Daemon) -> object:
            order.append(("server", self.stt.load_started.is_set(), daemon.model_ready))
            ui_server.write_runtime_handshake("http://127.0.0.1:1", "token", path=handshake)
            return object()

        def run(daemon: Daemon) -> None:
            order.append(("run", handshake.is_file(), self.stt.loaded.is_set()))

        with (
            contextlib.redirect_stderr(self.stderr),
            patch("dictate.ui_launcher.ensure_server_started", side_effect=start_server),
        ):
            self._run_headless(run)
            daemon = self.daemons[0]

            # The server started before the model load even began, and the
            # daemon was listening with the handshake written while it loaded.
            self.assertEqual(order, [("server", False, False), ("run", True, False)])
            self.assertEqual(daemon.model_status["phase"], "loading")
            self.assertTrue(self.stt.load_started.wait(timeout=5))

            self.stt.release_load.set()
            self.assertTrue(_wait_until(lambda: daemon.model_ready))

        log = self.stderr.getvalue()
        self.assertIn(f"Loading STT backend 'parakeet' model '{MODEL}'", log)
        self.assertIn("Ready.", log)

    def test_load_failure_keeps_the_engine_up_and_reports_the_error(self) -> None:
        self.stt.fail_with = RuntimeError("model.onnx is missing")

        with (
            contextlib.redirect_stderr(self.stderr),
            patch("dictate.ui_launcher.ensure_server_started", return_value=object()),
        ):
            self._run_headless(lambda daemon: None)
            daemon = self.daemons[0]
            self.stt.release_load.set()
            self.assertTrue(_wait_until(lambda: daemon.model_status["phase"] == "failed"))

        self.assertEqual(daemon.model_status["error"], "model.onnx is missing")
        self.assertTrue(self.stt.released)
        self.assertIn("Failed to load backend 'parakeet'", self.stderr.getvalue())

    @unittest.skipIf(
        sys.platform == "win32",
        "Windows CI intermittently interrupts threaded localhost server startup.",
    )
    def test_state_and_events_report_model_readiness_over_http(self) -> None:
        handshake = self.tmp / "ui-server.json"
        real_write = ui_server.write_runtime_handshake
        real_backend = ui_server.UiBackend

        def backend_factory(**kwargs: object) -> ui_server.UiBackend:
            return real_backend(
                config_path=self.tmp / "config.yaml",
                note_store=NoteStore(self.tmp / "notes"),
                prefs_store=ui_server.UiPrefsStore(self.tmp / "ui-prefs.json"),
                startup_enabled=lambda: False,
                **kwargs,
            )

        def reset_launcher() -> None:
            handle = ui_launcher._server_handle
            ui_launcher._server_handle = None
            ui_launcher._server_broker = None
            ui_launcher._wired_daemon_id = None
            if handle is not None:
                handle.shutdown()

        reset_launcher()
        self.addCleanup(reset_launcher)

        def get_state() -> dict[str, object]:
            info = json.loads(handshake.read_text())
            request = urllib.request.Request(info["url"] + "/api/state")
            request.add_header("Authorization", f"Bearer {info['token']}")
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read())

        with (
            contextlib.redirect_stderr(self.stderr),
            patch(
                "dictate.ui_server.write_runtime_handshake",
                side_effect=lambda url, token, **kw: real_write(url, token, path=handshake),
            ),
            patch("dictate.ui_server.UiBackend", side_effect=backend_factory),
        ):
            self._run_headless(lambda daemon: None)
            self.assertTrue(handshake.is_file())
            events = ui_launcher._server_handle.broker.subscribe()

            state = get_state()
            self.assertFalse(state["modelReady"])
            self.assertEqual(state["modelLoad"], {"phase": "loading", "error": None})
            self.assertFalse(self.stt.loaded.is_set())

            self.stt.release_load.set()
            self.assertTrue(_wait_until(lambda: self.daemons[0].model_ready))

            state = get_state()
            self.assertTrue(state["modelReady"])
            self.assertEqual(state["modelLoad"], {"phase": "ready", "error": None})
            published = []
            while not events.empty():
                published.append(events.get_nowait())
            self.assertIn(
                {"type": "model", "ready": True, "phase": "ready", "error": None},
                published,
            )


class MainStartupModeTests(unittest.TestCase):
    def _main(self, env: dict[str, str]) -> dict[str, Mock]:
        lock = Mock()
        lock.acquire.return_value = True
        stt = _SlowStt()
        mocks = {
            "preflight": Mock(),
            "load_stt": Mock(return_value=stt),
            "create_stt": Mock(return_value=stt),
            "run_headless": Mock(),
        }
        with (
            patch.dict(os.environ, env),
            patch("dictate.__main__.ProcessLock", return_value=lock),
            patch.object(main_module, "load_config", return_value=Config()),
            patch.object(main_module, "_ensure_desktop_integration"),
            patch.object(main_module, "_run_preflight_or_exit", mocks["preflight"]),
            patch.object(main_module, "_load_stt_or_exit", mocks["load_stt"]),
            patch.object(main_module, "create_speech_to_text", mocks["create_stt"]),
            patch.object(main_module, "_resolve_language", return_value=None),
            patch.object(main_module, "_resolve_hotwords", return_value=None),
            patch.object(main_module, "_run_headless", mocks["run_headless"]),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            if not env:
                os.environ.pop("DICTATE_UI_SERVER", None)
            self.assertEqual(main_module.main(["--no-tray"]), 0)
        return mocks

    def test_ui_server_engine_loads_the_model_after_starting(self) -> None:
        mocks = self._main({"DICTATE_UI_SERVER": "1"})

        mocks["load_stt"].assert_not_called()
        mocks["create_stt"].assert_called_once()
        self.assertFalse(mocks["preflight"].call_args.kwargs["check_stt_runtime"])
        model_load = mocks["run_headless"].call_args.kwargs["model_load"]
        self.assertIs(model_load.func, main_module._load_stt_model)
        self.assertEqual(model_load.keywords["model_name"], MODEL)

    def test_headless_engine_without_ui_server_loads_the_model_first(self) -> None:
        mocks = self._main({})

        mocks["load_stt"].assert_called_once()
        mocks["create_stt"].assert_not_called()
        self.assertTrue(mocks["preflight"].call_args.kwargs["check_stt_runtime"])
        self.assertIsNone(mocks["run_headless"].call_args.kwargs["model_load"])


class ReadinessReportingTests(unittest.TestCase):
    def test_preflight_can_leave_the_runtime_check_to_the_model_load(self) -> None:
        with patch("dictate.stt.factory.parakeet_available", side_effect=AssertionError("imported")):
            report = check_backend_readiness(backend="parakeet", model=None, check_runtime=False)
        self.assertEqual(report.errors, [])

        with patch("dictate.stt.factory.parakeet_available", return_value=False):
            report = check_backend_readiness(backend="parakeet", model=None)
        self.assertTrue(any("onnx-asr is not importable" in error for error in report.errors))

    def test_state_reports_daemon_model_status(self) -> None:
        class _Daemon:
            model_status = {"ready": False, "phase": "loading", "error": None}

        with tempfile.TemporaryDirectory() as d:
            backend = ui_server.UiBackend(
                config_path=Path(d) / "config.yaml",
                history_store=HistoryStore(Path(d) / "history.json"),
                note_store=NoteStore(Path(d) / "notes"),
                prefs_store=ui_server.UiPrefsStore(Path(d) / "ui-prefs.json"),
                startup_enabled=lambda: False,
                daemon=_Daemon(),
            )
            state = backend.get_state()
            self.assertFalse(state["modelReady"])
            self.assertEqual(state["modelLoad"], {"phase": "loading", "error": None})

            backend.daemon = None
            state = backend.get_state()
            self.assertTrue(state["modelReady"])
            self.assertEqual(state["modelLoad"], {"phase": "ready", "error": None})

    def test_note_start_after_a_failed_load_is_an_error(self) -> None:
        class _Daemon:
            model_status = {"ready": False, "phase": "failed", "error": "no runtime"}
            long_recording_active = False

            def start_note_recording(self) -> bool:
                raise AssertionError("must not start")

        backend = ui_server.UiBackend(
            history_store=HistoryStore(Path(tempfile.gettempdir()) / "unused-history.json"),
            note_store=NoteStore(Path(tempfile.gettempdir()) / "unused-notes"),
            daemon=_Daemon(),
        )
        with self.assertRaises(ui_server.ApiError) as raised:
            backend.start_note_recording()
        self.assertEqual(raised.exception.status, 503)
        self.assertIn("no runtime", raised.exception.message)

    def test_model_status_is_published_to_the_window(self) -> None:
        class _Daemon:
            pass

        daemon = _Daemon()
        seen: list[dict[str, object]] = []
        daemon.model_status_callback = seen.append
        broker = _Broker()

        ui_launcher._wire_daemon_events(daemon, broker)
        daemon.model_status_callback({"ready": False, "phase": "failed", "error": "boom"})

        self.assertEqual(seen, [{"ready": False, "phase": "failed", "error": "boom"}])
        self.assertEqual(
            broker.events,
            [("model", {"ready": False, "phase": "failed", "error": "boom"})],
        )


if __name__ == "__main__":
    unittest.main()
