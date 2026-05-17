"""Audio capture adapters."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np


class AudioCaptureError(RuntimeError):
    """Raised when audio recording fails."""


class AudioRecorder(Protocol):
    """Minimal audio capture contract for injection into Daemon."""

    @property
    def is_recording(self) -> bool:
        ...

    def start(self) -> None:
        ...

    def stop(self) -> np.ndarray:
        ...


class SoundDeviceRecorder:
    """Record mono float32 audio from the default microphone."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._stream: Any | None = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        """Start recording."""
        if self._recording:
            return

        self._chunks = []

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

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:  # noqa: BLE001
                raise AudioCaptureError(f"could not stop microphone input: {exc}") from exc
            finally:
                self._stream = None

        with self._lock:
            if not self._chunks:
                return np.array([], dtype=np.float32)
            audio = np.concatenate(self._chunks).flatten().astype(np.float32, copy=False)
            self._chunks = []
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
        if status:
            # Non-fatal audio status flags are surfaced by sounddevice here.
            pass
        with self._lock:
            self._chunks.append(indata.copy())
