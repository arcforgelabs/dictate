"""Parakeet ASR plus pyannote Community-1 speaker attribution."""

from __future__ import annotations

import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dictate.stt.base import (
    ComputeDevice,
    ComputeType,
    SpeechToText,
    SttCapabilities,
    TranscriptSegment,
)
from dictate.stt.parakeet_backend import ParakeetSpeechToText

PYANNOTE_COMMUNITY_MODEL = "pyannote/speaker-diarization-community-1"
_SAMPLE_RATE = 16000
_MIN_TURN_SECONDS = 0.20


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str


def pyannote_available() -> bool:
    try:
        import pyannote.audio  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def pyannote_token() -> str | None:
    return (
        os.environ.get("DICTATE_HF_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or os.environ.get("HF_TOKEN")
    )


def pyannote_model_source() -> str:
    return (
        os.environ.get("DICTATE_PYANNOTE_MODEL_PATH")
        or os.environ.get("DICTATE_PYANNOTE_MODEL")
        or PYANNOTE_COMMUNITY_MODEL
    )


class ParakeetPyannoteSpeechToText(SpeechToText):
    """Local meeting backend: pyannote speaker turns, Parakeet text per turn."""

    backend_name = "parakeet-pyannote"
    capabilities = SttCapabilities(
        supports_hotwords=False,
        supports_prompt_bias=False,
        supports_language_hint=False,
        supports_word_timestamps=False,
        supports_speaker_attribution=True,
        supports_streaming_chunks=False,
    )

    def __init__(
        self,
        model_name: str = "parakeet-tdt-0.6b-v2",
        device: ComputeDevice = "auto",
        compute_type: ComputeType = "int8",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._asr = ParakeetSpeechToText(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
        )
        self._pipeline: Any | None = None

    @property
    def model(self) -> str:
        return f"{self.model_name}+{pyannote_model_source()}"

    def prepare_model_resources(self) -> None:
        """Load ASR and speaker-attribution resources for install-time validation."""
        _ = self._asr.model
        _ = self._pyannote_pipeline()

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
    ) -> str:
        return self._asr.transcribe(
            audio,
            language=language,
            hotwords=hotwords,
            prompt_context=prompt_context,
        )

    def transcribe_diarized(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
    ) -> str:
        return _format_segments(self.transcribe_diarized_segments(audio, language, hotwords))

    def transcribe_diarized_segments(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
    ) -> list[TranscriptSegment]:
        if audio.size == 0:
            return []

        turns = self._speaker_turns(audio)
        if not turns:
            text = self.transcribe(audio, language=language, hotwords=hotwords)
            if not text.strip():
                return []
            return [TranscriptSegment(text=text.strip(), t_start=0.0, t_end=len(audio) / _SAMPLE_RATE)]

        speaker_names: dict[str, str] = {}
        segments: list[TranscriptSegment] = []
        audio_duration = len(audio) / _SAMPLE_RATE
        for turn in turns:
            turn_start = _clamp_time(turn.start, audio_duration)
            turn_end = _clamp_time(turn.end, audio_duration)
            if turn_end <= turn_start:
                continue
            segment = _slice_audio(audio, turn_start, turn_end)
            if len(segment) < int(_MIN_TURN_SECONDS * _SAMPLE_RATE):
                continue
            label = speaker_names.setdefault(turn.speaker, f"Speaker {len(speaker_names) + 1}")
            segments.extend(
                _transcribe_turn_segments(
                    self._asr,
                    segment,
                    turn_start=turn_start,
                    turn_end=turn_end,
                    speaker_id=turn.speaker,
                    speaker_label=label,
                    language=language,
                    hotwords=hotwords,
                )
            )
        return segments

    def release(self) -> None:
        self._asr.release()
        self._pipeline = None

    def _speaker_turns(self, audio: np.ndarray) -> list[SpeakerTurn]:
        with tempfile.TemporaryDirectory(prefix="dictate-pyannote-") as temp_dir:
            wav_path = Path(temp_dir) / "audio.wav"
            _write_wav(wav_path, audio)
            diarization = self._pyannote_pipeline()(str(wav_path))
        annotation = getattr(diarization, "exclusive_speaker_diarization", diarization)
        return _annotation_turns(annotation)

    def _pyannote_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline

        from pyannote.audio import Pipeline

        source = pyannote_model_source()
        source_path = Path(source).expanduser()
        token = None if source_path.exists() else pyannote_token()
        if token is None and not source_path.exists():
            raise RuntimeError(
                "pyannote Community-1 requires a Hugging Face token. Accept the "
                "pyannote/speaker-diarization-community-1 model terms, then set "
                "DICTATE_HF_TOKEN, HUGGINGFACE_HUB_TOKEN, or HF_TOKEN. For offline "
                "use, set DICTATE_PYANNOTE_MODEL_PATH to a local model checkout."
            )
        model_ref = str(source_path if source_path.exists() else source)
        pipeline = Pipeline.from_pretrained(model_ref, token=token)
        _move_pipeline_to_device(pipeline, self.device)
        self._pipeline = pipeline
        return pipeline


def _move_pipeline_to_device(pipeline: Any, device: ComputeDevice) -> None:
    if device == "cpu":
        return
    try:
        import torch
    except Exception:  # noqa: BLE001
        return
    if device in {"cuda", "amd"} or (device == "auto" and torch.cuda.is_available()):
        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))


def _slice_audio(audio: np.ndarray, start: float, end: float) -> np.ndarray:
    start_i = max(0, min(len(audio), int(start * _SAMPLE_RATE)))
    end_i = max(start_i, min(len(audio), int(end * _SAMPLE_RATE)))
    return np.asarray(audio[start_i:end_i], dtype=np.float32)


def _clamp_time(value: float, duration: float) -> float:
    return max(0.0, min(float(value), duration))


def _transcribe_turn_segments(
    asr: Any,
    audio: np.ndarray,
    *,
    turn_start: float,
    turn_end: float,
    speaker_id: str,
    speaker_label: str,
    language: str | None,
    hotwords: str | None,
) -> list[TranscriptSegment]:
    transcribe_segments = getattr(asr, "transcribe_segments", None)
    if callable(transcribe_segments):
        raw_segments = transcribe_segments(audio, language=language, hotwords=hotwords)
        segments = [
            _offset_turn_segment(
                segment,
                turn_start=turn_start,
                turn_end=turn_end,
                speaker_id=speaker_id,
                speaker_label=speaker_label,
            )
            for segment in raw_segments
            if segment.text.strip()
        ]
        if segments:
            return segments

    text = asr.transcribe(audio, language=language, hotwords=hotwords).strip()
    if not text:
        return []
    return [
        TranscriptSegment(
            text=text,
            t_start=turn_start,
            t_end=turn_end,
            speaker_id=speaker_id,
            speaker_label=speaker_label,
        )
    ]


def _offset_turn_segment(
    segment: TranscriptSegment,
    *,
    turn_start: float,
    turn_end: float,
    speaker_id: str,
    speaker_label: str,
) -> TranscriptSegment:
    t_start = _offset_optional_time(segment.t_start, turn_start, turn_end)
    t_end = _offset_optional_time(segment.t_end, turn_start, turn_end)
    if t_start is not None and t_end is not None and t_end < t_start:
        t_start, t_end = t_end, t_start
    if t_start is None and t_end is None:
        t_start, t_end = turn_start, turn_end
    return TranscriptSegment(
        text=segment.text.strip(),
        t_start=t_start,
        t_end=t_end,
        speaker_id=speaker_id,
        speaker_label=speaker_label,
    )


def _offset_optional_time(value: float | None, turn_start: float, turn_end: float) -> float | None:
    if value is None:
        return None
    return _clamp_time(turn_start + float(value), turn_end)


def _annotation_turns(annotation: Any) -> list[SpeakerTurn]:
    if hasattr(annotation, "itertracks"):
        turns: list[SpeakerTurn] = []
        for segment, _track, speaker in annotation.itertracks(yield_label=True):
            turns.append(
                SpeakerTurn(
                    start=float(segment.start),
                    end=float(segment.end),
                    speaker=str(speaker),
                )
            )
        return sorted(turns, key=lambda turn: (turn.start, turn.end))
    if isinstance(annotation, list):
        return sorted(
            (
                SpeakerTurn(
                    start=float(item["start"]),
                    end=float(item["end"]),
                    speaker=str(item["speaker"]),
                )
                for item in annotation
            ),
            key=lambda turn: (turn.start, turn.end),
        )
    return []


def _format_labelled_turns(turns: list[tuple[str, str]]) -> str:
    grouped: list[tuple[str, list[str]]] = []
    for speaker, text in turns:
        if grouped and grouped[-1][0] == speaker:
            grouped[-1][1].append(text)
        else:
            grouped.append((speaker, [text]))
    return "\n".join(f"{speaker}: {' '.join(parts).strip()}" for speaker, parts in grouped).strip()


def _format_segments(segments: list[TranscriptSegment]) -> str:
    if not any(segment.speaker_label or segment.speaker_id for segment in segments):
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
    return _format_labelled_turns(
        [
            (segment.speaker_label or segment.speaker_id or "Transcript", segment.text)
            for segment in segments
            if segment.text.strip()
        ]
    )


def _write_wav(path: Path, audio: np.ndarray) -> None:
    samples = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (samples * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(pcm.tobytes())
