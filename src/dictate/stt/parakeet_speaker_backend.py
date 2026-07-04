"""Parakeet ASR plus optional local speaker-attribution backends."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np

from dictate.stt.base import (
    ComputeDevice,
    ComputeType,
    SpeechToText,
    SttCapabilities,
    TranscriptSegment,
)
from dictate.stt.parakeet_backend import ParakeetSpeechToText
from dictate.stt.parakeet_pyannote_backend import (
    SpeakerTurn,
    _annotation_turns,
    _format_segments,
    _transcribe_turn_segments,
    _write_wav,
)

DIARIZEN_MODEL = "BUT-FIT/diarizen-wavlm-large-s80-md"
SORTFORMER_MODEL = "nvidia/diar_streaming_sortformer_4spk-v2.1"
_SAMPLE_RATE = 16000
_MIN_TURN_SECONDS = 0.20


def diarizen_available() -> bool:
    try:
        import diarizen  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def sortformer_available() -> bool:
    try:
        import nemo.collections.asr as nemo_asr  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def diarizen_model_source() -> str:
    return os.environ.get("DICTATE_DIARIZEN_MODEL_PATH") or os.environ.get("DICTATE_DIARIZEN_MODEL") or DIARIZEN_MODEL


def sortformer_model_source() -> str:
    return (
        os.environ.get("DICTATE_SORTFORMER_MODEL_PATH")
        or os.environ.get("DICTATE_SORTFORMER_MODEL")
        or SORTFORMER_MODEL
    )


class _ParakeetSpeakerSpeechToText(SpeechToText):
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
        *,
        model_name: str,
        device: ComputeDevice,
        compute_type: ComputeType,
        speaker_model_source: Callable[[], str],
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._speaker_model_source = speaker_model_source
        self._asr = ParakeetSpeechToText(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
        )
        self._speaker_pipeline: Any | None = None

    @property
    def model(self) -> str:
        return f"{self.model_name}+{self._speaker_model_source()}"

    def prepare_model_resources(self) -> None:
        _ = self._asr.model
        _ = self._load_speaker_pipeline()

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
        self._speaker_pipeline = None

    def _speaker_turns(self, audio: np.ndarray) -> list[SpeakerTurn]:
        raise NotImplementedError

    def _load_speaker_pipeline(self) -> Any:
        raise NotImplementedError


class ParakeetDiariZenSpeechToText(_ParakeetSpeakerSpeechToText):
    """Parakeet ASR with a DiariZen speaker-attribution lane."""

    backend_name = "parakeet-diarizen"

    def __init__(
        self,
        model_name: str = "parakeet-tdt-0.6b-v2",
        device: ComputeDevice = "auto",
        compute_type: ComputeType = "int8",
    ) -> None:
        super().__init__(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            speaker_model_source=diarizen_model_source,
        )

    def _speaker_turns(self, audio: np.ndarray) -> list[SpeakerTurn]:
        with tempfile.TemporaryDirectory(prefix="dictate-diarizen-") as temp_dir:
            wav_path = Path(temp_dir) / "audio.wav"
            _write_wav(wav_path, audio)
            pipeline = self._load_speaker_pipeline()
            diarization = _call_pipeline(pipeline, wav_path)
        return _annotation_turns(diarization)

    def _load_speaker_pipeline(self) -> Any:
        if self._speaker_pipeline is not None:
            return self._speaker_pipeline
        if not diarizen_available():
            raise RuntimeError(
                "DiariZen Meeting backend selected but the diarizen runtime is not importable. "
                "Install a DiariZen runtime or set DICTATE_DIARIZEN_MODEL_PATH to a supported "
                "local checkout before selecting parakeet-diarizen."
            )
        try:
            from diarizen.pipelines.inference import DiariZenPipeline
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "DiariZen is importable, but diarizen.pipelines.inference.DiariZenPipeline "
                "is unavailable in this environment."
            ) from exc
        source = _existing_path_or_ref(diarizen_model_source())
        pipeline = DiariZenPipeline.from_pretrained(source)
        _move_torch_pipeline_to_device(pipeline, self.device)
        self._speaker_pipeline = pipeline
        return pipeline


class ParakeetSortformerSpeechToText(_ParakeetSpeakerSpeechToText):
    """Parakeet ASR with NVIDIA NeMo Sortformer speaker attribution."""

    backend_name = "parakeet-sortformer"

    def __init__(
        self,
        model_name: str = "parakeet-tdt-0.6b-v2",
        device: ComputeDevice = "auto",
        compute_type: ComputeType = "int8",
    ) -> None:
        super().__init__(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
            speaker_model_source=sortformer_model_source,
        )

    def _speaker_turns(self, audio: np.ndarray) -> list[SpeakerTurn]:
        with tempfile.TemporaryDirectory(prefix="dictate-sortformer-") as temp_dir:
            wav_path = Path(temp_dir) / "audio.wav"
            _write_wav(wav_path, audio)
            pipeline = self._load_speaker_pipeline()
            diarization = _call_sortformer(pipeline, wav_path)
        return _coerce_turns(diarization)

    def _load_speaker_pipeline(self) -> Any:
        if self._speaker_pipeline is not None:
            return self._speaker_pipeline
        if not sortformer_available():
            raise RuntimeError(
                "NVIDIA Sortformer Meeting backend selected but NeMo ASR is not importable. "
                'Install the NeMo ASR runtime before selecting parakeet-sortformer.'
            )
        try:
            import nemo.collections.asr as nemo_asr
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("NeMo ASR is not available for Sortformer loading.") from exc
        source = _existing_path_or_ref(sortformer_model_source())
        try:
            model = nemo_asr.models.ASRModel.from_pretrained(model_name=source)
        except TypeError:
            model = nemo_asr.models.ASRModel.from_pretrained(source)
        _move_torch_pipeline_to_device(model, self.device)
        self._speaker_pipeline = model
        return model


def _call_pipeline(pipeline: Any, wav_path: Path) -> Any:
    if callable(pipeline):
        try:
            return pipeline(str(wav_path))
        except TypeError:
            return pipeline(wav_path)
    for name in ("diarize", "infer", "predict", "transcribe"):
        method = getattr(pipeline, name, None)
        if callable(method):
            return method(str(wav_path))
    raise RuntimeError("Speaker-attribution pipeline has no supported call/diarize method.")


def _call_sortformer(pipeline: Any, wav_path: Path) -> Any:
    diarize = getattr(pipeline, "diarize", None)
    if callable(diarize):
        return diarize([str(wav_path)], batch_size=1, num_workers=0, verbose=False)
    transcribe = getattr(pipeline, "transcribe", None)
    if callable(transcribe):
        try:
            result = transcribe([str(wav_path)])
        except TypeError:
            result = transcribe(str(wav_path))
        if isinstance(result, list) and len(result) == 1:
            return result[0]
        return result
    return _call_pipeline(pipeline, wav_path)


def _coerce_turns(value: Any) -> list[SpeakerTurn]:
    if isinstance(value, list):
        turns = _sortformer_line_turns(value)
        if turns:
            return turns
        if value and all(isinstance(item, dict) for item in value):
            return _annotation_turns(value)
        for item in value:
            turns = _coerce_turns(item)
            if turns:
                return turns
        return []
    turns = _annotation_turns(value)
    if turns:
        return turns
    if isinstance(value, dict):
        for key in ("segments", "speaker_segments", "diarization", "predictions"):
            nested = value.get(key)
            turns = _coerce_turns(nested)
            if turns:
                return turns
    for attr in ("segments", "speaker_segments", "diarization", "predictions"):
        if hasattr(value, attr):
            turns = _coerce_turns(getattr(value, attr))
            if turns:
                return turns
    return []


def _sortformer_line_turns(value: list[Any]) -> list[SpeakerTurn]:
    turns: list[SpeakerTurn] = []
    for item in value:
        if not isinstance(item, str):
            return []
        parts = item.strip().split()
        if len(parts) != 3:
            return []
        try:
            start = float(parts[0])
            end = float(parts[1])
        except ValueError:
            return []
        if end <= start:
            continue
        turns.append(SpeakerTurn(start=start, end=end, speaker=parts[2]))
    return sorted(turns, key=lambda turn: (turn.start, turn.end))


def _slice_audio(audio: np.ndarray, start: float, end: float) -> np.ndarray:
    start_i = max(0, min(len(audio), int(start * _SAMPLE_RATE)))
    end_i = max(start_i, min(len(audio), int(end * _SAMPLE_RATE)))
    return np.asarray(audio[start_i:end_i], dtype=np.float32)


def _clamp_time(value: float, duration: float) -> float:
    return max(0.0, min(float(value), duration))


def _existing_path_or_ref(source: str) -> str:
    path = Path(source).expanduser()
    return str(path) if path.exists() else source


def _move_torch_pipeline_to_device(pipeline: Any, device: ComputeDevice) -> None:
    if device == "cpu":
        return
    try:
        import torch
    except Exception:  # noqa: BLE001
        return
    if device in {"cuda", "amd"} or (device == "auto" and torch.cuda.is_available()):
        if torch.cuda.is_available():
            mover = getattr(pipeline, "to", None)
            if callable(mover):
                mover(torch.device("cuda"))
