from __future__ import annotations

import contextlib
import io
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from dictate.audio import AudioCaptureError, AudioChunk
from dictate.history import HistoryStore
from dictate.stt.base import SttCapabilities, TranscriptSegment

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


class _DiarizingApiStt(_FakeApiStt):
    capabilities = SttCapabilities(supports_speaker_attribution=True)

    def __init__(self) -> None:
        super().__init__()
        self.diarized_calls: list[int] = []

    def transcribe_diarized(self, audio, *args, **kwargs):  # noqa: ANN001
        del args, kwargs
        self.diarized_calls.append(len(audio))
        return "Speaker 1: hosted final"


class _SegmentDiarizingStt(_FakeStt):
    backend_name = "parakeet-pyannote"
    model_name = "parakeet-tdt-0.6b-v2"
    capabilities = SttCapabilities(supports_speaker_attribution=True)

    def __init__(self) -> None:
        self.segment_calls: list[int] = []

    def transcribe_diarized_segments(self, audio, *args, **kwargs):  # noqa: ANN001
        del args, kwargs
        self.segment_calls.append(len(audio))
        return [
            TranscriptSegment(
                text="hello",
                t_start=0.0,
                t_end=0.4,
                speaker_id="SPEAKER_A",
                speaker_label="Speaker 1",
            ),
            TranscriptSegment(
                text="reply",
                t_start=0.5,
                t_end=1.0,
                speaker_id="SPEAKER_B",
                speaker_label="Speaker 2",
            ),
        ]


class _ChunkingStt(_FakeStt):
    capabilities = SttCapabilities(supports_streaming_chunks=True)

    def __init__(self, mapping: dict[int, str]) -> None:
        self.mapping = mapping
        self.calls: list[int] = []

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del args, kwargs
        self.calls.append(len(audio))
        return self.mapping.get(len(audio), "")


class _FakeFasterWhisperStt(_ChunkingStt):
    backend_name = "faster-whisper"
    model_name = "turbo"


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


class _FailingFasterWhisperStt(_FakeFasterWhisperStt):
    def __init__(self) -> None:
        super().__init__({16: "first"})
        self.calls = 0

    def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
        del args, kwargs
        self.calls += 1
        if self.calls == 1:
            return "first"
        raise RuntimeError("boom")


class _FakeRecorder:
    def __init__(self) -> None:
        self.is_recording = False
        self.start_kwargs: list[dict[str, object]] = []

    def start(self, on_chunk=None, recording_id=None, **kwargs) -> None:  # noqa: ANN001
        self.is_recording = True
        self.on_chunk = on_chunk
        self.recording_id = recording_id
        self.start_kwargs.append(dict(kwargs))

    def stop(self) -> np.ndarray:
        self.is_recording = False
        return np.ones(16, dtype=np.float32)


class _NoteStreamingRecorder(_FakeRecorder):
    def stop(self) -> np.ndarray:
        self.is_recording = False
        return np.array([], dtype=np.float32)


class _PauseFlushRecorder(_FakeRecorder):
    def stop(self) -> np.ndarray:
        self.is_recording = False
        hook = getattr(self, "on_chunk", None)
        if hook is not None:
            hook(
                AudioChunk(
                    samples=np.full(4, 0.5, dtype=np.float32),
                    final=False,
                    sequence=0,
                    recording_id=self.recording_id or 0,
                    t_start=0.0,
                    t_end=0.25,
                )
            )
        return np.array([], dtype=np.float32)


class _SilenceHookRecorder(_FakeRecorder):
    def start(self, on_chunk=None, recording_id=None, **kwargs) -> None:  # noqa: ANN001
        super().start(on_chunk=on_chunk, recording_id=recording_id, **kwargs)
        self.on_samples = kwargs.get("on_samples")

    def emit_samples(self, samples: np.ndarray) -> None:
        hook = getattr(self, "on_samples", None)
        if hook is not None:
            hook(samples)


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


class _StopCallbackRecorder(_FakeRecorder):
    def stop(self) -> np.ndarray:
        self.is_recording = False
        callback = getattr(self, "on_chunk", None)
        if callback is None:
            return np.array([], dtype=np.float32)

        def _invoke_callback() -> None:
            callback(
                AudioChunk(
                    samples=np.ones(4, dtype=np.float32),
                    final=False,
                    sequence=0,
                    recording_id=self.recording_id or 0,
                    t_start=0.0,
                    t_end=0.25,
                )
            )

        thread = threading.Thread(target=_invoke_callback)
        thread.start()
        thread.join(timeout=1.0)
        if thread.is_alive():
            raise RuntimeError("callback did not finish")
        return np.array([], dtype=np.float32)


class _BlockingStopRecorder(_FakeRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.stop_entered = threading.Event()
        self.stop_release = threading.Event()
        self.start_called = threading.Event()

    def start(self, on_chunk=None, recording_id=None, **kwargs) -> None:  # noqa: ANN001
        super().start(on_chunk=on_chunk, recording_id=recording_id, **kwargs)
        self.start_called.set()

    def stop(self) -> np.ndarray:
        self.stop_entered.set()
        self.stop_release.wait(timeout=2.0)
        self.is_recording = False
        return np.array([], dtype=np.float32)


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

    def test_note_streaming_local_persists_segments_and_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            stt = _FakeFasterWhisperStt({4: "hello", 8: "world"})
            recorder = _FakeRecorder()
            transcripts: list[dict[str, object]] = []
            note_events: list[dict[str, object]] = []
            daemon = Daemon(
                stt,
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
                transcript_callback=transcripts.append,
                note_callback=note_events.append,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            self.assertIsNotNone(recorder.on_chunk)
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]

            recorder.on_chunk(
                AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, sequence=0, recording_id=recording_id)
            )
            daemon._handle_partial_chunk(
                AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, sequence=0, recording_id=recording_id)
            )
            recorder.on_chunk(
                AudioChunk(samples=np.full(8, 2, dtype=np.float32), final=False, sequence=1, recording_id=recording_id)
            )
            daemon._handle_partial_chunk(
                AudioChunk(samples=np.full(8, 2, dtype=np.float32), final=False, sequence=1, recording_id=recording_id)
            )

            self.assertEqual(notes.assembled_text(note_id), "hello world")
            self.assertTrue(any(event.get("phase") == "partial" for event in transcripts))

            self.assertTrue(daemon.stop_note_recording())
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=recording_id)
            )

            output.send.assert_not_called()
            self.assertEqual(hist.load()[0].text, "hello world")
            self.assertEqual(note_events[0]["text"], "hello world")
            self.assertEqual(note_events[0]["status"], "ok")
            note = notes.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "ready")

    def test_note_mark_ready_failure_does_not_surface_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            note_events: list[dict[str, object]] = []
            statuses: list[str | None] = []
            stt = _FakeFasterWhisperStt({16: "hello"})
            recorder = _FakeRecorder()
            daemon = Daemon(
                stt,
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
                status_callback=statuses.append,
                note_callback=note_events.append,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]

            original_mark_ready = notes.mark_ready

            def _boom(note_id: str, *, duration_s: float | None = None) -> None:  # noqa: ARG001
                del duration_s
                raise OSError("disk full")

            notes.mark_ready = _boom  # type: ignore[method-assign]
            try:
                self.assertTrue(daemon.stop_note_recording())
                daemon._handle_final_chunk(daemon._audio_queue.get_nowait())
            finally:
                notes.mark_ready = original_mark_ready  # type: ignore[method-assign]

            self.assertEqual(hist.load(), [])
            self.assertEqual(len(note_events), 1)
            self.assertEqual(note_events[0]["status"], "failed")
            self.assertEqual(note_events[0]["text"], "")
            self.assertTrue(any("Note save failed" in (status or "") for status in statuses))
            note = notes.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "failed")
            self.assertFalse(daemon.note_recording_active)
            self.assertFalse(daemon.note_recording_paused)
            self.assertIsNone(daemon._active_recording_id)

    def test_note_streaming_pause_resume_preserves_chunk_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            stt = _FakeFasterWhisperStt({4: "hello", 8: "world"})
            recorder = _NoteStreamingRecorder()
            daemon = Daemon(
                stt,
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]

            chunk0 = AudioChunk(
                samples=np.ones(4, dtype=np.float32),
                final=False,
                sequence=0,
                recording_id=recording_id,
                t_start=0.0,
                t_end=0.25,
            )
            recorder.on_chunk(chunk0)
            daemon._handle_partial_chunk(chunk0)

            self.assertTrue(daemon.pause_note_recording())
            self.assertTrue(daemon.resume_note_recording())
            self.assertEqual(recorder.start_kwargs[-1]["note_chunk_seq_offset"], 1)
            self.assertEqual(recorder.start_kwargs[-1]["note_time_offset_s"], 0.25)

            chunk1 = AudioChunk(
                samples=np.full(8, 2, dtype=np.float32),
                final=False,
                sequence=1,
                recording_id=recording_id,
                t_start=0.25,
                t_end=0.75,
            )
            recorder.on_chunk(chunk1)
            daemon._handle_partial_chunk(chunk1)

            segments = notes.load_segments(note_id)
            self.assertEqual([segment.seq for segment in segments], [0, 1])

    def test_note_chunk_resume_offsets_use_unique_persisted_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteSegment, NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(_FakeStt(), output=output, history_store=hist, note_store=notes)

            note_id = notes.create_note(provider="faster-whisper", model="turbo", recording_id=3)
            notes.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=0.5,
                    provider="faster-whisper",
                    model="turbo",
                    text="hello",
                ),
            )
            notes.append_segment(
                note_id,
                NoteSegment(
                    seq=1,
                    t_start=0.3,
                    t_end=0.8,
                    provider="faster-whisper",
                    model="turbo",
                    text="world",
                ),
            )

            daemon._recording_note_ids[3] = note_id
            self.assertEqual(daemon._note_chunk_resume_offsets(3), (2, 0.8))

    def test_note_pause_resume_uses_queued_pause_flush_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            recorder = _PauseFlushRecorder()
            daemon = Daemon(
                _FakeFasterWhisperStt({4: "first", 8: "second"}),
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]

            self.assertTrue(daemon.pause_note_recording())
            self.assertGreater(daemon._partial_audio_queue.qsize(), 0)

            self.assertTrue(daemon.resume_note_recording())
            self.assertEqual(recorder.start_kwargs[-1]["note_chunk_seq_offset"], 1)
            self.assertEqual(recorder.start_kwargs[-1]["note_time_offset_s"], 0.25)

            queued = daemon._partial_audio_queue.get_nowait()
            daemon._handle_partial_chunk(queued)

            resumed_chunk = AudioChunk(
                samples=np.full(8, 0.5, dtype=np.float32),
                final=False,
                sequence=1,
                recording_id=recording_id,
                t_start=0.25,
                t_end=0.75,
            )
            daemon._handle_partial_chunk(resumed_chunk)

            segments = notes.load_segments(note_id)
            self.assertEqual([segment.seq for segment in segments], [0, 1])
            self.assertEqual([segment.t_start for segment in segments], [0.0, 0.25])
            self.assertEqual([segment.t_end for segment in segments], [0.25, 0.75])

    def test_live_note_failure_stops_active_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            recorder = _FakeRecorder()
            daemon = Daemon(
                _FakeFasterWhisperStt({16: "hello"}),
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None

            original_append_segment = notes.append_segment

            def _boom(note_id: str, segment) -> None:  # noqa: ANN001
                del note_id, segment
                raise OSError("disk full")

            notes.append_segment = _boom  # type: ignore[method-assign]
            daemon._handle_partial_chunk(
                AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=recording_id)
            )
            notes.append_segment = original_append_segment  # type: ignore[method-assign]

            deadline = time.time() + 2.0
            while time.time() < deadline and (
                recorder.is_recording or daemon._active_recording_id is not None
            ):
                time.sleep(0.01)

            self.assertFalse(recorder.is_recording)
            self.assertIsNone(daemon._active_recording_id)
            self.assertFalse(daemon.note_recording_active)
            self.assertFalse(daemon.note_recording_paused)
            self.assertTrue(daemon.start_note_recording())
            daemon.stop_note_recording()

    def test_stale_failed_cleanup_does_not_stop_newer_recording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            recorder = _FakeRecorder()
            daemon = Daemon(
                _FakeFasterWhisperStt({16: "alpha"}),
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            first_recording_id = daemon._active_recording_id
            assert first_recording_id is not None

            cleanup_started = threading.Event()
            cleanup_release = threading.Event()
            original_cleanup = daemon._cleanup_failed_recording_session

            def _gated_cleanup(recording_id: int) -> None:
                cleanup_started.set()
                cleanup_release.wait(timeout=2.0)
                original_cleanup(recording_id)

            daemon._cleanup_failed_recording_session = _gated_cleanup  # type: ignore[method-assign]

            daemon._fail_recording_session(first_recording_id, "Transcription backlog exceeded")
            self.assertTrue(cleanup_started.wait(timeout=2.0))

            self.assertTrue(daemon.stop_note_recording())
            self.assertTrue(daemon.start_note_recording())
            second_recording_id = daemon._active_recording_id
            assert second_recording_id is not None

            cleanup_release.set()
            deadline = time.time() + 2.0
            while time.time() < deadline and daemon._active_recording_id != second_recording_id:
                time.sleep(0.01)

            self.assertTrue(recorder.is_recording)
            self.assertEqual(daemon._active_recording_id, second_recording_id)
            self.assertFalse(daemon.note_recording_paused)
            daemon.stop_note_recording()

    def test_note_auto_pause_after_sustained_silence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from unittest.mock import patch

            from dictate.daemon import Daemon
            from dictate.note_silence import NoteSilenceMonitor

            recorder = _SilenceHookRecorder()
            monitor = NoteSilenceMonitor(sample_rate=16000, pause_after_seconds=0.05, silence_rms=0.05)
            daemon = Daemon(
                _FakeStt(),
                output=MagicMock(),
                history_store=HistoryStore(path=Path(tmp) / "h.json"),
                recorder=recorder,
                note_silence_monitor=monitor,
            )
            with patch("dictate.daemon.play_pause_cue"):
                self.assertTrue(daemon.start_note_recording())
                recorder.emit_samples(np.zeros(500, dtype=np.float32))
                recorder.emit_samples(np.zeros(500, dtype=np.float32))
                deadline = time.time() + 1.0
                while time.time() < deadline and not daemon.note_recording_paused:
                    time.sleep(0.01)
            self.assertTrue(daemon.note_recording_paused)
            self.assertEqual(daemon.note_pause_reason, "silence")

    def test_note_pause_backpressure_does_not_report_paused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            recording_events: list[bool] = []
            note_events: list[tuple[bool, bool, str | None]] = []
            recorder = _PauseFlushRecorder()
            daemon = Daemon(
                _FakeFasterWhisperStt({4: "first"}),
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
                recording_callback=recording_events.append,
                note_recording_callback=lambda recording, paused=False, pause_reason=None: note_events.append(
                    (recording, paused, pause_reason)
                ),
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]
            daemon._partial_audio_queue = queue.Queue(maxsize=1)
            daemon._partial_audio_queue.put_nowait(
                AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, recording_id=recording_id)
            )

            self.assertFalse(daemon.pause_note_recording())
            self.assertFalse(daemon.note_recording_paused)
            self.assertEqual(recording_events[-1], False)
            self.assertEqual(note_events[-1], (False, False, None))
            self.assertTrue(daemon._is_recording_failed(recording_id))

            note = notes.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "failed")

    def test_note_pause_stop_callback_backpressure_does_not_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            recorder = _StopCallbackRecorder()
            daemon = Daemon(
                _FakeFasterWhisperStt({}),
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]
            daemon._partial_audio_queue = queue.Queue(maxsize=1)
            daemon._partial_audio_queue.put_nowait(
                AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, recording_id=recording_id)
            )

            self.assertFalse(daemon.pause_note_recording())
            self.assertFalse(recorder.is_recording)
            self.assertFalse(daemon.note_recording_paused)
            self.assertIsNone(daemon._active_recording_id)
            self.assertTrue(daemon._is_recording_failed(recording_id))

            note = notes.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "failed")

    def test_start_waits_for_stop_to_finish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            recorder = _BlockingStopRecorder()
            daemon = Daemon(
                _FakeFasterWhisperStt({}),
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recorder.start_called.clear()

            stop_result: list[bool] = []

            def _stop() -> None:
                stop_result.append(daemon.stop_note_recording())

            stop_thread = threading.Thread(target=_stop)
            stop_thread.start()
            self.assertTrue(recorder.stop_entered.wait(timeout=1.0))

            start_result: list[bool] = []

            def _start() -> None:
                start_result.append(daemon.start_note_recording())

            start_thread = threading.Thread(target=_start)
            start_thread.start()
            time.sleep(0.1)

            self.assertFalse(recorder.start_called.is_set())
            self.assertTrue(start_thread.is_alive())

            recorder.stop_release.set()
            stop_thread.join(timeout=1.0)
            start_thread.join(timeout=1.0)

            self.assertFalse(stop_thread.is_alive())
            self.assertFalse(start_thread.is_alive())
            self.assertEqual(stop_result, [True])
            self.assertEqual(start_result, [True])
            self.assertTrue(recorder.start_called.is_set())

    def test_failed_note_recording_remains_stoppable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            recording_events: list[bool] = []
            note_events: list[tuple[bool, bool, str | None]] = []
            daemon = Daemon(
                _FakeFasterWhisperStt({}),
                output=output,
                history_store=store,
                recorder=_FakeRecorder(),
                recording_callback=recording_events.append,
                note_recording_callback=lambda recording, paused=False, pause_reason=None: note_events.append(
                    (recording, paused, pause_reason)
                ),
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]

            daemon._fail_recording_session(recording_id, "Transcription backlog exceeded")

            self.assertFalse(daemon.note_recording_active)
            self.assertEqual(recording_events[-1], False)
            self.assertEqual(note_events[-1], (False, False, None))

            deadline = time.time() + 2.0
            while time.time() < deadline and (
                daemon.recorder.is_recording or daemon._active_recording_id is not None
            ):
                time.sleep(0.01)

            self.assertFalse(daemon.recorder.is_recording)
            self.assertIsNone(daemon._active_recording_id)
            self.assertTrue(daemon.start_note_recording())
            self.assertTrue(daemon.stop_note_recording())

            note = daemon.note_store.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "failed")
            self.assertFalse(store.load())

    def test_stop_note_recording_handles_active_and_paused_notes_without_hanging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(
                _FakeFasterWhisperStt({}),
                output=output,
                history_store=store,
                recorder=_FakeRecorder(),
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            self.assertTrue(daemon.stop_note_recording())
            self.assertFalse(daemon.recorder.is_recording)
            self.assertFalse(daemon.note_recording_paused)

            self.assertTrue(daemon.start_note_recording())
            self.assertTrue(daemon.pause_note_recording())
            self.assertTrue(daemon.note_recording_paused)
            self.assertTrue(daemon.stop_note_recording())
            self.assertFalse(daemon.recorder.is_recording)
            self.assertFalse(daemon.note_recording_paused)

    def test_old_failed_note_does_not_inactivate_newer_recording(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            recording_events: list[bool] = []
            note_events: list[tuple[bool, bool, str | None]] = []
            daemon = Daemon(
                _FakeFasterWhisperStt({16: "hello"}),
                output=output,
                history_store=store,
                recorder=_FakeRecorder(),
                recording_callback=recording_events.append,
                note_recording_callback=lambda recording, paused=False, pause_reason=None: note_events.append(
                    (recording, paused, pause_reason)
                ),
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            first_recording_id = daemon._active_recording_id
            assert first_recording_id is not None
            self.assertTrue(daemon.stop_note_recording())

            self.assertTrue(daemon.start_note_recording())
            second_recording_id = daemon._active_recording_id
            assert second_recording_id is not None

            daemon._fail_recording_session(first_recording_id, "Transcription backlog exceeded")

            self.assertEqual(recording_events[-1], True)
            self.assertEqual(note_events[-1], (True, False, None))
            self.assertTrue(daemon.note_recording_active)
            self.assertEqual(daemon._active_recording_id, second_recording_id)

    def test_dictation_streaming_failure_does_not_stop_active_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            recording_events: list[bool] = []
            note_events: list[tuple[bool, bool, str | None]] = []
            recorder = _FakeRecorder()
            daemon = Daemon(
                _FailingChunkStt(),
                output=output,
                history_store=store,
                recorder=recorder,
                recording_callback=recording_events.append,
                note_recording_callback=lambda recording, paused=False, pause_reason=None: note_events.append(
                    (recording, paused, pause_reason)
                ),
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon._start_recording())
            self.assertIsNotNone(recorder.on_chunk)
            daemon._handle_partial_chunk(AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=1))
            daemon._handle_partial_chunk(AudioChunk(samples=np.full(16, 2, dtype=np.float32), recording_id=1))

            self.assertTrue(recorder.is_recording)
            self.assertEqual(daemon._active_recording_id, 1)
            self.assertFalse(daemon.note_recording_active)
            self.assertFalse(daemon.note_recording_paused)
            self.assertEqual(recording_events[-1], True)
            self.assertEqual(note_events, [])
            self.assertTrue(daemon._is_recording_failed(1))

    def test_note_store_failure_fails_recording_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(
                _FakeFasterWhisperStt({4: "hello"}),
                output=output,
                history_store=HistoryStore(path=Path(tmp) / "h.json"),
                note_store=notes,
                recorder=_FakeRecorder(),
            )
            daemon.engine.min_duration_s = 0
            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]

            original_append = notes.append_segment

            def _boom(note_id_arg: str, segment) -> None:  # noqa: ANN001
                del note_id_arg, segment
                raise OSError("disk full")

            notes.append_segment = _boom  # type: ignore[method-assign]
            chunk = AudioChunk(
                samples=np.ones(4, dtype=np.float32),
                final=False,
                sequence=0,
                recording_id=recording_id,
                t_start=0.0,
                t_end=0.25,
            )
            self.assertEqual(daemon._append_note_stream_piece(chunk, "hello"), "")
            self.assertTrue(daemon._is_recording_failed(recording_id))
            note = notes.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "failed")
            notes.append_segment = original_append  # type: ignore[method-assign]

    def test_note_recording_saves_note_without_typing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _FakeApiStt()
            recorder = _FakeRecorder()
            notes: list[dict[str, object]] = []
            note_states: list[bool] = []
            daemon = Daemon(
                stt,
                output=output,
                history_store=store,
                recorder=recorder,
                note_callback=notes.append,
                note_recording_callback=note_states.append,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            self.assertTrue(daemon.stop_note_recording())
            chunk = daemon._audio_queue.get_nowait()
            daemon._handle_final_chunk(chunk)

            output.send.assert_not_called()
            self.assertEqual(stt.calls, [16])
            self.assertEqual(store.load()[0].text, "hosted final")
            self.assertEqual(notes[0]["text"], "hosted final")
            self.assertEqual(notes[0]["raw_text"], "hosted final")
            self.assertEqual(note_states, [True, False])

    def test_note_success_includes_status_ok(self) -> None:
        """The note callback payload must carry status='ok' on the success path."""
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            notes: list[dict[str, object]] = []
            daemon = Daemon(
                _FakeApiStt(),
                output=output,
                history_store=store,
                recorder=_FakeRecorder(),
                note_callback=notes.append,
            )
            daemon.engine.min_duration_s = 0
            daemon.start_note_recording()
            daemon.stop_note_recording()
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["status"], "ok")
            self.assertEqual(notes[0]["text"], "hosted final")

    def test_note_empty_recording_publishes_terminal_signal(self) -> None:
        """Empty note recording (no speech) must publish status='empty' via the note channel.

        Without this, the webview is stuck on "Transcribing…" indefinitely because
        _surface_empty_final_status only prints to stderr and never publishes an event.
        """
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            class _SilentStt(_FakeStt):
                """Returns empty transcription — simulates silence / no speech."""
                def transcribe(self, audio, *args, **kwargs):  # noqa: ANN001
                    del audio, args, kwargs
                    return ""

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            notes: list[dict[str, object]] = []
            daemon = Daemon(
                _SilentStt(),
                output=output,
                history_store=store,
                recorder=_FakeRecorder(),
                note_callback=notes.append,
            )
            daemon.engine.min_duration_s = 0
            daemon.start_note_recording()
            daemon.stop_note_recording()
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            # Must emit exactly one terminal signal so the UI can leave "Transcribing…".
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["status"], "empty")
            self.assertEqual(notes[0]["text"], "")
            # Nothing saved to history for an empty capture.
            self.assertEqual(store.load(), [])
            output.send.assert_not_called()

    def test_note_failed_recording_publishes_terminal_signal(self) -> None:
        """A failed note recording must publish status='failed' via the note channel.

        _fail_recording_session fires a stale transcript already, but the note
        channel signal is the primary, deterministic mechanism for the webview.
        """
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            notes: list[dict[str, object]] = []
            daemon = Daemon(
                _FakeApiStt(),
                output=output,
                history_store=store,
                recorder=_FakeRecorder(),
                note_callback=notes.append,
            )
            daemon.engine.min_duration_s = 0
            daemon.start_note_recording()
            daemon.stop_note_recording()
            recording_id = daemon._audio_queue.get_nowait().recording_id
            # Simulate a transcription failure (overload / STT error).
            daemon._fail_recording_session(recording_id, "Transcription backlog exceeded")

            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["status"], "failed")
            self.assertEqual(notes[0]["text"], "")

    def test_note_start_failure_does_not_leave_ghost_active_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            statuses: list[str | None] = []
            notes: list[dict[str, object]] = []
            recorder = _FakeRecorder()
            daemon = Daemon(
                _FakeFasterWhisperStt({}),
                output=output,
                history_store=store,
                recorder=recorder,
                status_callback=statuses.append,
                note_callback=notes.append,
            )
            daemon.engine.min_duration_s = 0

            original_create_note = daemon.note_store.create_note

            def _boom(*args, **kwargs):  # noqa: ANN001
                del args, kwargs
                raise OSError("disk full")

            daemon.note_store.create_note = _boom  # type: ignore[method-assign]
            try:
                self.assertFalse(daemon.start_note_recording())
            finally:
                daemon.note_store.create_note = original_create_note  # type: ignore[method-assign]

            self.assertFalse(recorder.is_recording)
            self.assertFalse(daemon.note_recording_active)
            self.assertFalse(daemon.note_recording_paused)
            self.assertIsNone(daemon._active_recording_id)
            self.assertEqual(recorder.start_kwargs, [])
            self.assertEqual(store.load(), [])
            self.assertEqual(notes[-1]["status"], "failed")
            self.assertEqual(notes[-1]["text"], "")
            self.assertTrue(any("Note recording failed" in (status or "") for status in statuses))

    def test_note_recording_uses_plain_asr_when_backend_diarization_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _DiarizingApiStt()
            recorder = _FakeRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            self.assertTrue(daemon.stop_note_recording())
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(stt.calls, [16])
            self.assertEqual(stt.diarized_calls, [])
            self.assertEqual(store.load()[0].text, "hosted final")
            output.send.assert_not_called()

    def test_meeting_recording_requires_backend_speaker_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _FakeApiStt()
            recorder = _FakeRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_meeting_recording())
            self.assertTrue(daemon.stop_meeting_recording())
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(stt.calls, [])
            self.assertEqual(store.load(), [])

    def test_meeting_recording_uses_backend_speaker_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _DiarizingApiStt()
            recorder = _FakeRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_meeting_recording())
            self.assertTrue(daemon.stop_meeting_recording())
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(stt.calls, [])
            self.assertEqual(stt.diarized_calls, [16])
            self.assertEqual(store.load()[0].text, "Speaker 1: hosted final")
            output.send.assert_not_called()

    def test_meeting_recording_can_use_dedicated_speaker_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            primary_stt = _FakeApiStt()
            meeting_stt = _DiarizingApiStt()
            recorder = _FakeRecorder()
            daemon = Daemon(
                primary_stt,
                output=output,
                history_store=store,
                recorder=recorder,
                meeting_stt=meeting_stt,
            )
            daemon.engine.min_duration_s = 0
            assert daemon.meeting_engine is not None
            daemon.meeting_engine.min_duration_s = 0

            self.assertTrue(daemon.start_meeting_recording())
            self.assertTrue(daemon.stop_meeting_recording())
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(primary_stt.calls, [])
            self.assertEqual(meeting_stt.diarized_calls, [16])
            self.assertEqual(store.load()[0].text, "Speaker 1: hosted final")

            self.assertTrue(daemon.start_note_recording())
            self.assertTrue(daemon.stop_note_recording())
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(primary_stt.calls, [16])
            self.assertEqual(meeting_stt.diarized_calls, [16])

    def test_meeting_recording_persists_structured_speaker_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            stt = _SegmentDiarizingStt()
            recorder = _FakeRecorder()
            note_events: list[dict[str, object]] = []
            daemon = Daemon(
                stt,
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
                note_callback=note_events.append,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_meeting_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]
            self.assertTrue(daemon.stop_meeting_recording())
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(stt.segment_calls, [16])
            note = notes.load_note(note_id)
            assert note is not None
            self.assertEqual(note.mode, "meeting")
            self.assertTrue(note.speaker_labels)
            self.assertEqual(note.status, "ready")
            segments = notes.load_segments(note_id)
            self.assertEqual(len(segments), 2)
            self.assertEqual(segments[0].speaker_label, "Speaker 1")
            self.assertEqual(segments[0].t_start, 0.0)
            self.assertEqual(segments[1].speaker_id, "SPEAKER_B")
            self.assertEqual(hist.load()[0].text, "Speaker 1: hello Speaker 2: reply")
            self.assertEqual(note_events[-1]["segments"][0]["speaker_label"], "Speaker 1")
            self.assertEqual(note_events[-1]["id"], note_id)
            self.assertEqual(note_events[-1]["mode"], "meeting")
            self.assertEqual(note_events[-1]["createdAt"], note.started_at)
            output.send.assert_not_called()

    def test_meeting_recording_callback_includes_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            events: list[dict[str, object]] = []
            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(
                _DiarizingApiStt(),
                output=output,
                history_store=store,
                recorder=_FakeRecorder(),
                note_recording_callback=lambda recording, **kwargs: events.append(
                    {"recording": recording, **kwargs}
                ),
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_meeting_recording())
            self.assertTrue(daemon.stop_meeting_recording())

            self.assertEqual(events[0]["mode"], "meeting")
            self.assertEqual(events[-1]["mode"], "meeting")

    def test_push_to_talk_does_not_use_backend_diarization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _DiarizingApiStt()
            recorder = _FakeRecorder()
            daemon = Daemon(stt, output=output, history_store=store, recorder=recorder)
            daemon.engine.min_duration_s = 0

            daemon._start_recording()
            daemon._finalize_recording()
            daemon._handle_final_chunk(daemon._audio_queue.get_nowait())

            self.assertEqual(stt.calls, [16])
            self.assertEqual(stt.diarized_calls, [])
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

    def test_queue_partial_audio_drops_oldest_when_overloaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daemon, _store, _output = self._make_daemon(tmp)
            daemon._partial_audio_queue = queue.Queue(maxsize=1)
            daemon.recorder._recording = True
            daemon._active_recording_id = 8
            self._seed_recording(daemon, 8)

            first = AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, recording_id=8)
            second = AudioChunk(samples=np.full(4, 2, dtype=np.float32), final=False, recording_id=8)
            self.assertTrue(daemon._queue_partial_audio(first))
            self.assertTrue(daemon._queue_partial_audio(second))
            self.assertEqual(daemon._partial_audio_queue.qsize(), 1)
            queued = daemon._partial_audio_queue.get_nowait()
            np.testing.assert_array_equal(queued.samples, second.samples)

    def test_queue_partial_audio_fails_note_streaming_when_overloaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(
                _FakeFasterWhisperStt({}),
                output=output,
                history_store=HistoryStore(path=Path(tmp) / "h.json"),
                note_store=notes,
                recorder=_FakeRecorder(),
            )
            daemon._partial_audio_queue = queue.Queue(maxsize=1)
            daemon.recorder._recording = True
            daemon._active_recording_id = 8
            self._seed_recording(daemon, 8)
            daemon._streaming_recordings.add(8)
            daemon._note_streaming_recordings.add(8)
            note_id = notes.create_note(provider="faster-whisper", model="turbo", recording_id=8)
            daemon._recording_note_ids[8] = note_id

            first = AudioChunk(samples=np.ones(4, dtype=np.float32), final=False, recording_id=8)
            second = AudioChunk(samples=np.full(4, 2, dtype=np.float32), final=False, recording_id=8)
            self.assertTrue(daemon._queue_partial_audio(first))
            self.assertFalse(daemon._queue_partial_audio(second))
            self.assertTrue(daemon._is_recording_failed(8))
            note = notes.load_note(note_id)
            assert note is not None
            self.assertEqual(note.status, "failed")

    def test_partial_window_overload_keeps_session_alive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({4: "stale"})
            daemon = Daemon(stt, output=output, history_store=store)
            daemon.engine.min_duration_s = 0
            daemon._partial_audio_queue = queue.Queue(maxsize=1)
            daemon.recorder._recording = True
            daemon._active_recording_id = 7
            self._seed_recording(daemon, 7)
            daemon._streaming_recordings.add(7)

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

            self.assertEqual(store.load()[0].text, "stale")
            self.assertEqual(stt.calls, [4])
            output.send.assert_called_once_with("stale")

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

    def test_failed_post_stop_session_clears_recording_maps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon
            from dictate.note_store import NoteStore

            hist = HistoryStore(path=Path(tmp) / "h.json")
            notes = NoteStore(root=Path(tmp) / "notes")
            output = MagicMock()
            output.name = "mock"
            recorder = _NoteStreamingRecorder()
            daemon = Daemon(
                _FailingFasterWhisperStt(),
                output=output,
                history_store=hist,
                note_store=notes,
                recorder=recorder,
            )
            daemon.engine.min_duration_s = 0

            self.assertTrue(daemon.start_note_recording())
            recording_id = daemon._active_recording_id
            assert recording_id is not None
            note_id = daemon._recording_note_ids[recording_id]

            first_chunk = AudioChunk(
                samples=np.ones(16, dtype=np.float32),
                final=False,
                sequence=0,
                recording_id=recording_id,
                t_start=0.0,
                t_end=1.0,
            )
            daemon._handle_partial_chunk(first_chunk)
            self.assertEqual(daemon._recording_note_chunk_cursors[recording_id], (1, 1.0))

            self.assertTrue(daemon.stop_note_recording())

            failing_chunk = AudioChunk(
                samples=np.full(16, 2, dtype=np.float32),
                final=False,
                sequence=1,
                recording_id=recording_id,
                t_start=1.0,
                t_end=2.0,
            )
            daemon._handle_partial_chunk(failing_chunk)

            self.assertNotIn(recording_id, daemon._recording_modes)
            self.assertNotIn(recording_id, daemon._recording_note_chunk_cursors)
            self.assertNotIn(recording_id, daemon._recording_note_ids)
            self.assertNotIn(recording_id, daemon._recording_prompt_tails)
            self.assertNotIn(recording_id, daemon._recording_stt_ids)
            self.assertFalse(recorder.is_recording)
            self.assertFalse(daemon.note_recording_active)
            self.assertFalse(notes.load_note(note_id) is None)

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

    def test_failed_final_tail_enqueue_does_not_restore_failed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            daemon = Daemon(_ChunkingStt({16: "dropped"}), output=output, history_store=store)
            daemon._audio_queue = queue.Queue(maxsize=1)
            daemon._audio_queue.put_nowait(AudioChunk(samples=np.ones(16, dtype=np.float32), final=True, recording_id=0))
            self._seed_recording(daemon, 3)

            daemon._queue_recording_chunk(
                AudioChunk(samples=np.ones(16, dtype=np.float32), final=True, recording_id=3)
            )

            self.assertNotIn(3, daemon._recording_parts)
            self.assertNotIn(3, daemon._recording_chunk_counts)
            self.assertNotIn(3, daemon._recording_final_chunks)
            self.assertNotIn(3, daemon._recording_stt_ids)
            output.send.assert_not_called()

    def test_successful_finalization_makes_late_chunks_silent_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16: "hello", 8: "late"})
            transcripts: list[dict[str, object]] = []
            daemon = Daemon(stt, output=output, history_store=store, transcript_callback=transcripts.append)
            daemon.engine.min_duration_s = 0
            self._seed_recording(daemon, 4)

            daemon._handle_partial_chunk(AudioChunk(samples=np.ones(16, dtype=np.float32), recording_id=4))
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=4)
            )
            daemon._handle_partial_chunk(AudioChunk(samples=np.ones(8, dtype=np.float32), recording_id=4))

            self.assertEqual(stt.calls, [16])
            output.send.assert_called_once_with("hello")
            self.assertEqual([event.get("stale") for event in transcripts], [False, False])

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

    def test_short_final_tail_after_streamed_text_is_transcribed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16000: "hello", 1600: "world"})
            daemon = Daemon(stt, output=output, history_store=store)
            self._seed_recording(daemon, 14)

            daemon._handle_partial_chunk(
                AudioChunk(samples=np.ones(16000, dtype=np.float32), final=False, recording_id=14)
            )
            daemon._handle_final_chunk(
                AudioChunk(samples=np.full(1600, 2, dtype=np.float32), final=True, recording_id=14)
            )

            self.assertEqual(stt.calls, [16000, 1600])
            output.send.assert_called_once_with("hello world")
            self.assertEqual(store.load()[0].text, "hello world")

    def test_empty_final_marker_after_streamed_text_still_commits_prior_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16000: "hello"})
            daemon = Daemon(stt, output=output, history_store=store)
            self._seed_recording(daemon, 15)

            daemon._handle_partial_chunk(
                AudioChunk(samples=np.ones(16000, dtype=np.float32), final=False, recording_id=15)
            )
            daemon._handle_final_chunk(
                AudioChunk(samples=np.array([], dtype=np.float32), final=True, recording_id=15)
            )

            self.assertEqual(stt.calls, [16000])
            output.send.assert_called_once_with("hello")
            self.assertEqual(store.load()[0].text, "hello")

    def test_no_speech_short_final_tail_after_streamed_text_does_not_drop_prior_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from dictate.daemon import Daemon

            store = HistoryStore(path=Path(tmp) / "h.json")
            output = MagicMock()
            output.name = "mock"
            stt = _ChunkingStt({16000: "hello"})
            daemon = Daemon(stt, output=output, history_store=store)
            self._seed_recording(daemon, 16)

            daemon._handle_partial_chunk(
                AudioChunk(samples=np.ones(16000, dtype=np.float32), final=False, recording_id=16)
            )
            daemon._handle_final_chunk(
                AudioChunk(samples=np.full(1600, 2, dtype=np.float32), final=True, recording_id=16)
            )

            self.assertEqual(stt.calls, [16000, 1600])
            output.send.assert_called_once_with("hello")
            self.assertEqual(store.load()[0].text, "hello")

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

    def test_sounddevice_recorder_exact_capacity_is_not_truncated(self) -> None:
        from dictate.audio import SoundDeviceRecorder

        recorder = SoundDeviceRecorder(
            sample_rate=4,
            max_recording_seconds=1,
            transcription_window_seconds=2,
        )
        recorder._recording = True

        recorder._audio_callback(np.ones((4, 1), dtype=np.float32), 4, None, None)
        audio = recorder.stop()

        self.assertFalse(recorder.truncated)
        self.assertEqual(audio.shape[0], 4)

    def test_sounddevice_stop_time_callback_is_included_in_final_tail(self) -> None:
        from dictate.audio import SoundDeviceRecorder

        seen: list[AudioChunk] = []
        recorder = SoundDeviceRecorder(
            sample_rate=4,
            max_recording_seconds=2,
            transcription_window_seconds=2,
        )

        class _StopCallbackStream:
            def stop(self) -> None:
                recorder._audio_callback(np.full((2, 1), 2, dtype=np.float32), 2, None, None)

            def close(self) -> None:
                pass

        recorder._recording = True
        recorder._stream = _StopCallbackStream()
        recorder._on_chunk = seen.append
        recorder._recording_id = 4
        recorder._audio_callback(np.ones((2, 1), dtype=np.float32), 2, None, None)

        audio = recorder.stop()

        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].final)
        self.assertEqual(seen[0].recording_id, 4)
        np.testing.assert_array_equal(seen[0].samples, np.array([1, 1, 2, 2], dtype=np.float32))
        np.testing.assert_array_equal(audio, np.array([1, 1, 2, 2], dtype=np.float32))

    def test_sounddevice_recorder_note_chunks_flush_on_stop(self) -> None:
        from dictate.audio import SoundDeviceRecorder
        from dictate.note_chunker import NoteChunkAccumulator

        seen: list[AudioChunk] = []
        recorder = SoundDeviceRecorder(
            sample_rate=10,
            max_recording_seconds=2,
            transcription_window_seconds=1,
        )
        recorder._recording = True
        recorder._on_chunk = seen.append
        recorder._recording_id = 9
        recorder._note_chunks = True
        recorder._note_accumulator = NoteChunkAccumulator(
            sample_rate=10,
            min_chunk_seconds=0.5,
            max_chunk_seconds=2.0,
            silence_gap_seconds=0.2,
            overlap_seconds=0.0,
            silence_rms=0.05,
        )

        recorder._audio_callback(np.full((3, 1), 0.5, dtype=np.float32), 3, None, None)
        self.assertEqual(len(seen), 0)

        audio = recorder.stop()

        self.assertEqual(audio.shape[0], 0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].sequence, 0)
        self.assertEqual(seen[0].recording_id, 9)
        self.assertFalse(seen[0].final)

    def test_sounddevice_recorder_overlap_stream_flushes_and_marks_stream_final(self) -> None:
        import os
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        # Test the raw chunking/flush behavior without the AGC/noise-suppression
        # preprocessor (which buffers 10 ms and would shift exact sample counts).
        self.enterContext(patch.dict(os.environ, {"DICTATE_DENOISE": "0"}))
        from dictate.audio import (
            DICTATION_MAX_CHUNK_SECONDS,
            DICTATION_MIN_CHUNK_SECONDS,
            DICTATION_OVERLAP_SECONDS,
            SoundDeviceRecorder,
        )

        seen: list[AudioChunk] = []
        recorder = SoundDeviceRecorder(
            sample_rate=16000,
            max_recording_seconds=10,
            transcription_window_seconds=2,
        )
        stream = MagicMock()
        fake_sd = SimpleNamespace(
            InputStream=MagicMock(return_value=stream),
        )
        with (
            patch("dictate.audio.resolve_input_capture", return_value=(0, 16000)),
            patch.dict("sys.modules", {"sounddevice": fake_sd}),
        ):
            recorder.start(on_chunk=seen.append, recording_id=7, overlap_stream=True)

        # The dictation overlap accumulator is built with the DICTATION_* constants,
        # not the note defaults.
        acc = recorder._note_accumulator
        self.assertIsNotNone(acc)
        self.assertEqual(acc.min_samples, int(16000 * DICTATION_MIN_CHUNK_SECONDS))
        self.assertEqual(acc.max_samples, int(16000 * DICTATION_MAX_CHUNK_SECONDS))
        self.assertEqual(acc.overlap_samples, int(16000 * DICTATION_OVERLAP_SECONDS))

        # Feed enough continuous speech to force a mid-stream (hard-cap) chunk plus a
        # remainder that only flushes on stop().
        recorder._audio_callback(np.full((80000, 1), 0.5, dtype=np.float32), 80000, None, None)
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].stream_final)

        audio = recorder.stop()

        # overlap_stream sessions carry no ring-buffer final audio (chunks own it all).
        self.assertEqual(audio.shape[0], 0)
        self.assertEqual(len(seen), 2)
        self.assertFalse(seen[0].stream_final)
        self.assertTrue(seen[1].stream_final)
        self.assertEqual(seen[0].recording_id, 7)
        self.assertEqual(seen[1].recording_id, 7)

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
