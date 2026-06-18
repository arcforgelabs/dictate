from __future__ import annotations

import contextlib
import io
import queue
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from dictate.audio import AudioCaptureError, AudioChunk
from dictate.history import HistoryStore
from dictate.stt.base import SttCapabilities

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
    capabilities = SttCapabilities()

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

    def __init__(self) -> None:
        self.calls: list[int] = []

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del args, kwargs
        self.calls.append(len(audio))
        return "hosted final"


class _ChunkingStt(_FakeStt):
    capabilities = SttCapabilities(supports_streaming_chunks=True)

    def __init__(self, mapping: dict[int, str]) -> None:
        self.mapping = mapping
        self.calls: list[int] = []

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del args, kwargs
        self.calls.append(len(audio))
        return self.mapping.get(len(audio), "")


class _ErrorStt(_FakeStt):
    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del audio, args, kwargs
        raise RuntimeError("boom")


class _FailingChunkStt(_FakeStt):
    capabilities = SttCapabilities(supports_streaming_chunks=True)

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del audio, args, kwargs
        self.calls += 1
        if self.calls == 1:
            return "first"
        raise RuntimeError("boom")


class _FakeRecorder:
    def __init__(self) -> None:
        self.is_recording = False

    def start(self, on_chunk=None, recording_id=None) -> None:  # noqa: ANN001
        self.is_recording = True
        self.on_chunk = on_chunk
        self.recording_id = recording_id

    def stop(self) -> np.ndarray:
        self.is_recording = False
        return np.ones(16, dtype=np.float32)


class _NoCallbackRecorder(_FakeRecorder):
    def start(self, on_chunk=None, recording_id=None) -> None:  # noqa: ANN001
        self.is_recording = True
        self.on_chunk = None
        self.recording_id = recording_id


class _StrictStartRecorder(_FakeRecorder):
    def start(self) -> None:
        self.is_recording = True


class _StopErrorRecorder(_FakeRecorder):
    def stop(self) -> np.ndarray:
        self.is_recording = False
        raise AudioCaptureError("stop failed")


class _TruncatedRecorder(_FakeRecorder):
    truncated = True

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

    def _seed_recording(self, daemon, recording_id: int) -> None:  # noqa: ANN001
        daemon._recording_stt_ids[recording_id] = id(daemon.engine.stt)
        daemon._recording_parts[recording_id] = []

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

    def test_hosted_backend_does_not_receive_partial_chunk_transcription(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _FakeApiStt()
            recorder = _FakeRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            self.assertIsNone(recorder.on_chunk)
            daemon._finalize_recording()

            chunk = daemon._audio_queue.get_nowait()
            self.assertTrue(chunk.final)
            self.assertEqual(stt.calls, [])
            daemon._handle_final_chunk(chunk)
            self.assertEqual(stt.calls, [16])
            output.send.assert_called_once_with("hosted final")

    def test_backend_switch_discards_queued_streaming_chunks_before_hosted_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            local_stt = _ChunkingStt({16: "local chunk"})
            hosted_stt = _FakeApiStt()
            recorder = _FakeRecorder()
            statuses: list[str | None] = []
            transcripts: list[dict[str, object]] = []
            daemon = Daemon(
                local_stt,
                output=output,
                history_store=store,
                status_callback=statuses.append,
                transcript_callback=transcripts.append,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            assert recorder.on_chunk is not None
            recorder.on_chunk(AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=1))
            chunk = daemon._partial_audio_queue.get_nowait()
            daemon.switch_speech_to_text(hosted_stt)
            daemon._handle_partial_chunk(chunk)

            self.assertEqual(local_stt.calls, [])
            self.assertEqual(hosted_stt.calls, [])
            self.assertFalse(store.load())
            output.send.assert_not_called()
            self.assertTrue(any("backend changed" in (message or "") for message in statuses))
            self.assertTrue(any(event.get("reason") == "stale-backend" for event in transcripts))

    def test_cleared_recording_state_drops_stale_chunk_without_hosted_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            local_stt = _ChunkingStt({16: "local chunk"})
            hosted_stt = _FakeApiStt()
            transcripts: list[dict[str, object]] = []
            daemon = Daemon(
                local_stt,
                output=output,
                history_store=store,
                transcript_callback=transcripts.append,
            )
            daemon.engine.min_duration_s = 0
            daemon._recording_stt_ids[13] = id(local_stt)
            daemon._recording_parts[13] = []
            daemon._clear_recording_state(13)
            daemon.switch_speech_to_text(hosted_stt)

            daemon._handle_partial_chunk(AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=13))

            self.assertEqual(hosted_stt.calls, [])
            self.assertNotIn(13, daemon._recording_parts)
            self.assertFalse(store.load())
            output.send.assert_not_called()
            self.assertTrue(any(event.get("reason") == "stale-backend" for event in transcripts))

    def test_unknown_recording_chunks_are_not_enqueued_during_later_recording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            recorder = _FakeRecorder()
            daemon = Daemon(_ChunkingStt({16: "stale"}), output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0
            daemon._start_recording()
            self.assertEqual(daemon._active_recording_id, 1)

            daemon._queue_recording_chunk(AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=99))
            daemon._queue_recording_chunk(
                AudioChunk(samples=np.ones(16, dtype=np.float32), final=True, recording_id=99)
            )

            self.assertTrue(daemon._partial_audio_queue.empty())
            self.assertTrue(daemon._audio_queue.empty())
            self.assertNotIn(99, daemon._recording_chunk_counts)
            self.assertNotIn(99, daemon._recording_final_chunks)
            output.send.assert_not_called()

    def test_backend_switch_race_cannot_send_stale_chunk_to_hosted_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            local_stt = _ChunkingStt({16: "local chunk"})
            hosted_stt = _FakeApiStt()
            statuses: list[str | None] = []
            transcripts: list[dict[str, object]] = []
            daemon = Daemon(
                local_stt,
                output=output,
                history_store=store,
                status_callback=statuses.append,
                transcript_callback=transcripts.append,
            )
            daemon.engine.min_duration_s = 0
            daemon._recording_stt_ids[1] = id(local_stt)
            chunk = AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=1)

            daemon._engine_lock.acquire()
            try:
                worker = threading.Thread(target=daemon._handle_partial_chunk, args=(chunk,))
                worker.start()
                daemon.engine.stt = hosted_stt
            finally:
                daemon._engine_lock.release()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive())

            self.assertEqual(local_stt.calls, [])
            self.assertEqual(hosted_stt.calls, [])
            self.assertFalse(store.load())
            output.send.assert_not_called()
            self.assertTrue(any("backend changed" in (message or "") for message in statuses))
            self.assertTrue(any(event.get("reason") == "stale-backend" for event in transcripts))

    def test_recorder_without_chunk_callbacks_commits_stop_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16: "legacy final"})
            recorder = _NoCallbackRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            daemon._finalize_recording()
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(stt.calls, [16])
            output.send.assert_called_once_with("legacy final")
            self.assertEqual(store.load()[0].text, "legacy final")

    def test_strict_no_arg_recorder_start_falls_back_to_stop_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16: "strict final"})
            recorder = _StrictStartRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            daemon._finalize_recording()
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(stt.calls, [16])
            output.send.assert_called_once_with("strict final")
            self.assertEqual(store.load()[0].text, "strict final")

    def test_tail_final_chunk_does_not_queue_second_empty_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({2: "tail"})
            recorder = _FakeRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            assert recorder.on_chunk is not None
            recorder.on_chunk(AudioChunk(samples=np.ones(2, dtype=np.float32), final=True, recording_id=1))
            daemon._finalize_recording()

            self.assertEqual(daemon._audio_queue.qsize(), 1)
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())
            self.assertTrue(daemon._audio_queue.empty())
            output.send.assert_called_once_with("tail")

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
            daemon._audio_queue.put_nowait(
                AudioChunk(samples=np.ones(16, dtype=np.float32), final=True)
            )

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
            self.assertIsInstance(daemon._audio_queue.get_nowait(), AudioChunk)

    def test_queue_latest_audio_preserves_window_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, _output = self._make_daemon(tmp)
            first = np.ones(4, dtype=np.float32)
            second = np.full(4, 2, dtype=np.float32)
            daemon.recorder._recording = True
            daemon._active_recording_id = 8
            self._seed_recording(daemon, 8)

            daemon._queue_latest_audio(first)
            daemon._queue_latest_audio(second)

            queued_first = daemon._partial_audio_queue.get_nowait()
            queued_second = daemon._partial_audio_queue.get_nowait()
            np.testing.assert_array_equal(queued_first.samples, first)
            np.testing.assert_array_equal(queued_second.samples, second)
            self.assertFalse(queued_first.final)
            self.assertFalse(queued_second.final)
            with self.assertRaises(queue.Empty):
                daemon._partial_audio_queue.get_nowait()

    def test_queue_partial_audio_emits_stale_notice_when_overloaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, _output = self._make_daemon(tmp)
            notices: list[dict[str, object]] = []
            daemon.transcript_callback = notices.append
            daemon.status_callback = lambda _message: None
            daemon._partial_audio_queue = queue.Queue(maxsize=1)
            daemon.recorder._recording = True
            daemon._active_recording_id = 8
            self._seed_recording(daemon, 8)

            daemon._queue_latest_audio(np.ones(4, dtype=np.float32))
            daemon._queue_latest_audio(np.full(4, 2, dtype=np.float32))

            self.assertTrue(any(event.get("stale") for event in notices))
            self.assertNotIn(8, daemon._recording_parts)

    def test_partial_window_overload_fails_session_instead_of_omitting_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon, TERMINAL_RECORDING_CACHE_SIZE

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({4: "stale"})
            daemon = Daemon(stt, output=output, history_store=store)
            daemon.engine.min_duration_s = 0
            statuses: list[str | None] = []
            transcripts: list[dict[str, object]] = []
            daemon.status_callback = statuses.append
            daemon.transcript_callback = transcripts.append
            daemon._partial_audio_queue = queue.Queue(maxsize=1)
            daemon.recorder._recording = True
            daemon._active_recording_id = 7
            self._seed_recording(daemon, 7)

            daemon._queue_partial_audio(
                AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, recording_id=7)
            )
            daemon._queue_partial_audio(
                AudioChunk(samples=np.full(4, 2, dtype=np.float32), final=False, recording_id=7)
            )
            stale_chunk = daemon._partial_audio_queue.get_nowait()
            daemon._handle_partial_chunk(stale_chunk)
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=7)
            )
            for recording_id in range(100, 100 + TERMINAL_RECORDING_CACHE_SIZE + 8):
                daemon._fail_recording_session(recording_id, "Transcription backlog exceeded")

            self.assertTrue(any("backlog exceeded" in (message or "") for message in statuses))
            self.assertTrue(any(event.get("stale") for event in transcripts))
            self.assertNotIn(7, daemon._recording_parts)
            self.assertLessEqual(len(daemon._terminal_recordings), TERMINAL_RECORDING_CACHE_SIZE)
            self.assertEqual(stt.calls, [])
            self.assertFalse(store.load())
            output.send.assert_not_called()

    def test_chunk_transcription_error_fails_instead_of_committing_prior_piece(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _FailingChunkStt()
            statuses: list[str | None] = []
            transcripts: list[dict[str, object]] = []
            daemon = Daemon(
                stt,
                output=output,
                history_store=store,
                status_callback=statuses.append,
                transcript_callback=transcripts.append,
            )
            daemon.engine.min_duration_s = 0
            self._seed_recording(daemon, 4)

            daemon._handle_partial_chunk(
                AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=4)
            )
            daemon._handle_partial_chunk(
                AudioChunk(samples=np.full(16, 2, dtype=np.float32), recording_id=4)
            )
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=4)
            )

            self.assertEqual(stt.calls, 2)
            self.assertFalse(store.load())
            output.send.assert_not_called()
            self.assertTrue(any("Transcription failed: boom" in (message or "") for message in statuses))
            self.assertTrue(any(event.get("reason") == "transcription-error" for event in transcripts))
            self.assertNotIn(4, daemon._recording_parts)

    def test_final_error_reports_failure_instead_of_no_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            statuses: list[str | None] = []
            daemon = Daemon(_ErrorStt(), output=output, history_store=store, status_callback=statuses.append)
            daemon.engine.min_duration_s = 0
            self._seed_recording(daemon, 5)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                daemon._handle_final_chunk(
                    AudioChunk(samples=np.ones(16, dtype=np.float32), final=True, recording_id=5)
                )

            self.assertTrue(any("Transcription failed: boom" in (message or "") for message in statuses))
            self.assertNotIn("No audio captured", stderr.getvalue())
            self.assertFalse(store.load())
            output.send.assert_not_called()

    def test_final_no_speech_reports_no_speech_instead_of_no_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(_FakeStt(), output=output, history_store=store)
            daemon.engine.min_duration_s = 0
            self._seed_recording(daemon, 6)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                daemon._handle_final_chunk(
                    AudioChunk(samples=np.ones(16, dtype=np.float32), final=True, recording_id=6)
                )

            self.assertIn("No speech detected", stderr.getvalue())
            self.assertNotIn("No audio captured", stderr.getvalue())
            self.assertFalse(store.load())
            output.send.assert_not_called()

    def test_streaming_no_speech_final_marker_reports_no_speech(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(_FakeStt(), output=output, history_store=store)
            daemon.engine.min_duration_s = 0
            self._seed_recording(daemon, 10)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                daemon._handle_partial_chunk(
                    AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=10)
                )
                daemon._handle_final_chunk(
                    AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=10)
                )

            self.assertIn("No speech detected", stderr.getvalue())
            self.assertNotIn("No audio captured", stderr.getvalue())
            self.assertFalse(store.load())
            output.send.assert_not_called()

    def test_streaming_too_short_final_marker_reports_too_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(_FakeStt(), output=output, history_store=store)
            self._seed_recording(daemon, 12)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                daemon._handle_partial_chunk(
                    AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=12)
                )
                daemon._handle_final_chunk(
                    AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=12)
                )

            self.assertIn("Too short, skipped", stderr.getvalue())
            self.assertNotIn("No audio captured", stderr.getvalue())
            self.assertFalse(store.load())
            output.send.assert_not_called()

    def test_final_audio_overload_cleans_up_recording_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, _output = self._make_daemon(tmp)
            transcript_events: list[dict[str, object]] = []
            status_events: list[str | None] = []
            daemon.transcript_callback = transcript_events.append
            daemon.status_callback = status_events.append
            self._seed_recording(daemon, 9)
            daemon._recording_parts[9] = ["hello"]

            for recording_id in range(1, 5):
                self._seed_recording(daemon, recording_id)
                daemon._queue_final_chunk(
                    AudioChunk(
                        samples=np.full(4, recording_id, dtype=np.float32),
                        final=True,
                        recording_id=recording_id,
                    )
                )

            daemon._queue_final_chunk(
                AudioChunk(samples=np.full(4, 5, dtype=np.float32), final=True, recording_id=9)
            )

            self.assertEqual(daemon._audio_queue.qsize(), 4)
            self.assertTrue(any("dropped" in (message or "") for message in status_events))
            self.assertTrue(any(event.get("reason") == "dropped-overload" for event in transcript_events))
            self.assertNotIn(9, daemon._recording_parts)
            self.assertEqual(
                [daemon._audio_queue.get_nowait().recording_id for _ in range(4)],
                [1, 2, 3, 4],
            )

    def test_terminal_recording_callback_does_not_recreate_state_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, output = self._make_daemon(tmp)
            transcripts: list[dict[str, object]] = []
            daemon.transcript_callback = transcripts.append
            daemon._recording_parts[11] = ["already failed"]
            daemon._recording_chunk_counts[11] = 1
            daemon._streaming_recordings.add(11)

            daemon._fail_recording_session(11, "Transcription backlog exceeded")
            daemon._queue_recording_chunk(
                AudioChunk(samples=np.ones(16, dtype=np.float32), final=False, recording_id=11)
            )
            daemon._finalize_recording()

            self.assertNotIn(11, daemon._recording_parts)
            self.assertNotIn(11, daemon._recording_chunk_counts)
            self.assertNotIn(11, daemon._recording_final_chunks)
            self.assertNotIn(11, daemon._streaming_recordings)
            self.assertTrue(any(event.get("stale") for event in transcripts))
            output.send.assert_not_called()

    def test_stop_capture_error_marks_recording_terminal_and_clears_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16: "stale"})
            recorder = _StopErrorRecorder()
            statuses: list[str | None] = []
            transcripts: list[dict[str, object]] = []
            daemon = Daemon(
                stt,
                output=output,
                history_store=store,
                status_callback=statuses.append,
                transcript_callback=transcripts.append,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            assert recorder.on_chunk is not None
            recorder.on_chunk(AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=1))
            queued = daemon._partial_audio_queue.get_nowait()
            daemon._finalize_recording()
            daemon._handle_partial_chunk(queued)

            self.assertTrue(any("stop failed" in (message or "") for message in statuses))
            self.assertTrue(any(event.get("reason") == "capture-error" for event in transcripts))
            self.assertNotIn(1, daemon._recording_parts)
            self.assertNotIn(1, daemon._recording_chunk_counts)
            self.assertNotIn(1, daemon._streaming_recordings)
            self.assertNotIn(1, daemon._recording_stt_ids)
            self.assertEqual(stt.calls, [])
            self.assertFalse(store.load())
            output.send.assert_not_called()

    def test_stop_time_callback_after_recorder_false_is_counted_only_when_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16: "queued during stop"})
            recorder = _FakeRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0
            daemon._start_recording()
            recorder.is_recording = False

            daemon._queue_recording_chunk(AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=1))

            self.assertEqual(daemon._recording_chunk_counts[1], 1)
            queued = daemon._partial_audio_queue.get_nowait()
            daemon._handle_partial_chunk(queued)
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=1)
            )
            output.send.assert_called_once_with("queued during stop")

    def test_final_tail_accounting_does_not_recreate_state_after_fast_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16: "tail"})
            daemon = Daemon(stt, output=output, history_store=store, recorder=_FakeRecorder())
            daemon.engine.min_duration_s = 0
            daemon._start_recording()

            def drain_immediately(chunk: AudioChunk) -> bool:
                daemon._handle_final_chunk(chunk)
                return True

            daemon._queue_final_chunk = drain_immediately
            daemon._queue_recording_chunk(
                AudioChunk(samples=np.ones(16, dtype=np.float32), final=True, recording_id=1)
            )

            output.send.assert_called_once_with("tail")
            self.assertNotIn(1, daemon._recording_parts)
            self.assertNotIn(1, daemon._recording_chunk_counts)
            self.assertNotIn(1, daemon._recording_final_chunks)
            self.assertNotIn(1, daemon._recording_stt_ids)

    def test_hosted_truncated_stop_audio_fails_instead_of_committing_partial_ring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _FakeApiStt()
            transcripts: list[dict[str, object]] = []
            statuses: list[str | None] = []
            daemon = Daemon(
                stt,
                output=output,
                history_store=store,
                status_callback=statuses.append,
                transcript_callback=transcripts.append,
                recorder=_TruncatedRecorder(),
            )
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            daemon._finalize_recording()

            self.assertEqual(stt.calls, [])
            self.assertTrue(daemon._audio_queue.empty())
            self.assertTrue(any("retained audio limit" in (message or "") for message in statuses))
            self.assertTrue(any(event.get("reason") == "truncated-audio" for event in transcripts))
            self.assertFalse(store.load())
            output.send.assert_not_called()

    def test_streaming_capable_truncated_stop_audio_without_chunks_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16: "partial ring"})
            transcripts: list[dict[str, object]] = []
            statuses: list[str | None] = []
            daemon = Daemon(
                stt,
                output=output,
                history_store=store,
                status_callback=statuses.append,
                transcript_callback=transcripts.append,
                recorder=_TruncatedRecorder(),
            )
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            daemon._finalize_recording()

            self.assertEqual(stt.calls, [])
            self.assertTrue(daemon._audio_queue.empty())
            self.assertTrue(any("retained audio limit" in (message or "") for message in statuses))
            self.assertTrue(any(event.get("reason") == "truncated-audio" for event in transcripts))
            self.assertFalse(store.load())
            output.send.assert_not_called()

    def test_exact_window_recording_commits_assembled_streamed_text_and_stays_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({4: "hello", 2: "world"})
            from dictate.daemon import Daemon

            daemon = Daemon(stt, output=output, history_store=store)
            daemon.engine.min_duration_s = 0
            self._seed_recording(daemon, 1)
            self._seed_recording(daemon, 2)
            daemon._handle_partial_chunk(
                AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, recording_id=1)
            )
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=1)
            )
            daemon._handle_partial_chunk(
                AudioChunk(samples=np.full(2, 2, dtype=np.float32), final=False, recording_id=2)
            )
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=2)
            )

            entries = store.load()
            self.assertEqual([entry.text for entry in entries], ["world", "hello"])
            self.assertEqual([call.args[0] for call in output.send.call_args_list], ["hello", "world"])
            self.assertEqual(stt.calls, [4, 2])
            self.assertFalse(daemon._stop.is_set())

    def test_overlapping_recordings_keep_their_transcripts_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({4: "hello", 2: "world"})
            from dictate.daemon import Daemon

            daemon = Daemon(stt, output=output, history_store=store, recorder=_FakeRecorder())
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            daemon._handle_partial_chunk(
                AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, recording_id=1)
            )
            daemon.recorder.is_recording = False
            daemon._start_recording()
            daemon._handle_partial_chunk(
                AudioChunk(samples=np.full(2, 2, dtype=np.float32), final=False, recording_id=2)
            )
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=1)
            )
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=2)
            )

            entries = store.load()
            self.assertEqual([entry.text for entry in entries], ["world", "hello"])
            self.assertEqual([call.args[0] for call in output.send.call_args_list], ["hello", "world"])

    def test_sounddevice_recorder_emits_windowed_chunks_and_tail(self) -> None:
        from dictate.audio import SoundDeviceRecorder

        seen: list[AudioChunk] = []
        recorder = SoundDeviceRecorder(
            sample_rate=4,
            max_recording_seconds=1,
            transcription_window_seconds=1,
        )
        recorder._recording = True
        recorder._on_chunk = seen.append

        recorder._audio_callback(np.ones((2, 1), dtype=np.float32), 2, None, None)
        recorder._audio_callback(np.ones((1, 1), dtype=np.float32), 1, None, None)
        recorder._audio_callback(np.ones((1, 1), dtype=np.float32), 1, None, None)
        recorder._audio_callback(np.ones((4, 1), dtype=np.float32), 4, None, None)
        recorder._audio_callback(np.ones((2, 1), dtype=np.float32), 2, None, None)
        audio = recorder.stop()

        self.assertTrue(recorder._truncated)
        self.assertEqual(audio.shape[0], 4)
        self.assertEqual(len(seen), 3)
        self.assertFalse(seen[0].final)
        self.assertEqual(seen[1].sequence, 1)
        self.assertFalse(seen[1].final)
        self.assertEqual(seen[2].sequence, 2)
        self.assertTrue(seen[2].final)

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
