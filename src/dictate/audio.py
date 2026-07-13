"""Audio capture adapters."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol

import numpy as np

from dictate.audio_preprocess import AudioPreprocessor, create_preprocessor
from dictate.note_chunker import NoteChunkAccumulator

DEFAULT_MAX_RECORDING_SECONDS = 120
DEFAULT_TRANSCRIPTION_WINDOW_SECONDS = 2.0
DEFAULT_SAMPLE_RATE = 16000

# Soft ALSA/PipeWire PCMs that typically resample; prefer these over raw hw:*
# devices. Defense in depth when PortAudio defaults to a hw capture node that
# rejects 16 kHz (ALSA-only builds / some PipeWire setups).
_PREFERRED_INPUT_NAMES = (
    "sysdefault",
    "default",
    "pulse",
    "pipewire",
    "default source",
)
_FALLBACK_CAPTURE_RATES = (48000, 44100, 32000, 22050)

# Overlap-stream (dictation) chunking: shorter windows than notes so perceived
# latency stays close to "release key -> last chunk decodes", with enough
# overlap for prompt-tail threading/merge to dedup the seam.
DICTATION_MIN_CHUNK_SECONDS = 2.5
DICTATION_MAX_CHUNK_SECONDS = 3.5
DICTATION_OVERLAP_SECONDS = 1.0


class AudioCaptureError(RuntimeError):
    """Raised when audio recording fails."""


def resample_audio(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linearly resample mono float audio between sample rates."""
    if src_rate <= 0 or dst_rate <= 0:
        raise ValueError(f"Invalid sample rate: src={src_rate} dst={dst_rate}")
    if audio.size == 0 or src_rate == dst_rate:
        return np.asarray(audio, dtype=np.float32)
    src_duration = audio.size / float(src_rate)
    target_size = max(1, int(round(src_duration * dst_rate)))
    src_x = np.linspace(0.0, src_duration, num=audio.size, endpoint=False)
    tgt_x = np.linspace(0.0, src_duration, num=target_size, endpoint=False)
    return np.interp(tgt_x, src_x, audio).astype(np.float32, copy=False)


def _default_input_device(sd: Any) -> int | None:
    pair = getattr(sd, "default", None)
    device = getattr(pair, "device", None) if pair is not None else None
    if isinstance(device, (list, tuple)):
        index = device[0] if device else None
    else:
        index = device
    try:
        value = int(index)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _pulse_default_input(sd: Any) -> int | None:
    """Prefer the PulseAudio/PipeWire host API default when PortAudio has one."""
    try:
        hostapis = sd.query_hostapis()
    except Exception:  # noqa: BLE001
        return None
    for api in hostapis:
        try:
            name = str(api.get("name", "")).lower()
            if "pulse" not in name:
                continue
            index = int(api.get("default_input_device", -1))
        except Exception:  # noqa: BLE001
            continue
        if index >= 0:
            return index
    return None


def _input_device_candidates(sd: Any) -> list[int]:
    """Prefer Pulse default, then PortAudio default, then soft PCMs."""
    seen: set[int] = set()
    candidates: list[int] = []

    def add(index: int | None) -> None:
        if index is None or index < 0 or index in seen:
            return
        seen.add(index)
        candidates.append(index)

    add(_pulse_default_input(sd))
    add(_default_input_device(sd))
    try:
        devices = sd.query_devices()
    except Exception:  # noqa: BLE001
        return candidates
    for index, device in enumerate(devices):
        try:
            if int(device.get("max_input_channels", 0)) <= 0:
                continue
            name = str(device.get("name", "")).lower()
        except Exception:  # noqa: BLE001
            continue
        if any(token in name for token in _PREFERRED_INPUT_NAMES):
            add(index)
    return candidates


def _device_supports_input(
    sd: Any,
    *,
    device: int,
    samplerate: int,
    channels: int = 1,
) -> bool:
    try:
        sd.check_input_settings(
            device=device,
            channels=channels,
            dtype="float32",
            samplerate=samplerate,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _native_samplerate(sd: Any, device: int) -> int | None:
    try:
        info = sd.query_devices(device)
        rate = int(round(float(info.get("default_samplerate") or 0)))
    except Exception:  # noqa: BLE001
        return None
    return rate if rate > 0 else None


def resolve_input_capture(
    sd: Any,
    *,
    target_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = 1,
) -> tuple[int, int]:
    """Pick an input device and capture rate that PortAudio can open.

    Prefers ``target_rate`` (16 kHz for STT). When the default hw device rejects
    that rate — common with ALSA-only PortAudio builds on PipeWire — falls back
    to a soft PCM (``sysdefault`` / ``pulse`` / …) or captures at a native rate
    for later resampling.
    """
    candidates = _input_device_candidates(sd)
    if not candidates:
        raise AudioCaptureError("no microphone input devices detected")

    for device in candidates:
        if _device_supports_input(
            sd, device=device, samplerate=target_rate, channels=channels
        ):
            return device, target_rate

    for device in candidates:
        rates: list[int] = []
        native = _native_samplerate(sd, device)
        if native is not None:
            rates.append(native)
        for rate in _FALLBACK_CAPTURE_RATES:
            if rate not in rates:
                rates.append(rate)
        for rate in rates:
            if _device_supports_input(
                sd, device=device, samplerate=rate, channels=channels
            ):
                return device, rate

    raise AudioCaptureError(
        f"no microphone input device supports capture near {target_rate} Hz"
    )

@dataclass(slots=True)
class AudioChunk:
    """A bounded audio slice captured from the microphone."""

    samples: np.ndarray
    final: bool = False
    sequence: int = 0
    recording_id: int = 0
    t_start: float | None = None
    t_end: float | None = None
    # True only on the last chunk emitted by an accumulator's terminal flush
    # (note or dictation overlap-streaming). Distinct from ``final`` (queue
    # routing) so streamed sessions keep flowing through the merge/prompt-tail
    # path; consumers use this to pick decode params (e.g. long_form) for the
    # true last piece of real audio without changing queue behavior.
    stream_final: bool = False


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
        sample_rate: int = DEFAULT_SAMPLE_RATE,
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
        self._on_samples: Callable[[np.ndarray], None] | None = None
        self._stream: Any | None = None
        self._recording = False
        self._note_chunks = False
        self._overlap_stream = False
        self._note_accumulator: NoteChunkAccumulator | None = None
        self._preprocessor: AudioPreprocessor | None = None
        # Capture may open at a device-native rate; samples are resampled to
        # ``sample_rate`` before preprocessing / STT.
        self._capture_rate = sample_rate
        self._capture_device: int | None = None

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
        *,
        note_chunks: bool = False,
        overlap_stream: bool = False,
        note_chunk_seq_offset: int = 0,
        note_time_offset_s: float = 0.0,
        on_samples: Callable[[np.ndarray], None] | None = None,
    ) -> None:
        """Start recording.

        ``note_chunks`` and ``overlap_stream`` both drive silence-aligned,
        overlapping chunk emission via ``NoteChunkAccumulator`` instead of the
        fixed zero-overlap window path; they use different chunk-size params
        (notes: longer windows; dictation overlap-stream: shorter windows for
        lower perceived latency) and are mutually exclusive per session.
        """
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
        self._on_samples = on_samples
        self._note_chunks = bool(note_chunks)
        self._overlap_stream = bool(overlap_stream) and not self._note_chunks
        if self._note_chunks:
            self._note_accumulator = NoteChunkAccumulator(
                sample_rate=self.sample_rate,
                seq_offset=note_chunk_seq_offset,
                time_offset_s=note_time_offset_s,
            )
        elif self._overlap_stream:
            self._note_accumulator = NoteChunkAccumulator(
                sample_rate=self.sample_rate,
                min_chunk_seconds=DICTATION_MIN_CHUNK_SECONDS,
                max_chunk_seconds=DICTATION_MAX_CHUNK_SECONDS,
                overlap_seconds=DICTATION_OVERLAP_SECONDS,
                seq_offset=note_chunk_seq_offset,
                time_offset_s=note_time_offset_s,
            )
        else:
            self._note_accumulator = None
        # AGC + noise suppression on the live stream (None if disabled/unavailable).
        self._preprocessor = create_preprocessor(self.sample_rate)

        try:
            import sounddevice as sd

            device, capture_rate = resolve_input_capture(sd, target_rate=self.sample_rate)
            self._capture_device = device
            self._capture_rate = capture_rate
            self._stream = sd.InputStream(
                # Explicit device from resolve_input_capture (Pulse/sysdefault/
                # native-rate fallback). Avoid relying on PortAudio's default,
                # which can be a raw hw:* node that rejects 16 kHz.
                device=device,
                samplerate=capture_rate,
                channels=1,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()
        except AudioCaptureError:
            self._stream = None
            self._recording = False
            self._capture_rate = self.sample_rate
            self._capture_device = None
            raise
        except Exception as exc:  # noqa: BLE001
            self._stream = None
            self._recording = False
            self._capture_rate = self.sample_rate
            self._capture_device = None
            raise AudioCaptureError(f"could not start microphone input: {exc}") from exc

        self._recording = True

    def stop(self) -> np.ndarray:
        """Stop recording and return captured audio."""
        if not self._recording:
            return np.array([], dtype=np.float32)

        self._recording = False

        tail_chunk: AudioChunk | None = None
        chunk_events: list[AudioChunk] = []
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:  # noqa: BLE001
                raise AudioCaptureError(f"could not stop microphone input: {exc}") from exc
            finally:
                self._stream = None

        with self._lock:
            callback = self._on_chunk
            self._on_chunk = None
            self._on_samples = None
            if self._preprocessor is not None:
                # Drain the ~10 ms the preprocessor was still buffering so the tail
                # of the utterance is not lost, then feed it through the same path.
                tail = self._preprocessor.flush()
                self._preprocessor = None
                if tail.size:
                    if not (self._note_chunks or self._overlap_stream):
                        self._write_capture(tail)
                    self._append_stream_samples(tail, chunk_events)
            if self._note_accumulator is not None:
                flushed = self._note_accumulator.flush(final=True)
                last_index = len(flushed) - 1
                for index, emitted in enumerate(flushed):
                    chunk_events.append(
                        AudioChunk(
                            samples=emitted.samples,
                            final=False,
                            sequence=emitted.sequence,
                            recording_id=self._recording_id,
                            t_start=emitted.t_start,
                            t_end=emitted.t_end,
                            stream_final=index == last_index,
                        )
                    )
                self._note_accumulator = None
            elif callback is not None and self._window_count > 0:
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
            elif self._note_chunks or self._overlap_stream:
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
        if callback is not None:
            for chunk_event in chunk_events:
                try:
                    callback(chunk_event)
                except Exception:  # noqa: BLE001
                    pass
            if tail_chunk is not None:
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
        if self._capture_rate != self.sample_rate:
            samples = resample_audio(samples, self._capture_rate, self.sample_rate)
            if samples.size == 0:
                return
        if self._preprocessor is not None:
            # AGC + noise suppression before anything downstream sees the audio.
            # Emits only whole 10 ms frames; the ~10 ms remainder is flushed on stop.
            samples = self._preprocessor.process(samples)
            if samples.size == 0:
                return
        with self._lock:
            if not (self._note_chunks or self._overlap_stream):
                self._write_capture(samples)
            self._append_stream_samples(samples, chunk_events)
            callback = self._on_chunk
            samples_cb = self._on_samples
        if samples_cb is not None:
            try:
                samples_cb(samples)
            except Exception:  # noqa: BLE001
                pass
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

    def _append_stream_samples(self, samples: np.ndarray, chunk_events: list[AudioChunk]) -> None:
        if self._on_chunk is None:
            return
        if self._note_accumulator is not None:
            for emitted in self._note_accumulator.push(samples):
                chunk_events.append(
                    AudioChunk(
                        samples=emitted.samples,
                        final=False,
                        sequence=emitted.sequence,
                        recording_id=self._recording_id,
                        t_start=emitted.t_start,
                        t_end=emitted.t_end,
                    )
                )
            return
        self._append_window_samples(samples, chunk_events)

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
