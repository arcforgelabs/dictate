"""Push-to-talk daemon. Listens for a configured combo and runs shared dictation pipeline."""

from __future__ import annotations

import logging
import queue
import sys
import time
import threading
from collections import deque
from collections.abc import Callable
from typing import Literal

logger = logging.getLogger(__name__)

import numpy as np

from dictate.audio import AudioCaptureError, AudioChunk, AudioRecorder, SoundDeviceRecorder
from dictate.cue_sound import play_pause_cue
from dictate.engine import DictationEngine, TranscriptionResult
from dictate.history import HistoryStore
from dictate.note_store import NoteSegment, NoteStore
from dictate.note_silence import NoteSilenceMonitor
from dictate.transcript_merge import merge_transcript_piece, prompt_tail
from dictate.hotkey import format_hotkey_combo, normalize_push_to_talk_combo
from dictate.hotkey_backend import (
    HotkeyBackend,
    HotkeyBackendUnavailableError,
    create_hotkey_backend,
)
from dictate.lexicon import LexiconMode
from dictate.outputs import TextOutput
from dictate.provider_supervisor import ProviderSupervisor
from dictate.stt import SpeechToText, TranscriptSegment

# Retry policy for long recordings (note mode) when remote transcription fails.
# We retry the full chunk up to N times with exponential backoff before degrading.
_LONG_RECORDING_MAX_RETRIES = 2
_LONG_RECORDING_RETRY_BASE_DELAY = 1.0  # seconds

SAMPLE_RATE = 16000
NOTE_MAX_RECORDING_SECONDS = 900
FINAL_AUDIO_QUEUE_SIZE = 4
FINAL_WINDOW_QUEUE_SIZE = 128
TERMINAL_RECORDING_CACHE_SIZE = FINAL_AUDIO_QUEUE_SIZE + FINAL_WINDOW_QUEUE_SIZE
_FINAL_CHUNK_EMPTY = object()
RecordingMode = Literal["dictation", "note", "meeting"]


class Daemon:
    def __init__(
        self,
        stt: SpeechToText,
        *,
        output: TextOutput,
        language: str | None = None,
        hotwords: str | None = None,
        lexicon_mode: LexiconMode = "native",
        lexicon_replacements: dict[str, str] | None = None,
        history_store: HistoryStore | None = None,
        note_store: NoteStore | None = None,
        note_silence_monitor: NoteSilenceMonitor | None = None,
        push_to_talk_combo: str = "ctrl_r",
        status_callback: Callable[[str | None], None] | None = None,
        recording_callback: Callable[[bool], None] | None = None,
        history_callback: Callable[[], None] | None = None,
        transcript_callback: Callable[[dict[str, object]], None] | None = None,
        note_recording_callback: Callable[[bool], None] | None = None,
        note_callback: Callable[[dict[str, object]], None] | None = None,
        audio_level_callback: Callable[[float], None] | None = None,
        recorder: AudioRecorder | None = None,
        supervisor: ProviderSupervisor | None = None,
        meeting_stt: SpeechToText | None = None,
    ):
        self.active = True
        self.language = language
        self.output = output
        self.history_store = history_store or HistoryStore()
        self.note_store = note_store or NoteStore()
        self.status_callback = status_callback
        self.recording_callback = recording_callback
        self.history_callback = history_callback
        self.transcript_callback = transcript_callback
        self.note_recording_callback = note_recording_callback
        self.note_callback = note_callback
        self.audio_level_callback = audio_level_callback
        self.push_to_talk_combo = normalize_push_to_talk_combo(push_to_talk_combo)
        self.supervisor = supervisor
        self.engine = DictationEngine(
            stt=stt,
            sample_rate=SAMPLE_RATE,
            hotwords=hotwords,
            lexicon_mode=lexicon_mode,
            lexicon_replacements=lexicon_replacements,
        )
        self.meeting_engine: DictationEngine | None = None
        if meeting_stt is not None:
            self.meeting_engine = DictationEngine(
                stt=meeting_stt,
                sample_rate=SAMPLE_RATE,
                hotwords=hotwords,
                lexicon_mode=lexicon_mode,
                lexicon_replacements=lexicon_replacements,
            )
        # Wire the supervisor as the engine's health_sink so remote
        # success/failure is reported automatically on every transcription.
        if supervisor is not None:
            self.engine.health_sink = _make_supervisor_health_sink(supervisor)
        self.recorder = recorder or SoundDeviceRecorder(
            sample_rate=SAMPLE_RATE,
            max_recording_seconds=NOTE_MAX_RECORDING_SECONDS,
        )
        self._engine_lock = threading.Lock()
        self._recording_lock = threading.RLock()

        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._audio_queue: queue.Queue[AudioChunk | None] = queue.Queue(maxsize=FINAL_AUDIO_QUEUE_SIZE)
        self._partial_audio_queue: queue.Queue[AudioChunk] = queue.Queue(maxsize=FINAL_WINDOW_QUEUE_SIZE)
        self._hotkey_backend: HotkeyBackend | None = None
        self._recording_generation = 0
        self._recording_parts: dict[int, list[str]] = {}
        self._recording_chunk_counts: dict[int, int] = {}
        self._recording_final_chunks: set[int] = set()
        self._streaming_recordings: set[int] = set()
        self._recording_stt_ids: dict[int, int] = {}
        self._recording_last_audio_status: dict[int, TranscriptionResult] = {}
        self._recording_modes: dict[int, RecordingMode] = {}
        self._recording_note_ids: dict[int, str] = {}
        self._recording_prompt_tails: dict[int, str] = {}
        self._recording_note_chunk_cursors: dict[int, tuple[int, float]] = {}
        self._note_streaming_recordings: set[int] = set()
        self._terminal_recordings: set[int] = set()
        self._terminal_recording_order: deque[int] = deque()
        self._active_recording_id: int | None = None
        self._note_recording_paused = False
        self._note_pause_reason: str | None = None
        self._note_silence_monitor = note_silence_monitor or NoteSilenceMonitor(sample_rate=SAMPLE_RATE)
        self._note_auto_pause_pending = False
        self._queue_lock = threading.Lock()
        self._recorder_control_lock = threading.Lock()

    def pause(self) -> None:
        """Stop listening for hotkey."""
        self.active = False
        if self.recorder.is_recording:
            self._finalize_recording()

    def resume(self) -> None:
        """Resume listening for hotkey."""
        self.active = True

    def set_hotwords(self, hotwords: str | None) -> None:
        """Update hotwords without restarting daemon."""
        with self._engine_lock:
            self.engine.set_hotwords(hotwords)
            if self.meeting_engine is not None:
                self.meeting_engine.set_hotwords(hotwords)

    def clear_active_api_key(self, backend: str) -> None:
        """Remove a hosted backend key from the currently loaded STT object."""
        with self._engine_lock:
            stt = self.engine.stt
            if stt.backend_name == backend and hasattr(stt, "api_key"):
                setattr(stt, "api_key", "")
            if self.meeting_engine is not None:
                meeting_stt = self.meeting_engine.stt
                if meeting_stt.backend_name == backend and hasattr(meeting_stt, "api_key"):
                    setattr(meeting_stt, "api_key", "")

    def set_push_to_talk_combo(self, combo: str) -> None:
        """Update push-to-talk combo without restarting daemon."""
        self.push_to_talk_combo = normalize_push_to_talk_combo(combo)
        if self._hotkey_backend is not None:
            self._hotkey_backend.set_combo(self.push_to_talk_combo)
        else:
            self._ensure_worker_started()
            self._start_hotkey_backend()
        if self.recorder.is_recording:
            self._finalize_recording()

    def start_note_recording(self) -> bool:
        """Start a conversation note recording independent of push-to-talk."""
        with self._recording_lock:
            if self._note_recording_paused:
                return self.resume_note_recording()
        return self._start_recording(mode="note")

    def start_meeting_recording(self) -> bool:
        """Start a meeting recording that requires speaker attribution."""
        return self._start_recording(mode="meeting")

    def pause_note_recording(self, *, pause_reason: str = "manual") -> bool:
        """Pause an active note recording without finalizing the session."""
        with self._recorder_control_lock:
            with self._recording_lock:
                recording_id = self._active_recording_id
                if (
                    recording_id is None
                    or self._note_recording_paused
                    or not self.recorder.is_recording
                    or self._recording_mode(recording_id) != "note"
                ):
                    return False
            try:
                audio = self.recorder.stop()
            except AudioCaptureError as exc:
                print(f"\r  Microphone error: {exc}", file=sys.stderr)
                return False
            if self._is_recording_failed(recording_id):
                return False
            if audio.size > 0:
                if not self._queue_partial_audio(
                    AudioChunk(
                        samples=audio,
                        final=False,
                        sequence=0,
                        recording_id=recording_id,
                    )
                ):
                    return False
            with self._recording_lock:
                if self._active_recording_id != recording_id or self._is_recording_failed(recording_id):
                    return False
                self._note_recording_paused = True
                self._note_pause_reason = pause_reason
                self._note_silence_monitor.reset()
            play_pause_cue()
            self._notify_recording(False)
            self._notify_note_recording(False, paused=True, pause_reason=pause_reason)
            return True

    def resume_note_recording(self) -> bool:
        """Resume a paused note recording on the same session."""
        with self._recorder_control_lock:
            with self._recording_lock:
                if not self._note_recording_paused:
                    return False
                recording_id = self._active_recording_id
                if recording_id is None or self._recording_mode(recording_id) != "note":
                    return False
                seq_offset = 0
                time_offset_s = 0.0
                if self._is_note_streaming(recording_id):
                    seq_offset, time_offset_s = self._note_chunk_resume_offsets(recording_id)
                try:
                    self.recorder.start(
                        recording_id=recording_id,
                        on_chunk=self._queue_recording_chunk if self._recording_uses_streaming(recording_id) else None,
                        note_chunks=self._is_note_streaming(recording_id),
                        note_chunk_seq_offset=seq_offset,
                        note_time_offset_s=time_offset_s,
                        on_samples=self._on_recording_samples,
                    )
                except TypeError:
                    try:
                        self.recorder.start(
                            recording_id=recording_id,
                            on_chunk=self._queue_recording_chunk if self._recording_uses_streaming(recording_id) else None,
                            on_samples=self._on_recording_samples,
                        )
                    except TypeError:
                        self.recorder.start()
                except (AudioCaptureError, TypeError) as exc:
                    print(f"\r  Microphone error: {exc}", file=sys.stderr)
                    return False
                self._note_recording_paused = False
                self._note_pause_reason = None
                self._note_silence_monitor.reset()
                self._notify_recording(True)
                self._notify_note_recording(True, paused=False)
                return True

    def stop_note_recording(self) -> bool:
        """Stop an active note recording and queue it for note transcription."""
        with self._recorder_control_lock:
            with self._recording_lock:
                recording_id = self._active_recording_id
                if recording_id is None or self._recording_mode(recording_id) != "note":
                    return False
                paused = self._note_recording_paused
        if paused:
            self._finish_paused_note_recording(recording_id)
            return True
        self._finalize_recording()
        return True

    def stop_meeting_recording(self) -> bool:
        """Stop an active meeting recording and queue it for transcription."""
        with self._recording_lock:
            recording_id = self._active_recording_id
            if recording_id is None or self._recording_mode(recording_id) != "meeting":
                return False
        self._finalize_recording()
        return True

    def cancel_note_recording(self) -> bool:
        """Discard an active or paused note recording without saving a note."""
        return self._cancel_long_recording("note")

    def cancel_meeting_recording(self) -> bool:
        """Discard an active or paused meeting recording without saving a note."""
        return self._cancel_long_recording("meeting")

    def _cancel_long_recording(self, expected_mode: RecordingMode) -> bool:
        with self._recorder_control_lock:
            with self._recording_lock:
                recording_id = self._active_recording_id
                if recording_id is None or self._recording_mode(recording_id) != expected_mode:
                    return False
                note_id = self._recording_note_ids.get(recording_id)
                recorder_running = self.recorder.is_recording
            if note_id:
                try:
                    self.note_store.delete_note(note_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not delete discarded note %s: %s", note_id, exc)
            with self._queue_lock:
                self._remember_terminal_recording_locked(recording_id)
            self._purge_queued_chunks_for_recording(recording_id)
            if recorder_running:
                try:
                    self.recorder.stop()
                except AudioCaptureError as exc:
                    print(f"\r  Microphone error: {exc}", file=sys.stderr)
            with self._recording_lock:
                if self._active_recording_id == recording_id:
                    self._active_recording_id = None
                self._note_recording_paused = False
                self._note_pause_reason = None
            self._clear_recording_state(recording_id)
            self._notify_recording(False)
            self._notify_note_recording(False, paused=False, mode=expected_mode, discarded=True)
            self._surface_transcript(
                phase="final",
                text="",
                sequence=None,
                recording_id=recording_id,
                stale=True,
                reason="discarded",
            )
        return True

    def _finish_paused_note_recording(self, recording_id: int) -> None:
        with self._recording_lock:
            if self._active_recording_id != recording_id or not self._note_recording_paused:
                return
            self._note_recording_paused = False
            self._note_pause_reason = None
        self._finish_paused_note_recording_unlocked(recording_id)

    def _finish_paused_note_recording_unlocked(self, recording_id: int) -> None:
        if self._should_queue_final_marker(recording_id):
            self._queue_final_marker(recording_id)
        else:
            self._queue_final_chunk(
                AudioChunk(
                    samples=np.array([], dtype=np.float32),
                    final=True,
                    sequence=0,
                    recording_id=recording_id,
                )
            )
        with self._recording_lock:
            if self._active_recording_id == recording_id:
                self._active_recording_id = None
                self._notify_recording(False)
                self._notify_note_recording(False, paused=False)

    def toggle_note_recording(self) -> bool:
        """Toggle note recording and return whether note capture is active."""
        should_finalize = False
        should_resume = False
        should_start = False
        with self._recording_lock:
            if self._note_recording_paused:
                should_resume = True
            else:
                recording_id = self._active_recording_id
                if self.recorder.is_recording and recording_id is not None:
                    if self._recording_mode(recording_id) == "note":
                        should_finalize = True
                    else:
                        return False
                else:
                    should_start = True
        if should_resume:
            return self.resume_note_recording()
        if should_finalize:
            self._finalize_recording()
            return False
        if should_start:
            return self._start_recording(mode="note")
        return False

    @property
    def note_recording_active(self) -> bool:
        return self.long_recording_active

    @property
    def long_recording_active(self) -> bool:
        recording_id = self._active_recording_id
        return bool(
            recording_id is not None
            and self._recording_mode(recording_id) in {"note", "meeting"}
            and not self._is_recording_failed(recording_id)
        )

    @property
    def long_recording_mode(self) -> RecordingMode | None:
        recording_id = self._active_recording_id
        if recording_id is None or self._is_recording_failed(recording_id):
            return None
        mode = self._recording_mode(recording_id)
        return mode if mode in {"note", "meeting"} else None

    @property
    def note_recording_paused(self) -> bool:
        return self._note_recording_paused

    @property
    def note_pause_reason(self) -> str | None:
        if not self._note_recording_paused:
            return None
        return self._note_pause_reason

    def switch_speech_to_text(self, stt: SpeechToText, *, hotwords: str | None = None) -> None:
        """Swap STT backend/model at runtime."""
        previous_stt: SpeechToText | None = None
        with self._engine_lock:
            previous_stt = self.engine.stt
            self.engine.stt = stt
            self.engine.set_hotwords(hotwords)
            try:
                self.engine.release_api_fallback()
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to release fallback STT resources: {exc}", file=sys.stderr)
        if previous_stt is not None and previous_stt is not stt:
            try:
                previous_stt.release()
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to release previous STT resources: {exc}", file=sys.stderr)

    def set_meeting_speech_to_text(
        self,
        stt: SpeechToText,
        *,
        hotwords: str | None = None,
    ) -> None:
        """Set the dedicated Meeting backend without changing normal dictation."""
        previous_stt: SpeechToText | None = None
        with self._engine_lock:
            if self.meeting_engine is None:
                self.meeting_engine = DictationEngine(
                    stt=stt,
                    sample_rate=SAMPLE_RATE,
                    hotwords=hotwords if hotwords is not None else self.engine.hotwords,
                    lexicon_mode=self.engine.lexicon_mode,
                    lexicon_replacements=self.engine.lexicon_replacements,
                )
            else:
                previous_stt = self.meeting_engine.stt
                self.meeting_engine.stt = stt
                if hotwords is not None:
                    self.meeting_engine.set_hotwords(hotwords)
            try:
                self.meeting_engine.release_api_fallback()
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to release meeting fallback STT resources: {exc}", file=sys.stderr)
        if previous_stt is not None and previous_stt is not stt:
            try:
                previous_stt.release()
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to release previous meeting STT resources: {exc}", file=sys.stderr)

    def current_backend_model(self) -> tuple[str, str]:
        """Return active backend/model selection."""
        with self._engine_lock:
            return (self.engine.stt.backend_name, self.engine.stt.model_name)

    def current_meeting_backend_model(self) -> tuple[str, str] | None:
        """Return dedicated Meeting backend/model selection if configured."""
        with self._engine_lock:
            if self.meeting_engine is None:
                return None
            stt = self.meeting_engine.stt
            return (stt.backend_name, getattr(stt, "model_name", "") or "")

    def runtime_stt_options(self) -> tuple[str, str]:
        """Return current STT device/compute options for new model instantiation."""
        with self._engine_lock:
            stt = self.engine.stt
            device = getattr(stt, "device", "auto")
            compute_type = getattr(stt, "compute_type", "int8")
            return (device, compute_type)

    def shutdown(self) -> None:
        """Clean shutdown."""
        if self._stop.is_set():
            return

        self.active = False
        self._stop.set()

        if self.recorder.is_recording:
            self._finalize_recording()

        if self._hotkey_backend is not None:
            self._hotkey_backend.stop()
            self._hotkey_backend = None

        with self._engine_lock:
            try:
                self.engine.release()
            except Exception:  # noqa: BLE001
                pass
            if self.meeting_engine is not None:
                try:
                    self.meeting_engine.release()
                except Exception:  # noqa: BLE001
                    pass

        if self.supervisor is not None:
            try:
                self.supervisor.shutdown()
            except Exception:  # noqa: BLE001
                pass

        self._queue_stop_signal()

    def _start_recording(self, mode: RecordingMode = "dictation") -> bool:
        with self._recorder_control_lock:
            with self._recording_lock:
                if self.recorder.is_recording or not self.active:
                    return False
                if self._note_recording_paused:
                    return False

                self._note_pause_reason = None
                self._note_silence_monitor.reset()
                note_start_error: Exception | None = None
                failed_recording_id: int | None = None
                try:
                    self._recording_generation += 1
                    self._active_recording_id = self._recording_generation
                    recording_id = self._active_recording_id
                    with self._engine_lock:
                        engine = self._engine_for_mode_locked(mode)
                        stt = engine.stt
                        note_streaming = mode == "note" and (
                            (self.supervisor is not None and self.supervisor.is_degraded())
                            or stt.backend_name == "faster-whisper"
                        )
                        streaming_enabled = (
                            (mode == "dictation" and bool(stt.capabilities.supports_streaming_chunks))
                            or note_streaming
                        )
                        # Dictation, when streaming-capable, uses the same silence-aligned
                        # overlap accumulator as notes (shorter windows) instead of the
                        # fixed zero-overlap window path, so quality matches a full-utterance
                        # decode without an end-of-clip re-decode.
                        dictation_overlap_stream = mode == "dictation" and streaming_enabled
                        stt_id = id(stt)
                        note_provider = stt.backend_name
                        note_model = getattr(stt, "model_name", "") or ""
                        if self.supervisor is not None and self.supervisor.is_degraded():
                            note_provider = "faster-whisper"
                            note_model = note_model or "base"
                    with self._queue_lock:
                        self._recording_parts[self._active_recording_id] = []
                        self._recording_chunk_counts[self._active_recording_id] = 0
                        self._recording_modes[self._active_recording_id] = mode
                        self._recording_final_chunks.discard(self._active_recording_id)
                        self._recording_stt_ids[self._active_recording_id] = stt_id
                        if streaming_enabled:
                            self._streaming_recordings.add(self._active_recording_id)
                        else:
                            self._streaming_recordings.discard(self._active_recording_id)
                        if mode in {"note", "meeting"}:
                            try:
                                note_id = self.note_store.create_note(
                                    provider=note_provider,
                                    model=note_model,
                                    recording_id=self._active_recording_id,
                                    speaker_labels=mode == "meeting",
                                    mode=mode,
                                )
                            except Exception as exc:  # noqa: BLE001
                                note_start_error = exc
                                failed_recording_id = self._active_recording_id
                            else:
                                self._recording_note_ids[self._active_recording_id] = note_id
                                if note_streaming:
                                    self._recording_prompt_tails[self._active_recording_id] = ""
                                    self._recording_note_chunk_cursors[self._active_recording_id] = (
                                        0,
                                        0.0,
                                    )
                                    self._note_streaming_recordings.add(self._active_recording_id)
                                else:
                                    self._note_streaming_recordings.discard(self._active_recording_id)
                        else:
                            self._note_streaming_recordings.discard(self._active_recording_id)
                            if dictation_overlap_stream:
                                self._recording_prompt_tails[self._active_recording_id] = ""
                        self._terminal_recordings.discard(self._active_recording_id)
                    if note_start_error is None:
                        try:
                            self.recorder.start(
                                on_chunk=self._queue_recording_chunk if streaming_enabled else None,
                                recording_id=self._active_recording_id,
                                note_chunks=note_streaming,
                                overlap_stream=dictation_overlap_stream,
                                on_samples=self._on_recording_samples,
                            )
                        except TypeError:
                            try:
                                # Older recorder that predates ``overlap_stream``: retry
                                # while RETAINING ``note_chunks`` so note streaming is not
                                # silently downgraded to a non-chunked capture.
                                self.recorder.start(
                                    on_chunk=self._queue_recording_chunk if streaming_enabled else None,
                                    recording_id=self._active_recording_id,
                                    note_chunks=note_streaming,
                                    on_samples=self._on_recording_samples,
                                )
                            except TypeError:
                                try:
                                    self.recorder.start(
                                        on_chunk=self._queue_recording_chunk if streaming_enabled else None,
                                        recording_id=self._active_recording_id,
                                        on_samples=self._on_recording_samples,
                                    )
                                except TypeError:
                                    self.recorder.start()
                except (AudioCaptureError, TypeError) as exc:
                    if self._active_recording_id is not None:
                        self._clear_recording_state(self._active_recording_id)
                    self._active_recording_id = None
                    print(f"\r  Microphone error: {exc}", file=sys.stderr)
                    return False
                if note_start_error is not None:
                    if failed_recording_id is not None:
                        self._clear_recording_state(failed_recording_id)
                    self._active_recording_id = None
                    print(f"\r  Note recording failed: {note_start_error}", file=sys.stderr)
                    self._surface_status(f"Note recording failed: {note_start_error}")
                    self._surface_note_terminal(recording_id, "failed")
                    return False

                if mode == "meeting":
                    label = "Meeting recording"
                elif mode == "note":
                    label = "Note recording"
                else:
                    label = "Recording"
                print(f"\r  \033[91m● {label}...\033[0m", end="", file=sys.stderr, flush=True)
                self._notify_recording(True)
                if mode in {"note", "meeting"}:
                    self._notify_note_recording(True, paused=False, mode=mode)
                # Opportunistic recovery probe: if degraded, check whether the remote
                # recovered while we were idle — cheap way to avoid waiting for the
                # next scheduled probe to fire.
                if self.supervisor is not None:
                    self.supervisor.probe_now()
                return True

    def _finalize_recording(self) -> None:
        with self._recorder_control_lock:
            with self._recording_lock:
                recording_id = self._active_recording_id
                mode = self._recording_mode(recording_id) if recording_id is not None else "dictation"
                failed = recording_id is not None and self._is_recording_failed(recording_id)
            if recording_id is None:
                return
            try:
                audio = self.recorder.stop()
            except AudioCaptureError as exc:
                if recording_id is not None:
                    self._fail_recording_session(
                        recording_id,
                        f"Microphone error: {exc}",
                        transcript_reason="capture-error",
                    )
                else:
                    print(f"\r  Microphone error: {exc}", file=sys.stderr)
                self._notify_recording(False)
                if mode in {"note", "meeting"}:
                    self._notify_note_recording(False, paused=False, mode=mode)
                return
            if failed or self._is_recording_failed(recording_id):
                with self._recording_lock:
                    if self._active_recording_id == recording_id:
                        self._active_recording_id = None
                    self._note_recording_paused = False
                    self._clear_recording_state(recording_id)
                self._notify_recording(False)
                if mode in {"note", "meeting"}:
                    self._notify_note_recording(False, paused=False, mode=mode)
                return

            if self._should_queue_stop_audio(recording_id, audio):
                if self._is_unstreamed_recording_truncated(recording_id):
                    self._fail_recording_session(
                        recording_id,
                        "Recording exceeded retained audio limit; final audio incomplete",
                        transcript_reason="truncated-audio",
                    )
                    self._notify_recording(False)
                    if mode in {"note", "meeting"}:
                        self._notify_note_recording(False, paused=False, mode=mode)
                    return
                self._queue_final_chunk(AudioChunk(samples=audio, final=True, sequence=0, recording_id=recording_id))
            elif self._should_queue_final_marker(recording_id):
                self._queue_final_marker(recording_id)
            with self._recording_lock:
                if self._active_recording_id != recording_id or self._is_recording_failed(recording_id):
                    return
                self._active_recording_id = None
                self._note_recording_paused = False
            self._notify_recording(False)
            if mode in {"note", "meeting"}:
                self._notify_note_recording(False, paused=False, mode=mode)

    def _on_hotkey_press(self) -> None:
        try:
            self._start_recording()
        except RuntimeError:
            # Recorder is being stopped; discard this capture cycle.
            pass

    def _on_hotkey_release(self) -> None:
        try:
            self._finalize_recording()
        except RuntimeError:
            pass

    def start(self) -> None:
        """Start daemon threads (non-blocking). Returns immediately."""
        try:
            self.note_store.recover_interrupted()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Note store recovery failed: %s", exc)
        self._ensure_worker_started()
        self._start_hotkey_backend()

    def _ensure_worker_started(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._transcription_loop, daemon=True)
        self._worker.start()

    def _start_hotkey_backend(self) -> None:
        if self._hotkey_backend is None:
            self._hotkey_backend = create_hotkey_backend(
                combo=self.push_to_talk_combo,
                on_press=self._on_hotkey_press,
                on_release=self._on_hotkey_release,
            )
        try:
            self._hotkey_backend.start()
        except HotkeyBackendUnavailableError:
            self._hotkey_backend = None
            raise

    def run(self) -> None:
        """Start daemon and block (for headless mode)."""
        print("dictate daemon running", file=sys.stderr)
        print(
            (
                f"  Hold {format_hotkey_combo(self.push_to_talk_combo)} to dictate, "
                f"release to transcribe ({self.output.name})"
            ),
            file=sys.stderr,
        )
        print("  Ctrl+C to quit\n", file=sys.stderr)

        self.start()

        try:
            self._stop.wait()
        except KeyboardInterrupt:
            print("\nStopping...", file=sys.stderr)
        finally:
            self.shutdown()

    def _transcription_loop(self) -> None:
        while not self._stop.is_set():
            try:
                chunk = self._partial_audio_queue.get_nowait()
            except queue.Empty:
                final_chunk = self._take_next_final_chunk()
                if final_chunk is None:
                    break
                if final_chunk is _FINAL_CHUNK_EMPTY:
                    try:
                        chunk = self._partial_audio_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    self._handle_partial_chunk(chunk)
                    continue
                self._handle_final_chunk(final_chunk)
                continue
            self._handle_partial_chunk(chunk)

    def _take_next_final_chunk(self) -> AudioChunk | None | object:
        try:
            return self._audio_queue.get_nowait()
        except queue.Empty:
            return _FINAL_CHUNK_EMPTY

    def _handle_final_chunk(self, chunk: AudioChunk) -> None:
        audio = chunk.samples
        try:
            if self._is_recording_failed(chunk.recording_id):
                return
            if audio.size > 0:
                min_duration_s = 0.0 if self._assembled_recording_text(chunk.recording_id) else None
                result = self._transcribe_recording_audio(
                    chunk.recording_id,
                    audio,
                    min_duration_s=min_duration_s,
                )
                if result is None:
                    self._fail_recording_session(
                        chunk.recording_id,
                        "Transcription backend changed; recording discarded",
                        transcript_reason="stale-backend",
                    )
                    return
                if result.notice:
                    self._surface_status(result.notice)
                if result.status == "error":
                    self._fail_recording_session(
                        chunk.recording_id,
                        f"Transcription failed: {result.error or 'unknown transcription error'}",
                        transcript_reason="transcription-error",
                    )
                    return
                if result.status == "ok" and result.text:
                    self._record_transcript_piece(chunk.recording_id, result)
                else:
                    self._remember_recording_audio_status(chunk.recording_id, result)
            else:
                result = None
            self._finalize_recording_session(chunk.recording_id, result)
        finally:
            del audio

    def _handle_partial_chunk(self, chunk: AudioChunk) -> None:
        audio = chunk.samples
        if audio.size == 0:
            return
        if self._is_recording_failed(chunk.recording_id):
            return
        mode = self._recording_mode(chunk.recording_id)
        min_duration_s = 0.0 if self._is_note_streaming(chunk.recording_id) else None
        result = self._transcribe_recording_audio(
            chunk.recording_id,
            audio,
            min_duration_s=min_duration_s,
        )
        if result is None:
            self._fail_recording_session(
                chunk.recording_id,
                "Transcription backend changed; recording discarded",
                transcript_reason="stale-backend",
            )
            return
        try:
            if result.notice:
                self._surface_status(result.notice)
            if result.status == "error":
                self._fail_recording_session(
                    chunk.recording_id,
                    f"Transcription failed: {result.error or 'unknown transcription error'}",
                    transcript_reason="transcription-error",
                )
                return
            if result.status == "ok" and result.text:
                piece = result.text.strip()
                if self._is_note_streaming(chunk.recording_id):
                    piece = self._append_note_stream_piece(chunk, piece)
                elif mode == "dictation" and self._recording_uses_streaming(chunk.recording_id):
                    piece = self._append_dictation_stream_piece(chunk, piece)
                if piece:
                    self._record_transcript_piece(
                        chunk.recording_id,
                        TranscriptionResult(status="ok", duration_s=result.duration_s, text=piece),
                    )
                assembled_text = self._assembled_recording_text(chunk.recording_id)
                if assembled_text:
                    self._surface_transcript(
                        phase="partial",
                        text=assembled_text,
                        sequence=chunk.sequence,
                        recording_id=chunk.recording_id,
                        stale=False,
                        mode=mode,
                    )
            else:
                self._remember_recording_audio_status(chunk.recording_id, result)
        finally:
            del audio

    def _handle_result(self, result: TranscriptionResult) -> None:
        self._handle_recording_result(0, result)
        self._recording_parts.pop(0, None)

    def _handle_recording_result(self, recording_id: int, result: TranscriptionResult) -> None:
        try:
            if self._is_recording_failed(recording_id):
                return
            if result.notice:
                self._surface_status(result.notice)

            if result.status == "error":
                message = result.error or "unknown transcription error"
                self._surface_status(f"Transcription failed: {message}")

            if result.status == "ok" and result.text:
                self._record_transcript_piece(recording_id, result)

            assembled_text = self._assembled_recording_text(recording_id)
            if not assembled_text:
                if result.status == "empty":
                    print("\r  No audio captured", file=sys.stderr)
                    return
                if result.status == "too_short":
                    print("\r  Too short, skipped", file=sys.stderr)
                    return
                if result.status == "no_speech":
                    print("\r  No speech detected", file=sys.stderr)
                    return
                if result.status == "error":
                    return
                return
            try:
                self.history_store.append(assembled_text)
            except Exception as exc:  # noqa: BLE001
                print(f"\r  History save failed: {exc}", file=sys.stderr)
            else:
                self._notify_history_changed()

            try:
                self.output.send(assembled_text)
            except Exception as exc:  # noqa: BLE001
                print(f"\r  Output backend failed ({self.output.name}): {exc}", file=sys.stderr)
                return

            self._surface_transcript(
                phase="final",
                text=assembled_text,
                sequence=None,
                recording_id=recording_id,
                stale=False,
            )
            print(f"\r  Typed: {assembled_text}", file=sys.stderr)
        finally:
            self._clear_recording_state(recording_id)

    def _surface_status(self, message: str) -> None:
        print(f"\r  {message}", file=sys.stderr)
        if self.status_callback is None:
            return
        try:
            self.status_callback(message)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Status callback failed: {exc}", file=sys.stderr)

    def _on_recording_samples(self, samples: np.ndarray) -> None:
        self._emit_audio_level(samples)
        self._track_note_silence(samples)

    def _emit_audio_level(self, samples: np.ndarray) -> None:
        if self.audio_level_callback is None:
            return
        now = time.monotonic()
        last = getattr(self, "_last_audio_level_emit", 0.0)
        if now - last < 0.066:
            return
        self._last_audio_level_emit = now
        if samples.size == 0:
            level = 0.0
        else:
            rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
            level = min(1.0, rms * 3.4)
        try:
            self.audio_level_callback(level)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Audio level callback failed: {exc}", file=sys.stderr)

    def _track_note_silence(self, samples: np.ndarray) -> None:
        if self._note_recording_paused or self._note_auto_pause_pending:
            return
        recording_id = self._active_recording_id
        if recording_id is None or self._recording_mode(recording_id) != "note":
            return
        if not self._note_silence_monitor.push(samples):
            return
        self._note_silence_monitor.reset()
        self._schedule_note_auto_pause()

    def _schedule_note_auto_pause(self) -> None:
        if self._note_auto_pause_pending:
            return
        self._note_auto_pause_pending = True
        threading.Thread(target=self._run_note_auto_pause, name="dictate-note-auto-pause", daemon=True).start()

    def _run_note_auto_pause(self) -> None:
        try:
            self.pause_note_recording(pause_reason="silence")
        finally:
            self._note_auto_pause_pending = False

    def _notify_recording(self, recording: bool) -> None:
        if self.recording_callback is None:
            return
        try:
            self.recording_callback(recording)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Recording callback failed: {exc}", file=sys.stderr)

    def _notify_note_recording(
        self,
        recording: bool,
        *,
        paused: bool = False,
        pause_reason: str | None = None,
        mode: RecordingMode | None = None,
        discarded: bool = False,
    ) -> None:
        if self.note_recording_callback is None:
            return
        if mode is None:
            mode = self.long_recording_mode or "note"
        try:
            self.note_recording_callback(
                recording,
                paused=paused,
                pause_reason=pause_reason,
                mode=mode,
                discarded=discarded,
            )
        except TypeError:
            try:
                self.note_recording_callback(recording, paused=paused, pause_reason=pause_reason, mode=mode)
            except TypeError:
                try:
                    self.note_recording_callback(recording, paused=paused, pause_reason=pause_reason)
                except TypeError:
                    try:
                        self.note_recording_callback(recording, paused=paused)
                    except TypeError:
                        self.note_recording_callback(recording)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Note recording callback failed: {exc}", file=sys.stderr)

    def _notify_history_changed(self) -> None:
        if self.history_callback is None:
            return
        try:
            self.history_callback()
        except Exception as exc:  # noqa: BLE001
            print(f"\r  History callback failed: {exc}", file=sys.stderr)

    def _queue_latest_audio(self, audio: np.ndarray) -> None:
        self._queue_partial_audio(
            AudioChunk(samples=audio, final=False, recording_id=self._active_recording_id or 0)
        )

    def _queue_recording_chunk(self, chunk: AudioChunk) -> None:
        with self._queue_lock:
            if chunk.recording_id != 0 and not self._recording_session_known_locked(chunk.recording_id):
                return
            previous_count = self._recording_chunk_counts.get(chunk.recording_id, 0)
            previous_final = chunk.recording_id in self._recording_final_chunks
            self._recording_chunk_counts[chunk.recording_id] = previous_count + 1
            if chunk.final:
                self._recording_final_chunks.add(chunk.recording_id)
        if not self._queue_partial_audio(chunk):
            with self._queue_lock:
                if chunk.recording_id != 0 and not self._recording_session_known_locked(chunk.recording_id):
                    return
                if previous_count == 0:
                    self._recording_chunk_counts.pop(chunk.recording_id, None)
                else:
                    self._recording_chunk_counts[chunk.recording_id] = previous_count
                if chunk.final and not previous_final:
                    self._recording_final_chunks.discard(chunk.recording_id)
        if self._is_note_streaming(chunk.recording_id):
            self._update_note_chunk_cursor(chunk)

    def _queue_partial_audio(self, chunk: AudioChunk) -> bool:
        if chunk.recording_id != 0 and not self._recording_session_known(chunk.recording_id):
            return False
        if chunk.final:
            return self._queue_final_chunk(chunk)
        if self._is_recording_failed(chunk.recording_id):
            return False
        if not self.recorder.is_recording and not self._recording_session_known(chunk.recording_id):
            return False
        try:
            self._partial_audio_queue.put_nowait(chunk)
            return True
        except queue.Full:
            if self._is_note_streaming(chunk.recording_id):
                self._fail_recording_session(
                    chunk.recording_id,
                    "Transcription backlog exceeded; note recording aborted",
                )
                return False
            logger.warning("Transcription backlog for recording %s; dropping oldest partial chunk", chunk.recording_id)
            try:
                self._partial_audio_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._partial_audio_queue.put_nowait(chunk)
                return True
            except queue.Full:
                return False

    def _queue_final_audio(self, audio: np.ndarray) -> None:
        chunk = AudioChunk(
            samples=audio,
            final=True,
            sequence=self._recording_generation,
            recording_id=self._active_recording_id or self._recording_generation,
        )
        self._queue_final_chunk(chunk)

    def _queue_final_chunk(self, chunk: AudioChunk) -> bool:
        if chunk.recording_id != 0 and not self._recording_session_known(chunk.recording_id):
            return False
        try:
            self._audio_queue.put_nowait(chunk)
            return True
        except queue.Full:
            self._fail_recording_session(chunk.recording_id, "Transcription busy; final audio dropped")
            return False

    def _queue_final_marker(self, recording_id: int) -> None:
        self._queue_final_chunk(
            AudioChunk(
                samples=np.array([], dtype=np.float32),
                final=True,
                sequence=self._recording_generation,
                recording_id=recording_id,
            )
        )

    def _queue_stop_signal(self) -> None:
        self._drain_partial_audio_queue()
        try:
            self._audio_queue.put_nowait(None)
        except queue.Full:
            self._drain_final_audio_queue()
            self._audio_queue.put_nowait(None)

    def _drain_partial_audio_queue(self) -> int:
        dropped = 0
        while True:
            try:
                self._partial_audio_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                return dropped

    def _drain_final_audio_queue(self) -> int:
        dropped = 0
        while True:
            try:
                self._audio_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                return dropped

    def _purge_queued_chunks_for_recording(self, recording_id: int) -> None:
        kept_partials: list[AudioChunk] = []
        while True:
            try:
                chunk = self._partial_audio_queue.get_nowait()
            except queue.Empty:
                break
            if chunk.recording_id != recording_id:
                kept_partials.append(chunk)
        for chunk in kept_partials:
            try:
                self._partial_audio_queue.put_nowait(chunk)
            except queue.Full:
                logger.warning("Could not restore partial chunk for recording %s", chunk.recording_id)

        kept_finals: list[object] = []
        while True:
            try:
                item = self._audio_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                kept_finals.append(item)
                continue
            if getattr(item, "recording_id", None) != recording_id:
                kept_finals.append(item)
        for item in kept_finals:
            try:
                self._audio_queue.put_nowait(item)
            except queue.Full:
                rid = getattr(item, "recording_id", None)
                logger.warning("Could not restore final chunk for recording %s", rid)

    def _surface_transcript(
        self,
        *,
        phase: str,
        text: str,
        sequence: int | None,
        recording_id: int | None,
        stale: bool,
        mode: RecordingMode = "dictation",
        reason: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "phase": phase,
            "text": text,
            "stale": stale,
            "mode": mode,
        }
        if sequence is not None:
            payload["sequence"] = sequence
        if recording_id is not None:
            payload["recording_id"] = recording_id
        if reason is not None:
            payload["reason"] = reason
        self._notify_transcript(payload)

    def _surface_note(
        self,
        *,
        text: str,
        raw_text: str,
        recording_id: int,
        segments: list[dict[str, object]] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "text": text,
            "raw_text": raw_text,
            "recording_id": recording_id,
            "status": "ok",
        }
        if segments is not None:
            payload["segments"] = segments
        if self.note_callback is not None:
            try:
                self.note_callback(payload)
            except Exception as exc:  # noqa: BLE001
                print(f"\r  Note callback failed: {exc}", file=sys.stderr)
        self._surface_transcript(
            phase="final",
            text=text,
            sequence=None,
            recording_id=recording_id,
            stale=False,
            mode=self._recording_mode(recording_id),
        )

    def _surface_note_terminal(self, recording_id: int, status: str) -> None:
        """Publish a terminal note signal so the webview can leave "Transcribing…".

        Called on every non-success terminal path for note-mode recordings:
        empty/no-speech (status="empty") and transcription failure (status="failed").
        Reuses the same "note" event channel as the success path; the webview
        distinguishes by the status field.
        """
        if self.note_callback is None:
            return
        try:
            self.note_callback({"text": "", "status": status, "recording_id": recording_id})
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Note terminal callback failed: {exc}", file=sys.stderr)

    def _notify_transcript(self, event: dict[str, object]) -> None:
        if self.transcript_callback is None:
            return
        try:
            self.transcript_callback(event)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Transcript callback failed: {exc}", file=sys.stderr)

    def _record_transcript_piece(self, recording_id: int, result: TranscriptionResult) -> None:
        if result.status != "ok" or not result.text:
            return
        if self._is_recording_failed(recording_id):
            return
        if recording_id != 0 and not self._recording_session_known(recording_id):
            return
        if not self._persist_transcript_segments(recording_id, result):
            return
        with self._queue_lock:
            if recording_id == 0:
                self._recording_parts.setdefault(recording_id, []).append(result.text.strip())
            elif recording_id in self._recording_parts:
                self._recording_parts[recording_id].append(result.text.strip())

    def _persist_transcript_segments(self, recording_id: int, result: TranscriptionResult) -> bool:
        if recording_id == 0 or self._is_note_streaming(recording_id):
            return True
        if self._recording_mode(recording_id) not in {"note", "meeting"}:
            return True
        with self._queue_lock:
            note_id = self._recording_note_ids.get(recording_id)
            seq = self._recording_chunk_counts.get(recording_id, 0)
        if not note_id:
            return True
        provider, model = self._stt_labels(recording_id)
        segments = result.segments or [
            TranscriptSegment(
                text=result.text,
                t_start=0.0,
                t_end=result.duration_s,
            )
        ]
        try:
            for offset, segment in enumerate(segments):
                text = segment.text.strip()
                if not text:
                    continue
                self.note_store.append_segment(
                    note_id,
                    NoteSegment(
                        seq=seq + offset,
                        t_start=segment.t_start if segment.t_start is not None else 0.0,
                        t_end=segment.t_end if segment.t_end is not None else result.duration_s,
                        provider=provider,
                        model=model,
                        text=text,
                        speaker_id=segment.speaker_id,
                        speaker_label=segment.speaker_label,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Could not persist transcript segments for %s", note_id)
            self._fail_recording_session(recording_id, f"Note storage failed: {exc}")
            return False
        return True

    def _remember_recording_audio_status(self, recording_id: int, result: TranscriptionResult) -> None:
        if result.status not in {"too_short", "no_speech"}:
            return
        with self._queue_lock:
            self._recording_last_audio_status[recording_id] = result

    def _assembled_recording_text(self, recording_id: int) -> str:
        with self._queue_lock:
            parts = list(self._recording_parts.get(recording_id, []))
        return " ".join(part for part in (piece.strip() for piece in parts) if part)

    def _finalize_recording_session(
        self,
        recording_id: int,
        final_result: TranscriptionResult | None = None,
    ) -> None:
        if self._is_recording_failed(recording_id):
            self._clear_recording_state(recording_id)
            return
        assembled_text = self._assembled_recording_text(recording_id)
        if not assembled_text:
            # Capture mode before _clear_recording_state pops it from the dict.
            mode = self._recording_mode(recording_id)
            note_id: str | None = None
            with self._queue_lock:
                note_id = self._recording_note_ids.get(recording_id)
            final_result = final_result or self._last_recording_audio_status(recording_id)
            self._clear_recording_state(recording_id)
            self._surface_empty_final_status(final_result)
            if mode in {"note", "meeting"}:
                if note_id:
                    try:
                        self.note_store.mark_failed(note_id, error="empty")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Could not mark note failed: %s", exc)
                # Deterministic terminal signal so the webview can leave "Transcribing…".
                self._surface_note_terminal(recording_id, "empty")
            return

        mode = self._recording_mode(recording_id)
        self._mark_recording_completed(recording_id)
        if mode in {"note", "meeting"}:
            self._finalize_note_session(recording_id, assembled_text)
            self._clear_recording_state(recording_id)
            return
        self._clear_recording_state(recording_id)
        try:
            self.history_store.append(assembled_text)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  History save failed: {exc}", file=sys.stderr)
        else:
            self._notify_history_changed()

        try:
            self.output.send(assembled_text)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Output backend failed ({self.output.name}): {exc}", file=sys.stderr)
            return

        self._surface_transcript(
            phase="final",
            text=assembled_text,
            sequence=None,
            recording_id=recording_id,
            stale=False,
        )
        print(f"\r  Typed: {assembled_text}", file=sys.stderr)

    def _finalize_note_session(self, recording_id: int, raw_text: str) -> None:
        note_id: str | None = None
        segments_payload: list[dict[str, object]] = []
        with self._queue_lock:
            note_id = self._recording_note_ids.pop(recording_id, None)
            self._recording_prompt_tails.pop(recording_id, None)
            self._note_streaming_recordings.discard(recording_id)
        if note_id:
            stored = self.note_store.assembled_text(note_id)
            if stored.strip():
                raw_text = stored
            segments_payload = [
                _note_segment_payload(segment) for segment in self.note_store.load_segments(note_id)
            ]
            try:
                self.note_store.mark_ready(note_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not mark note ready: %s", exc)
                try:
                    self.note_store.mark_failed(note_id, error=f"Could not mark note ready: {exc}")
                except Exception as mark_exc:  # noqa: BLE001
                    logger.warning("Could not mark note failed: %s", mark_exc)
                self._surface_status(f"Note save failed: {exc}")
                self._surface_note_terminal(recording_id, "failed")
                return
        note_text = raw_text.strip()
        if not note_text:
            self._surface_empty_final_status(None)
            # Assembled text was whitespace-only: signal the webview to leave "Transcribing…".
            self._surface_note_terminal(recording_id, "empty")
            return
        try:
            self.history_store.append(note_text)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Note history save failed: {exc}", file=sys.stderr)
        else:
            self._notify_history_changed()
        self._surface_note(
            text=note_text,
            raw_text=raw_text,
            recording_id=recording_id,
            segments=segments_payload,
        )
        print(f"\r  Saved note: {note_text}", file=sys.stderr)

    def _fail_recording_session(
        self,
        recording_id: int,
        reason: str,
        *,
        transcript_reason: str = "dropped-overload",
    ) -> None:
        active_capture = False
        with self._queue_lock:
            if recording_id in self._terminal_recordings:
                return
            # Preserve mode so stop() can still finalize the failed session.
            mode = self._recording_modes.get(recording_id, "dictation")
            note_id = self._recording_note_ids.pop(recording_id, None)
        with self._recording_lock:
            active_capture = self._active_recording_id == recording_id
            recorder_running = self.recorder.is_recording
            if active_capture and mode in {"note", "meeting"}:
                self._note_recording_paused = False
                self._note_pause_reason = None
        with self._queue_lock:
            self._remember_terminal_recording_locked(recording_id)
            self._recording_parts.pop(recording_id, None)
            self._recording_chunk_counts.pop(recording_id, None)
            self._recording_final_chunks.discard(recording_id)
            self._streaming_recordings.discard(recording_id)
            self._recording_last_audio_status.pop(recording_id, None)
            self._recording_prompt_tails.pop(recording_id, None)
            self._note_streaming_recordings.discard(recording_id)
        if note_id:
            try:
                self.note_store.mark_failed(note_id, error=reason)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not mark note failed: %s", exc)
        if not active_capture:
            self._clear_recording_state(recording_id)
        self._surface_status(reason)
        self._surface_transcript(
            phase="final",
            text="",
            sequence=None,
            recording_id=recording_id,
            stale=True,
            reason=transcript_reason,
        )
        should_stop_capture = active_capture and (
            mode in {"note", "meeting"} or transcript_reason in {"capture-error", "truncated-audio"}
        )
        if should_stop_capture:
            self._notify_recording(False)
        if mode in {"note", "meeting"}:
            # Publish a terminal note signal so the webview can leave "Transcribing…".
            self._surface_note_terminal(recording_id, "failed")
        if should_stop_capture and mode in {"note", "meeting"}:
            self._notify_note_recording(False, paused=False, mode=mode)
        if should_stop_capture and recorder_running:
            threading.Thread(
                target=self._cleanup_failed_recording_session,
                args=(recording_id,),
                name=f"dictate-failed-cleanup-{recording_id}",
                daemon=True,
            ).start()
        elif should_stop_capture:
            with self._recording_lock:
                if self._active_recording_id == recording_id:
                    self._active_recording_id = None
                self._note_recording_paused = False
                self._note_pause_reason = None
                self._clear_recording_state(recording_id)

    def _clear_recording_state(self, recording_id: int) -> None:
        with self._queue_lock:
            self._recording_parts.pop(recording_id, None)
            self._recording_chunk_counts.pop(recording_id, None)
            self._recording_final_chunks.discard(recording_id)
            self._streaming_recordings.discard(recording_id)
            self._recording_stt_ids.pop(recording_id, None)
            self._recording_last_audio_status.pop(recording_id, None)
            self._recording_modes.pop(recording_id, None)
            self._recording_note_ids.pop(recording_id, None)
            self._recording_prompt_tails.pop(recording_id, None)
            self._recording_note_chunk_cursors.pop(recording_id, None)
            self._note_streaming_recordings.discard(recording_id)

    def _cleanup_failed_recording_session(self, recording_id: int) -> None:
        with self._recorder_control_lock:
            with self._recording_lock:
                if self._active_recording_id != recording_id:
                    self._clear_recording_state(recording_id)
                    return
            try:
                if self.recorder.is_recording:
                    try:
                        self.recorder.stop()
                    except AudioCaptureError as exc:
                        print(f"\r  Microphone error: {exc}", file=sys.stderr)
            finally:
                with self._recording_lock:
                    if self._active_recording_id == recording_id:
                        self._active_recording_id = None
                    self._note_recording_paused = False
                    self._note_pause_reason = None
                    self._clear_recording_state(recording_id)

    def _mark_recording_completed(self, recording_id: int) -> None:
        with self._queue_lock:
            if recording_id in self._terminal_recordings:
                return
            self._remember_terminal_recording_locked(recording_id)

    def _is_recording_failed(self, recording_id: int) -> bool:
        with self._queue_lock:
            return recording_id in self._terminal_recordings

    def _recording_mode(self, recording_id: int) -> RecordingMode:
        with self._queue_lock:
            return self._recording_modes.get(recording_id, "dictation")

    def _remember_terminal_recording_locked(self, recording_id: int) -> None:
        self._terminal_recordings.add(recording_id)
        self._terminal_recording_order.append(recording_id)
        while len(self._terminal_recording_order) > TERMINAL_RECORDING_CACHE_SIZE:
            expired = self._terminal_recording_order.popleft()
            if expired not in self._terminal_recording_order:
                self._terminal_recordings.discard(expired)

    def _supports_streaming_chunks(self) -> bool:
        return bool(self.engine.stt.capabilities.supports_streaming_chunks)

    def _note_streaming_enabled(self, mode: RecordingMode) -> bool:
        if mode != "note":
            return False
        if self.supervisor is not None and self.supervisor.is_degraded():
            return True
        with self._engine_lock:
            return self.engine.stt.backend_name == "faster-whisper"

    def _is_note_streaming(self, recording_id: int) -> bool:
        with self._queue_lock:
            return recording_id in self._note_streaming_recordings

    def _recording_uses_streaming(self, recording_id: int) -> bool:
        with self._queue_lock:
            return recording_id in self._streaming_recordings

    def _note_chunk_resume_offsets(self, recording_id: int) -> tuple[int, float]:
        with self._queue_lock:
            note_id = self._recording_note_ids.get(recording_id)
            queued_seq, queued_time = self._recording_note_chunk_cursors.get(recording_id, (0, 0.0))
        if not note_id:
            return queued_seq, queued_time
        segments = self.note_store.load_segments(note_id)
        if not segments:
            return queued_seq, queued_time
        return (
            max(max(segment.seq for segment in segments) + 1, queued_seq),
            max(max(segment.t_end for segment in segments), queued_time),
        )

    def _stt_labels(self, recording_id: int | None = None) -> tuple[str, str]:
        with self._engine_lock:
            mode = self._recording_mode(recording_id) if recording_id is not None else "dictation"
            stt = self._engine_for_mode_locked(mode).stt
            provider = stt.backend_name
            model = getattr(stt, "model_name", "") or ""
        if self.supervisor is not None and self.supervisor.is_degraded():
            provider = "faster-whisper"
            model = model or "base"
        return provider, model

    def _append_note_stream_piece(self, chunk: AudioChunk, piece: str) -> str:
        recording_id = chunk.recording_id
        with self._queue_lock:
            tail = self._recording_prompt_tails.get(recording_id, "")
            note_id = self._recording_note_ids.get(recording_id)
        merged = merge_transcript_piece(tail, piece)
        if not merged:
            return ""
        if note_id:
            provider, model = self._stt_labels(recording_id)
            try:
                self.note_store.append_segment(
                    note_id,
                    NoteSegment(
                        seq=chunk.sequence,
                        t_start=chunk.t_start if chunk.t_start is not None else 0.0,
                        t_end=chunk.t_end if chunk.t_end is not None else self.engine.duration_s(chunk.samples),
                        provider=provider,
                        model=model,
                        text=merged,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Could not persist note segment for %s", note_id)
                self._fail_recording_session(recording_id, f"Note storage failed: {exc}")
                return ""
        self._update_note_chunk_cursor(chunk)
        with self._queue_lock:
            combined = f"{tail} {merged}".strip() if tail else merged
            self._recording_prompt_tails[recording_id] = prompt_tail(combined)
        return merged

    def _append_dictation_stream_piece(self, chunk: AudioChunk, piece: str) -> str:
        """Note-store-free sibling of ``_append_note_stream_piece`` for streamed dictation.

        Same overlap merge + prompt-tail threading as the note path, reusing
        the same merge helper, but skips note_store persistence (dictation
        has no note session).
        """
        recording_id = chunk.recording_id
        with self._queue_lock:
            tail = self._recording_prompt_tails.get(recording_id, "")
        merged = merge_transcript_piece(tail, piece)
        if not merged:
            return ""
        with self._queue_lock:
            combined = f"{tail} {merged}".strip() if tail else merged
            self._recording_prompt_tails[recording_id] = prompt_tail(combined)
        return merged

    def _update_note_chunk_cursor(self, chunk: AudioChunk) -> None:
        if not self._is_note_streaming(chunk.recording_id):
            return
        t_end = chunk.t_end if chunk.t_end is not None else self.engine.duration_s(chunk.samples)
        with self._queue_lock:
            previous_seq, previous_time = self._recording_note_chunk_cursors.get(chunk.recording_id, (0, 0.0))
            self._recording_note_chunk_cursors[chunk.recording_id] = (
                max(previous_seq, chunk.sequence + 1),
                max(previous_time, t_end),
            )

    def _transcribe_recording_audio(
        self,
        recording_id: int,
        audio: np.ndarray,
        *,
        min_duration_s: float | None = None,
    ) -> TranscriptionResult | None:
        duration = len(audio) / SAMPLE_RATE
        print(
            f"\r  Transcribing {duration:.1f}s...   ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        with self._engine_lock:
            with self._queue_lock:
                expected_stt_id = self._recording_stt_ids.get(recording_id)
                terminal = recording_id in self._terminal_recordings
            if recording_id != 0 and (terminal or expected_stt_id is None):
                return None
            mode = self._recording_mode(recording_id)
            engine = self._engine_for_mode_locked(mode)
            if expected_stt_id is not None and id(engine.stt) != expected_stt_id:
                return None
            supervisor = self.supervisor

            # Any streaming recording (note or dictation) decodes through the same
            # prompt-threaded chunk path so quality matches a full-utterance decode.
            # Dictation decodes EVERY chunk with long_form=False: cross-chunk continuity
            # comes from the threaded initial_prompt (prompt_tail), not from
            # condition_on_previous_text (which only affects segments within one short
            # 2.5-3.5s chunk and is the anti-hallucination-safe choice OFF). Notes keep
            # long_form=True (unchanged behavior).
            if self._is_note_streaming(recording_id) or self._recording_uses_streaming(recording_id):
                initial_prompt: str | None = None
                with self._queue_lock:
                    tail = self._recording_prompt_tails.get(recording_id, "")
                if tail:
                    initial_prompt = prompt_tail(tail)
                long_form = mode != "dictation"
                # Notes keep the lighter master-tuned decode params (unchanged: note
                # backlog aborts, so a heavier decode risks a hard CPU regression);
                # dictation uses the default quality profile.
                decode_profile = "note" if self._is_note_streaming(recording_id) else "quality"
                return engine.transcribe_stream_chunk(
                    audio,
                    language=self.language,
                    initial_prompt=initial_prompt,
                    long_form=long_form,
                    min_duration_s=min_duration_s,
                    decode_profile=decode_profile,
                )

            # On-device decode params: note recordings keep the lighter master
            # profile even when they fall back to CPU (unchanged note behavior).
            decode_profile = "note" if mode in {"note", "meeting"} else "quality"

            # --- Degraded path: force on-device transcription ---
            # When the supervisor is degraded (remote failed earlier), bypass
            # the remote backend entirely and go straight to the CPU fallback.
            if supervisor is not None and supervisor.is_degraded():
                return self.engine.transcribe_local(
                    audio,
                    language=self.language,
                    min_duration_s=min_duration_s,
                    decode_profile=decode_profile,
                )

            # --- Long recording (note mode): retry remote before degrading ---
            # Note recordings can be many minutes long; we retry the chunk a
            # bounded number of times with backoff before giving up and running
            # locally, so a brief network hiccup does not forfeit the session.
            if mode == "note" and supervisor is not None:
                return self._transcribe_long_recording_with_retry(
                    audio,
                    min_duration_s=min_duration_s,
                    supervisor=supervisor,
                )

            # --- Default path (no supervisor, or streaming chunks in dictation) ---
            # One remote attempt; on failure the engine falls back to CPU and
            # sets result.notice. Meeting is the only mode that asks for speaker
            # attribution; note recordings use the same plain ASR contract as
            # push-to-talk dictation.
            diarize = mode == "meeting"
            return engine.transcribe(
                audio,
                language=self.language,
                min_duration_s=min_duration_s,
                diarize=diarize,
                require_speaker_attribution=mode == "meeting",
                decode_profile=decode_profile,
            )

    def _transcribe_long_recording_with_retry(
        self,
        audio: np.ndarray,
        *,
        min_duration_s: float | None,
        supervisor: ProviderSupervisor,
    ) -> TranscriptionResult:
        """Retry remote transcription for long (note) recordings before degrading.

        On each failure the remote-only transcription raises (instead of falling
        back silently) so we can retry.  If all retries are exhausted we:
        1. Report failure to the supervisor (marks degraded, schedules probe).
        2. Run the audio locally via the CPU fallback.
        3. Return the local result *with* a notice so the UI can surface it.
        """
        last_exc: Exception | None = None
        for attempt in range(_LONG_RECORDING_MAX_RETRIES + 1):
            if attempt > 0:
                delay = _LONG_RECORDING_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                time.sleep(delay)
            try:
                return self.engine.transcribe_remote_only(
                    audio,
                    language=self.language,
                    min_duration_s=min_duration_s,
                    diarize=False,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                # Continue to next retry (supervisor health_sink already updated
                # inside transcribe_remote_only)

        # All retries exhausted — report failure and use local fallback.
        # (health_sink already marked failure; supervisor.report_failure is
        #  idempotent for subsequent calls in the same degraded window.)
        logger.warning(
            "Remote transcription failed after %d retries; using on-device fallback. "
            "Error: %s",
            _LONG_RECORDING_MAX_RETRIES,
            last_exc,
        )
        # Use the normal engine.transcribe() which also includes the CPU fallback
        # and sets result.notice — we pass the original exception context via the
        # engine's existing path. This wrapper is note-only, so keep the "note" profile.
        return self.engine.transcribe(
            audio,
            language=self.language,
            min_duration_s=min_duration_s,
            diarize=False,
            decode_profile="note",
        )

    def _last_recording_audio_status(self, recording_id: int) -> TranscriptionResult | None:
        with self._queue_lock:
            return self._recording_last_audio_status.get(recording_id)

    def _surface_empty_final_status(self, result: TranscriptionResult | None) -> None:
        if result is None or result.status == "empty":
            print("\r  No audio captured", file=sys.stderr)
            return
        if result.status == "too_short":
            print("\r  Too short, skipped", file=sys.stderr)
            return
        if result.status == "no_speech":
            print("\r  No speech detected", file=sys.stderr)
            return
        if result.status == "error":
            self._surface_status(f"Transcription failed: {result.error or 'unknown transcription error'}")
            return

    def _should_queue_stop_audio(self, recording_id: int, audio: np.ndarray) -> bool:
        if audio.size == 0:
            return False
        with self._queue_lock:
            return self._recording_chunk_counts.get(recording_id, 0) == 0

    def _recording_session_known(self, recording_id: int) -> bool:
        with self._queue_lock:
            return self._recording_session_known_locked(recording_id)

    def _recording_session_known_locked(self, recording_id: int) -> bool:
        return (
            recording_id in self._recording_stt_ids
            and recording_id not in self._terminal_recordings
        )

    def _is_unstreamed_recording_truncated(self, recording_id: int) -> bool:
        with self._queue_lock:
            delivered_chunks = self._recording_chunk_counts.get(recording_id, 0)
        return delivered_chunks == 0 and bool(getattr(self.recorder, "truncated", False))

    def _should_queue_final_marker(self, recording_id: int) -> bool:
        with self._queue_lock:
            return (
                recording_id in self._streaming_recordings
                and self._recording_chunk_counts.get(recording_id, 0) > 0
                and recording_id not in self._recording_final_chunks
            )

    def _engine_for_mode_locked(self, mode: RecordingMode) -> DictationEngine:
        if mode == "meeting" and self.meeting_engine is not None:
            return self.meeting_engine
        return self.engine


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_supervisor_health_sink(
    supervisor: ProviderSupervisor,
) -> Callable[[bool, str | None], None]:
    """Return an engine ``health_sink`` that routes results to a supervisor.

    The supervisor tracks degradation/recovery state and fires SSE callbacks.
    We still honour the (healthy: bool, reason: str | None) signature so
    the engine doesn't need to know about the supervisor.
    """
    def _sink(healthy: bool, reason: str | None) -> None:
        if healthy:
            supervisor.report_success()
        else:
            supervisor.report_failure(reason or "unreachable")
    return _sink


def _note_segment_payload(segment: NoteSegment) -> dict[str, object]:
    payload: dict[str, object] = {
        "seq": segment.seq,
        "t_start": segment.t_start,
        "t_end": segment.t_end,
        "provider": segment.provider,
        "model": segment.model,
        "text": segment.text,
    }
    if segment.speaker_id:
        payload["speaker_id"] = segment.speaker_id
    if segment.speaker_label:
        payload["speaker_label"] = segment.speaker_label
    return payload
