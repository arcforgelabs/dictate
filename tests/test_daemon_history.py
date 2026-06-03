from __future__ import annotations

import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from dictate.history import HistoryStore

# Stub out heavy dependencies so tests work without faster-whisper / numpy / pynput.
_stub_modules = {
    "faster_whisper": {"WhisperModel": MagicMock},
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

from dictate.engine import TranscriptionResult  # noqa: E402


class _FakeStt:
    backend_name = "fake"
    model_name = "fake-model"

    @property
    def model(self):
        return None

    def transcribe(self, *args, **kwargs):
        return ""

    def release(self):
        pass


class _FakeApiStt(_FakeStt):
    backend_name = "openai"
    api_key = "stored-in-memory"


class _FakeRecorder:
    def __init__(self) -> None:
        self.is_recording = False

    def start(self) -> None:
        self.is_recording = True

    def stop(self) -> np.ndarray:
        self.is_recording = False
        return np.ones(16, dtype=np.float32)


class DaemonHistoryTests(unittest.TestCase):
    def _make_daemon(self, tmp_dir: str):
        from dictate.daemon import Daemon

        store = HistoryStore(path=Path(tmp_dir) / "h.json")
        output = MagicMock()
        output.name = "mock"
        daemon = Daemon(
            _FakeStt(),
            output=output,
            history_store=store,
            status_callback=None,
        )
        return daemon, store, output

    def test_successful_result_appends_to_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, store, _output = self._make_daemon(tmp)
            result = TranscriptionResult(status="ok", duration_s=1.0, text="hello world")
            daemon._handle_result(result)
            entries = store.load()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].text, "hello world")

    def test_successful_result_notifies_history_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, _output = self._make_daemon(tmp)
            calls: list[bool] = []
            daemon.history_callback = lambda: calls.append(True)

            result = TranscriptionResult(status="ok", duration_s=1.0, text="hello world")
            daemon._handle_result(result)

            self.assertEqual(calls, [True])

    def test_non_success_result_does_not_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, store, _output = self._make_daemon(tmp)
            calls: list[bool] = []
            daemon.history_callback = lambda: calls.append(True)
            for status in ("empty", "too_short", "no_speech", "error"):
                result = TranscriptionResult(status=status, duration_s=0.5, text="", error="fail")
                daemon._handle_result(result)
            self.assertEqual(store.load(), [])
            self.assertEqual(calls, [])

    def test_history_saved_even_if_output_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, store, output = self._make_daemon(tmp)
            output.send.side_effect = RuntimeError("output broke")
            result = TranscriptionResult(status="ok", duration_s=1.0, text="saved anyway")
            daemon._handle_result(result)
            entries = store.load()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].text, "saved anyway")

    def test_result_notice_is_surfaced_without_blocking_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, store, output = self._make_daemon(tmp)
            messages: list[str | None] = []
            daemon.status_callback = messages.append
            result = TranscriptionResult(
                status="ok",
                duration_s=1.0,
                text="recovered",
                notice="xAI failed; used CPU fallback",
            )

            daemon._handle_result(result)

            self.assertEqual(messages, ["xAI failed; used CPU fallback"])
            output.send.assert_called_once_with("recovered")
            self.assertEqual(store.load()[0].text, "recovered")

    def test_recording_callback_tracks_capture_start_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            messages: list[bool] = []
            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(
                _FakeStt(),
                output=output,
                history_store=store,
                recording_callback=messages.append,
                recorder=_FakeRecorder(),
            )

            daemon._start_recording()
            daemon._finalize_recording()

            self.assertEqual(messages, [True, False])

    def test_shutdown_disables_hotkey_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, _output = self._make_daemon(tmp)
            backend = MagicMock()
            daemon._hotkey_backend = backend

            daemon.shutdown()

            self.assertFalse(daemon.active)
            self.assertTrue(daemon._stop.is_set())
            self.assertIsNone(daemon._hotkey_backend)
            backend.stop.assert_called_once_with()
            self.assertIsNone(daemon._audio_queue.get_nowait())

    def test_shutdown_does_not_block_with_pending_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, _output = self._make_daemon(tmp)
            daemon._audio_queue.put_nowait(np.ones(16, dtype=np.float32))

            shutdown_thread = threading.Thread(target=daemon.shutdown)
            shutdown_thread.start()
            shutdown_thread.join(timeout=0.5)
            if shutdown_thread.is_alive():
                try:
                    daemon._audio_queue.get_nowait()
                except Exception:  # noqa: BLE001
                    pass
                shutdown_thread.join(timeout=0.5)

            self.assertFalse(shutdown_thread.is_alive())
            self.assertIsNone(daemon._audio_queue.get_nowait())

    def test_queue_latest_audio_preserves_pending_recordings_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, _output = self._make_daemon(tmp)
            first = np.ones(4, dtype=np.float32)
            second = np.full(4, 2, dtype=np.float32)

            daemon._queue_latest_audio(first)
            daemon._queue_latest_audio(second)

            np.testing.assert_array_equal(daemon._audio_queue.get_nowait(), first)
            np.testing.assert_array_equal(daemon._audio_queue.get_nowait(), second)

    def test_clear_active_api_key_removes_key_from_loaded_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _FakeApiStt()
            daemon = Daemon(stt, output=output, history_store=store)

            daemon.clear_active_api_key("openai")

            self.assertEqual(stt.api_key, "")


if __name__ == "__main__":
    unittest.main()
