"""Audio capture adapters."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

DEFAULT_MAX_RECORDING_SECONDS = 120


class AudioCaptureError(RuntimeError):
    """Raised when audio recording fails."""


@dataclass(slots=True)
class AudioChunk:
    """A bounded audio slice captured from the microphone."""

    samples: np.ndarray
    final: bool = False
    sequence: int = 0


class AudioRecorder(Protocol):
    """Minimal audio capture contract for injection into Daemon."""

    @property
    def is_recording(self) -> bool:
        ...

    def start(self, on_chunk: Callable[[AudioChunk], None] | None = None) -> None:
        ...

    def stop(self) -> np.ndarray:
        ...


class SoundDeviceRecorder:
    """Record mono float32 audio from the default microphone."""

    def __init__(
        self,
        sample_rate: int = 16000,
        max_recording_seconds: int = DEFAULT_MAX_RECORDING_SECONDS,
    ):
        self.sample_rate = sample_rate
        self.max_recording_seconds = max(1, int(max_recording_seconds))
        self._max_samples = self.sample_rate * self.max_recording_seconds
        self._lock = threading.Lock()
        self._buffer = np.zeros(self._max_samples, dtype=np.float32)
        self._write_pos = 0
        self._sample_count = 0
        self._truncated = False
        self._chunk_sequence = 0
        self._on_chunk: Callable[[AudioChunk], None] | None = None
        self._stream: Any | None = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self, on_chunk: Callable[[AudioChunk], None] | None = None) -> None:
        """Start recording."""
        if self._recording:
            return

        self._buffer.fill(0)
        self._write_pos = 0
        self._sample_count = 0
        self._truncated = False
        self._chunk_sequence = 0
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
        self._on_chunk = None

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:  # noqa: BLE001
                raise AudioCaptureError(f"could not stop microphone input: {exc}") from exc
            finally:
                self._stream = None

        with self._lock:
            if self._sample_count == 0:
                self._sample_count = 0
                return np.array([], dtype=np.float32)
            if self._sample_count < self._max_samples:
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
        with self._lock:
            remaining = self._max_samples - self._sample_count
            if remaining <= 0:
                self._truncated = True
                return
            chunk = np.asarray(indata[:remaining], dtype=np.float32).reshape(-1).copy()
            if chunk.size == 0:
                return
            self._write_chunk(chunk)
            self._sample_count += len(chunk)
            if len(chunk) < len(indata):
                self._truncated = True
            callback = self._on_chunk
            if callback is not None:
                chunk_event = AudioChunk(samples=chunk.copy(), final=False, sequence=self._chunk_sequence)
                self._chunk_sequence += 1
            else:
                chunk_event = None
        if callback is not None and chunk_event is not None:
            try:
                callback(chunk_event)
            except Exception:  # noqa: BLE001
                pass

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
