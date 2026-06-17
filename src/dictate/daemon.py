"""Push-to-talk daemon. Listens for a configured combo and runs shared dictation pipeline."""

from __future__ import annotations

import queue
import sys
import threading
from collections import deque
from collections.abc import Callable

import numpy as np

from dictate.audio import AudioCaptureError, AudioChunk, AudioRecorder, SoundDeviceRecorder
from dictate.engine import DictationEngine, TranscriptionResult
from dictate.history import HistoryStore
from dictate.hotkey import format_hotkey_combo, normalize_push_to_talk_combo
from dictate.hotkey_backend import (
    HotkeyBackend,
    HotkeyBackendUnavailableError,
    create_hotkey_backend,
)
from dictate.lexicon import LexiconMode
from dictate.outputs import TextOutput
from dictate.stt import SpeechToText

SAMPLE_RATE = 16000
FINAL_AUDIO_QUEUE_SIZE = 4
FINAL_WINDOW_QUEUE_SIZE = 64
TERMINAL_RECORDING_CACHE_SIZE = FINAL_AUDIO_QUEUE_SIZE + FINAL_WINDOW_QUEUE_SIZE
_FINAL_CHUNK_EMPTY = object()


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
        push_to_talk_combo: str = "ctrl_r",
        status_callback: Callable[[str | None], None] | None = None,
        recording_callback: Callable[[bool], None] | None = None,
        history_callback: Callable[[], None] | None = None,
        transcript_callback: Callable[[dict[str, object]], None] | None = None,
        recorder: AudioRecorder | None = None,
    ):
        self.active = True
        self.language = language
        self.output = output
        self.history_store = history_store or HistoryStore()
        self.status_callback = status_callback
        self.recording_callback = recording_callback
        self.history_callback = history_callback
        self.transcript_callback = transcript_callback
        self.push_to_talk_combo = normalize_push_to_talk_combo(push_to_talk_combo)
        self.engine = DictationEngine(
            stt=stt,
            sample_rate=SAMPLE_RATE,
            hotwords=hotwords,
            lexicon_mode=lexicon_mode,
            lexicon_replacements=lexicon_replacements,
        )
        self.recorder = recorder or SoundDeviceRecorder(sample_rate=SAMPLE_RATE)
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
        self._terminal_recordings: set[int] = set()
        self._terminal_recording_order: deque[int] = deque()
        self._active_recording_id: int | None = None
        self._queue_lock = threading.Lock()

    def pause(self) -> None:
        """Stop listening for hotkey."""
        self.active = False
        with self._recording_lock:
            if self.recorder.is_recording:
                self._finalize_recording()

    def resume(self) -> None:
        """Resume listening for hotkey."""
        self.active = True

    def set_hotwords(self, hotwords: str | None) -> None:
        """Update hotwords without restarting daemon."""
        with self._engine_lock:
            self.engine.set_hotwords(hotwords)

    def clear_active_api_key(self, backend: str) -> None:
        """Remove a hosted backend key from the currently loaded STT object."""
        with self._engine_lock:
            stt = self.engine.stt
            if stt.backend_name == backend and hasattr(stt, "api_key"):
                setattr(stt, "api_key", "")

    def set_push_to_talk_combo(self, combo: str) -> None:
        """Update push-to-talk combo without restarting daemon."""
        self.push_to_talk_combo = normalize_push_to_talk_combo(combo)
        if self._hotkey_backend is not None:
            self._hotkey_backend.set_combo(self.push_to_talk_combo)
        else:
            self._ensure_worker_started()
            self._start_hotkey_backend()
        if self.recorder.is_recording:
            with self._recording_lock:
                if self.recorder.is_recording:
                    self._finalize_recording()

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

    def current_backend_model(self) -> tuple[str, str]:
        """Return active backend/model selection."""
        with self._engine_lock:
            return (self.engine.stt.backend_name, self.engine.stt.model_name)

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

        with self._recording_lock:
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

        self._queue_stop_signal()

    def _start_recording(self) -> None:
        with self._recording_lock:
            if self.recorder.is_recording or not self.active:
                return

            try:
                self._recording_generation += 1
                self._active_recording_id = self._recording_generation
                streaming_enabled = self._supports_streaming_chunks()
                with self._queue_lock:
                    self._recording_parts[self._active_recording_id] = []
                    self._recording_chunk_counts[self._active_recording_id] = 0
                    self._recording_final_chunks.discard(self._active_recording_id)
                    if streaming_enabled:
                        self._streaming_recordings.add(self._active_recording_id)
                    else:
                        self._streaming_recordings.discard(self._active_recording_id)
                    self._terminal_recordings.discard(self._active_recording_id)
                self.recorder.start(
                    on_chunk=self._queue_recording_chunk if streaming_enabled else None,
                    recording_id=self._active_recording_id,
                )
            except AudioCaptureError as exc:
                if self._active_recording_id is not None:
                    self._clear_recording_state(self._active_recording_id)
                self._active_recording_id = None
                print(f"\r  Microphone error: {exc}", file=sys.stderr)
                return

            print("\r  \033[91m● Recording...\033[0m", end="", file=sys.stderr, flush=True)
            self._notify_recording(True)

    def _finalize_recording(self) -> None:
        with self._recording_lock:
            recording_id = self._active_recording_id
            try:
                audio = self.recorder.stop()
            except AudioCaptureError as exc:
                self._active_recording_id = None
                print(f"\r  Microphone error: {exc}", file=sys.stderr)
                self._notify_recording(False)
                return

            if recording_id is not None:
                if self._should_queue_stop_audio(recording_id, audio):
                    self._queue_final_chunk(
                        AudioChunk(samples=audio, final=True, sequence=0, recording_id=recording_id)
                    )
                elif self._should_queue_final_marker(recording_id):
                    self._queue_final_marker(recording_id)
                self._active_recording_id = None
            self._notify_recording(False)

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
                duration = len(audio) / SAMPLE_RATE
                print(
                    f"\r  Transcribing {duration:.1f}s...   ",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )
                with self._engine_lock:
                    result = self.engine.transcribe(audio, language=self.language)
                if result.status == "ok" and result.text:
                    self._record_transcript_piece(chunk.recording_id, result)
            self._finalize_recording_session(chunk.recording_id)
        finally:
            del audio

    def _handle_partial_chunk(self, chunk: AudioChunk) -> None:
        audio = chunk.samples
        if audio.size == 0:
            return
        if self._is_recording_failed(chunk.recording_id):
            return
        duration = len(audio) / SAMPLE_RATE
        print(
            f"\r  Transcribing {duration:.1f}s...   ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        try:
            with self._engine_lock:
                result = self.engine.transcribe(audio, language=self.language)
            if result.status == "ok" and result.text:
                self._record_transcript_piece(chunk.recording_id, result)
                assembled_text = self._assembled_recording_text(chunk.recording_id)
                if assembled_text:
                    self._surface_transcript(
                        phase="partial",
                        text=assembled_text,
                        sequence=chunk.sequence,
                        recording_id=chunk.recording_id,
                        stale=False,
                    )
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

    def _notify_recording(self, recording: bool) -> None:
        if self.recording_callback is None:
            return
        try:
            self.recording_callback(recording)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Recording callback failed: {exc}", file=sys.stderr)

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
            self._recording_chunk_counts[chunk.recording_id] = (
                self._recording_chunk_counts.get(chunk.recording_id, 0) + 1
            )
            if chunk.final:
                self._recording_final_chunks.add(chunk.recording_id)
        self._queue_partial_audio(chunk)

    def _queue_partial_audio(self, chunk: AudioChunk) -> None:
        if chunk.final:
            self._queue_final_chunk(chunk)
            return
        if not self.recorder.is_recording:
            return
        if self._is_recording_failed(chunk.recording_id):
            return
        try:
            self._partial_audio_queue.put_nowait(chunk)
        except queue.Full:
            self._fail_recording_session(chunk.recording_id, "Transcription backlog exceeded")

    def _queue_final_audio(self, audio: np.ndarray) -> None:
        chunk = AudioChunk(
            samples=audio,
            final=True,
            sequence=self._recording_generation,
            recording_id=self._active_recording_id or self._recording_generation,
        )
        self._queue_final_chunk(chunk)

    def _queue_final_chunk(self, chunk: AudioChunk) -> None:
        try:
            self._audio_queue.put_nowait(chunk)
        except queue.Full:
            self._fail_recording_session(chunk.recording_id, "Transcription busy; final audio dropped")

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

    def _surface_transcript(
        self,
        *,
        phase: str,
        text: str,
        sequence: int | None,
        recording_id: int | None,
        stale: bool,
        reason: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "phase": phase,
            "text": text,
            "stale": stale,
        }
        if sequence is not None:
            payload["sequence"] = sequence
        if recording_id is not None:
            payload["recording_id"] = recording_id
        if reason is not None:
            payload["reason"] = reason
        self._notify_transcript(payload)

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
        with self._queue_lock:
            self._recording_parts.setdefault(recording_id, []).append(result.text.strip())

    def _assembled_recording_text(self, recording_id: int) -> str:
        with self._queue_lock:
            parts = list(self._recording_parts.get(recording_id, []))
        return " ".join(part for part in (piece.strip() for piece in parts) if part)

    def _finalize_recording_session(self, recording_id: int) -> None:
        if self._is_recording_failed(recording_id):
            self._clear_recording_state(recording_id)
            return
        assembled_text = self._assembled_recording_text(recording_id)
        if not assembled_text:
            self._clear_recording_state(recording_id)
            print("\r  No audio captured", file=sys.stderr)
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

    def _fail_recording_session(self, recording_id: int, reason: str) -> None:
        with self._queue_lock:
            if recording_id in self._terminal_recordings:
                return
            self._remember_terminal_recording_locked(recording_id)
            self._recording_parts.pop(recording_id, None)
            self._recording_chunk_counts.pop(recording_id, None)
            self._recording_final_chunks.discard(recording_id)
            self._streaming_recordings.discard(recording_id)
        if self._active_recording_id == recording_id:
            self._active_recording_id = None
        self._surface_status(reason)
        self._surface_transcript(
            phase="final",
            text="",
            sequence=None,
            recording_id=recording_id,
            stale=True,
            reason="dropped-overload",
        )

    def _clear_recording_state(self, recording_id: int) -> None:
        with self._queue_lock:
            self._recording_parts.pop(recording_id, None)
            self._recording_chunk_counts.pop(recording_id, None)
            self._recording_final_chunks.discard(recording_id)
            self._streaming_recordings.discard(recording_id)

    def _is_recording_failed(self, recording_id: int) -> bool:
        with self._queue_lock:
            return recording_id in self._terminal_recordings

    def _remember_terminal_recording_locked(self, recording_id: int) -> None:
        self._terminal_recordings.add(recording_id)
        self._terminal_recording_order.append(recording_id)
        while len(self._terminal_recording_order) > TERMINAL_RECORDING_CACHE_SIZE:
            expired = self._terminal_recording_order.popleft()
            if expired not in self._terminal_recording_order:
                self._terminal_recordings.discard(expired)

    def _supports_streaming_chunks(self) -> bool:
        return bool(self.engine.stt.capabilities.supports_streaming_chunks)

    def _should_queue_stop_audio(self, recording_id: int, audio: np.ndarray) -> bool:
        if audio.size == 0:
            return False
        with self._queue_lock:
            return self._recording_chunk_counts.get(recording_id, 0) == 0

    def _should_queue_final_marker(self, recording_id: int) -> bool:
        with self._queue_lock:
            return (
                recording_id in self._streaming_recordings
                and self._recording_chunk_counts.get(recording_id, 0) > 0
                and recording_id not in self._recording_final_chunks
            )
