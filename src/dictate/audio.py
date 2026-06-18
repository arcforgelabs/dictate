"""Audio capture adapters."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

DEFAULT_MAX_RECORDING_SECONDS = 120
DEFAULT_TRANSCRIPTION_WINDOW_SECONDS = 2.0


class AudioCaptureError(RuntimeError):
    """Raised when audio recording fails."""


@dataclass(slots=True)
class AudioChunk:
    """A bounded audio slice captured from the microphone."""

    samples: np.ndarray
    final: bool = False
    sequence: int = 0
    recording_id: int = 0


class AudioRecorder(Protocol):
    """Minimal audio capture contract for injection into Daemon."""

    @property
    def is_recording(self) -> bool:
        ...

    @property
    def truncated(self) -> bool:
        ...

    def start(
        self,
        on_chunk: Callable[[AudioChunk], None] | None = None,
        recording_id: int | None = None,
    ) -> None:
        ...

    def stop(self) -> np.ndarray:
        ...


class SoundDeviceRecorder:
    """Record mono float32 audio from the default microphone."""

    def __init__(
        self,
        sample_rate: int = 16000,
        max_recording_seconds: int = DEFAULT_MAX_RECORDING_SECONDS,
        transcription_window_seconds: float = DEFAULT_TRANSCRIPTION_WINDOW_SECONDS,
    ):
        self.sample_rate = sample_rate
        self.max_recording_seconds = max(1, int(max_recording_seconds))
        self._max_samples = self.sample_rate * self.max_recording_seconds
        self._window_samples = max(1, int(self.sample_rate * float(transcription_window_seconds)))
        self._lock = threading.Lock()
        self._buffer = np.zeros(self._max_samples, dtype=np.float32)
        self._write_pos = 0
        self._sample_count = 0
        self._truncated = False
        self._chunk_sequence = 0
        self._recording_id = 0
        self._window_buffer = np.zeros(self._window_samples, dtype=np.float32)
        self._window_count = 0
        self._on_chunk: Callable[[AudioChunk], None] | None = None
        self._stream: Any | None = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def truncated(self) -> bool:
        return self._truncated

    def start(
        self,
        on_chunk: Callable[[AudioChunk], None] | None = None,
        recording_id: int | None = None,
    ) -> None:
        """Start recording."""
        if self._recording:
            return

        self._buffer.fill(0)
        self._write_pos = 0
        self._sample_count = 0
        self._truncated = False
        self._chunk_sequence = 0
        self._recording_id = 0 if recording_id is None else int(recording_id)
        self._window_count = 0
        self._on_chunk = on_chunk

        try:
            import sounddevice as sd

            self._stream = sd.InputStream(
                # NOTE: No explicit `device=` means we follow the OS default input device
                # (e.g. the PulseAudio/PipeWire default source on Linux). Future improvement:
                # add a config/CLI option to pin a specific input device by index/name.
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as exc:  # noqa: BLE001
            self._stream = None
            self._recording = False
            raise AudioCaptureError(f"could not start microphone input: {exc}") from exc

        self._recording = True

    def stop(self) -> np.ndarray:
        """Stop recording and return captured audio."""
        if not self._recording:
            return np.array([], dtype=np.float32)

        self._recording = False
        callback = self._on_chunk
        self._on_chunk = None

        tail_chunk: AudioChunk | None = None
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:  # noqa: BLE001
                raise AudioCaptureError(f"could not stop microphone input: {exc}") from exc
            finally:
                self._stream = None

        with self._lock:
            if callback is not None and self._window_count > 0:
                tail = self._window_buffer[: self._window_count].copy()
                tail_chunk = AudioChunk(
                    samples=tail,
                    final=True,
                    sequence=self._chunk_sequence,
                    recording_id=self._recording_id,
                )
                self._chunk_sequence += 1
                self._window_count = 0
            if self._sample_count == 0:
                self._sample_count = 0
                audio = np.array([], dtype=np.float32)
            elif self._sample_count < self._max_samples:
                audio = self._buffer[: self._sample_count].copy()
            else:
                audio = np.concatenate(
                    (
                        self._buffer[self._write_pos :],
                        self._buffer[: self._write_pos],
                    )
                ).astype(np.float32, copy=False)
            self._sample_count = 0
            self._write_pos = 0
        if callback is not None and tail_chunk is not None:
            try:
                callback(tail_chunk)
            except Exception:  # noqa: BLE001
                pass
        return audio

    def record_until(
        self,
        should_stop: Callable[[], bool],
        poll_interval: float = 0.05,
    ) -> np.ndarray:
        """Record until `should_stop()` returns True."""
        self.start()
        try:
            while not should_stop():
                time.sleep(poll_interval)
        finally:
            pass
        return self.stop()

    def _audio_callback(self, indata, frames, time_info, status):  # noqa: ANN001
        del frames, time_info
        if status:
            # Non-fatal audio status flags are surfaced by sounddevice here.
            pass
        callback: Callable[[AudioChunk], None] | None
        chunk_events: list[AudioChunk] = []
        samples = np.asarray(indata, dtype=np.float32).reshape(-1)
        if samples.size == 0:
            return
        with self._lock:
            self._write_capture(samples)
            self._append_window_samples(samples, chunk_events)
            callback = self._on_chunk
        if callback is not None:
            for chunk_event in chunk_events:
                try:
                    callback(chunk_event)
                except Exception:  # noqa: BLE001
                    pass

    def _write_capture(self, samples: np.ndarray) -> None:
        previous_sample_count = self._sample_count
        if samples.size > self._max_samples:
            self._buffer[:] = samples[-self._max_samples :]
            self._write_pos = 0
            self._sample_count = self._max_samples
            self._truncated = True
            return

        self._write_chunk(samples)
        self._sample_count = min(self._max_samples, self._sample_count + len(samples))
        if previous_sample_count + len(samples) > self._max_samples:
            self._truncated = True

    def _append_window_samples(self, samples: np.ndarray, chunk_events: list[AudioChunk]) -> None:
        if self._on_chunk is None:
            return
        offset = 0
        while offset < len(samples):
            if self._window_count == self._window_samples:
                self._emit_window_chunk(chunk_events, final=False)
            needed = self._window_samples - self._window_count
            take = min(needed, len(samples) - offset)
            end = offset + take
            self._window_buffer[self._window_count : self._window_count + take] = samples[offset:end]
            self._window_count += take
            offset = end
            if self._window_count == self._window_samples:
                self._emit_window_chunk(chunk_events, final=False)

    def _emit_window_chunk(self, chunk_events: list[AudioChunk], *, final: bool) -> None:
        if self._window_count == 0:
            return
        chunk_events.append(
            AudioChunk(
                samples=self._window_buffer[: self._window_count].copy(),
                final=final,
                sequence=self._chunk_sequence,
                recording_id=self._recording_id,
            )
        )
        self._chunk_sequence += 1
        self._window_count = 0

    def _write_chunk(self, chunk: np.ndarray) -> None:
        """Copy a chunk into the bounded ring buffer."""
        end = self._write_pos + len(chunk)
        if end <= self._max_samples:
            self._buffer[self._write_pos:end] = chunk
        else:
            first = self._max_samples - self._write_pos
            self._buffer[self._write_pos:] = chunk[:first]
            self._buffer[: end % self._max_samples] = chunk[first:]
        self._write_pos = end % self._max_samples
