"""The clip queued on key release starts decoding without waiting for a poll (#156)."""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

# Stub out heavy dependencies so the daemon imports without pynput / sounddevice.
for _mod_name, _attrs in {
    "pynput": {},
    "pynput.keyboard": {"Listener": MagicMock, "Key": MagicMock()},
    "sounddevice": {"InputStream": MagicMock},
}.items():
    if _mod_name not in sys.modules:
        _mod = types.ModuleType(_mod_name)
        for _attr_name, _attr_val in _attrs.items():
            setattr(_mod, _attr_name, _attr_val)
        sys.modules[_mod_name] = _mod

from dictate.audio import AudioChunk  # noqa: E402
from dictate.history import HistoryStore  # noqa: E402
from dictate.note_store import NoteStore  # noqa: E402
from dictate.stt.base import SttCapabilities  # noqa: E402


class _Stt:
    backend_name = "fake"
    model_name = "fake-model"
    capabilities = SttCapabilities()

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del audio, args, kwargs
        return "hello there"

    def release(self) -> None:
        pass


class _Recorder:
    def __init__(self) -> None:
        self.is_recording = False
        self.truncated = False

    def start(self, on_chunk=None, recording_id=None, **kwargs) -> None:  # noqa: ANN001
        del on_chunk, recording_id, kwargs
        self.is_recording = True

    def stop(self) -> np.ndarray:
        self.is_recording = False
        return np.full(16000, 0.1, dtype=np.float32)


class WorkerWakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.output = MagicMock()
        self.output.name = "mock"

    def _daemon(self):  # noqa: ANN202
        from dictate.daemon import Daemon

        return Daemon(
            _Stt(),
            output=self.output,
            history_store=HistoryStore(path=self.root / "h.json"),
            note_store=NoteStore(self.root / "notes"),
            recorder=_Recorder(),
        )

    def test_queueing_a_final_chunk_wakes_the_worker(self) -> None:
        daemon = self._daemon()
        with contextlib.redirect_stderr(io.StringIO()):
            daemon._start_recording()
        daemon._work_ready.clear()

        daemon._queue_final_chunk(
            AudioChunk(samples=np.ones(4, dtype=np.float32), final=True, recording_id=1)
        )

        self.assertTrue(daemon._work_ready.is_set())

    def test_queueing_a_partial_chunk_wakes_the_worker(self) -> None:
        daemon = self._daemon()
        with contextlib.redirect_stderr(io.StringIO()):
            daemon._start_recording()
        daemon._work_ready.clear()

        daemon._queue_partial_audio(
            AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, recording_id=1)
        )

        self.assertTrue(daemon._work_ready.is_set())

    def test_idle_worker_starts_on_release_not_on_the_next_poll(self) -> None:
        sent = threading.Event()
        self.output.send.side_effect = lambda text: sent.set()
        daemon = self._daemon()
        log = io.StringIO()
        # A poll this long fails the test if the worker only wakes on it.
        with patch("dictate.daemon.WORKER_IDLE_POLL_SECONDS", 30.0), contextlib.redirect_stderr(log):
            daemon._ensure_worker_started()
            self.addCleanup(daemon.shutdown)
            time.sleep(0.2)  # let the worker go idle
            daemon._on_hotkey_press()
            daemon._on_hotkey_release()
            self.assertTrue(sent.wait(10), log.getvalue())

    def test_shutdown_wakes_an_idle_worker(self) -> None:
        daemon = self._daemon()
        with patch("dictate.daemon.WORKER_IDLE_POLL_SECONDS", 30.0):
            daemon._ensure_worker_started()
            time.sleep(0.2)
            daemon.shutdown()
            assert daemon._worker is not None
            daemon._worker.join(5)
            self.assertFalse(daemon._worker.is_alive())


if __name__ == "__main__":
    unittest.main()
