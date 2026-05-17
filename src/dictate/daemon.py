"""Push-to-talk daemon. Listens for a configured combo and runs shared dictation pipeline."""

from __future__ import annotations

import queue
import sys
import threading
from collections.abc import Callable

import numpy as np

from dictate.audio import AudioCaptureError, AudioRecorder, SoundDeviceRecorder
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
        recorder: AudioRecorder | None = None,
    ):
        self.active = True
        self.language = language
        self.output = output
        self.history_store = history_store or HistoryStore()
        self.status_callback = status_callback
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
        self._audio_queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._hotkey_backend: HotkeyBackend | None = None

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
                self.recorder.start()
            except AudioCaptureError as exc:
                print(f"\r  Microphone error: {exc}", file=sys.stderr)
                return

            print("\r  \033[91m● Recording...\033[0m", end="", file=sys.stderr, flush=True)

    def _finalize_recording(self) -> None:
        with self._recording_lock:
            try:
                audio = self.recorder.stop()
            except AudioCaptureError as exc:
                print(f"\r  Microphone error: {exc}", file=sys.stderr)
                return

            if audio.size > 0:
                self._queue_latest_audio(audio)

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
            audio = self._audio_queue.get()
            if audio is None:
                break

            duration = len(audio) / SAMPLE_RATE
            print(
                f"\r  Transcribing {duration:.1f}s...   ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            with self._engine_lock:
                result = self.engine.transcribe(audio, language=self.language)
            self._handle_result(result)

    def _handle_result(self, result: TranscriptionResult) -> None:
        if result.notice:
            self._surface_status(result.notice)

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
            message = result.error or "unknown transcription error"
            self._surface_status(f"Transcription failed: {message}")
            return

        try:
            self.history_store.append(result.text)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  History save failed: {exc}", file=sys.stderr)

        try:
            self.output.send(result.text)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Output backend failed ({self.output.name}): {exc}", file=sys.stderr)
            return

        print(f"\r  Typed: {result.text}", file=sys.stderr)

    def _surface_status(self, message: str) -> None:
        print(f"\r  {message}", file=sys.stderr)
        if self.status_callback is None:
            return
        try:
            self.status_callback(message)
        except Exception as exc:  # noqa: BLE001
            print(f"\r  Status callback failed: {exc}", file=sys.stderr)

    def _queue_latest_audio(self, audio: np.ndarray) -> None:
        self._audio_queue.put_nowait(audio)

    def _queue_stop_signal(self) -> None:
        self._drain_pending_audio_queue()
        self._audio_queue.put_nowait(None)

    def _drain_pending_audio_queue(self) -> None:
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                return
