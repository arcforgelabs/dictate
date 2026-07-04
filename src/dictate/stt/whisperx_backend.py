"""WhisperX local transcription and diarization backend adapter."""

from __future__ import annotations

import os
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

from dictate.stt.base import ComputeDevice, ComputeType, SpeechToText, SttCapabilities


class WhisperXSpeechToText(SpeechToText):
    """Local WhisperX backend for word alignment and pyannote speaker diarization."""

    backend_name = "whisperx"
    capabilities = SttCapabilities(
        supports_hotwords=False,
        supports_prompt_bias=False,
        supports_language_hint=True,
        supports_word_timestamps=True,
        supports_speaker_attribution=True,
    )

    def __init__(
        self,
        model_name: str = "large-v3",
        device: ComputeDevice = "auto",
        compute_type: ComputeType = "int8",
    ) -> None:
        self.model_name = model_name
        self.device = _resolve_device(device)
        self.compute_type = compute_type
        self._whisperx = _import_whisperx()
        self._model = self._whisperx.load_model(
            model_name,
            self.device,
            compute_type=compute_type,
        )

    @property
    def model(self) -> str:
        return self.model_name

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
    ) -> str:
        del hotwords, prompt_context
        result = self._transcribe_result(audio, language=language)
        return _segments_text(result).strip()

    def transcribe_diarized(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
    ) -> str:
        """Transcribe with WhisperX alignment and pyannote speaker labels."""
        del hotwords
        token = _hf_token()
        if not token:
            raise RuntimeError(
                "WhisperX diarization requires a Hugging Face token. "
                "Accept pyannote model terms, then set DICTATE_HF_TOKEN, "
                "HUGGINGFACE_HUB_TOKEN, or HF_TOKEN."
            )

        with tempfile.TemporaryDirectory(prefix="dictate-whisperx-") as temp_dir:
            wav_path = Path(temp_dir) / "audio.wav"
            _write_wav(wav_path, audio)
            whisper_audio = self._whisperx.load_audio(str(wav_path))
            result = self._model.transcribe(
                whisper_audio,
                batch_size=_batch_size(),
                language=language,
            )
            result = self._align_result(result, whisper_audio)
            diarize_model = self._whisperx.DiarizationPipeline(
                use_auth_token=token,
                device=self.device,
            )
            diarize_segments = diarize_model(str(wav_path))
            result = self._whisperx.assign_word_speakers(diarize_segments, result)
        return _diarized_segments_text(result).strip() or _segments_text(result).strip()

    def release(self) -> None:
        self._model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return

    def _transcribe_result(self, audio: np.ndarray, *, language: str | None) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="dictate-whisperx-") as temp_dir:
            wav_path = Path(temp_dir) / "audio.wav"
            _write_wav(wav_path, audio)
            whisper_audio = self._whisperx.load_audio(str(wav_path))
            result = self._model.transcribe(
                whisper_audio,
                batch_size=_batch_size(),
                language=language,
            )
        return result if isinstance(result, dict) else {}

    def _align_result(self, result: dict[str, Any], audio: np.ndarray) -> dict[str, Any]:
        language_code = result.get("language") if isinstance(result.get("language"), str) else "en"
        try:
            align_model, metadata = self._whisperx.load_align_model(
                language_code=language_code,
                device=self.device,
            )
            return self._whisperx.align(
                result.get("segments", []),
                align_model,
                metadata,
                audio,
                self.device,
                return_char_alignments=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"WhisperX alignment failed: {exc}") from exc


def whisperx_available() -> bool:
    try:
        _import_whisperx()
    except Exception:
        return False
    return True


def _import_whisperx() -> Any:
    try:
        import whisperx
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "WhisperX backend requires optional dependencies. "
            'Install with: uv pip install -e ".[whisperx]"'
        ) from exc
    return whisperx


def _resolve_device(device: ComputeDevice) -> str:
    if device != "auto":
        return device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _hf_token() -> str | None:
    for name in ("DICTATE_HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "HF_TOKEN"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def _batch_size() -> int:
    raw = os.environ.get("DICTATE_WHISPERX_BATCH_SIZE", "16")
    try:
        value = int(raw)
    except ValueError:
        return 16
    return max(1, min(64, value))


def _write_wav(path: Path, audio: np.ndarray, sample_rate: int = 16000) -> None:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


def _segments_text(result: dict[str, Any]) -> str:
    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    pieces: list[str] = []
    for segment in result.get("segments", []):
        if isinstance(segment, dict) and isinstance(segment.get("text"), str):
            pieces.append(segment["text"].strip())
    return " ".join(piece for piece in pieces if piece).strip()


def _diarized_segments_text(result: dict[str, Any]) -> str:
    segments = result.get("segments", [])
    if not isinstance(segments, list):
        return ""

    turns: list[tuple[str, list[str]]] = []
    speaker_labels: dict[str, str] = {}
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        speaker = segment.get("speaker")
        if not isinstance(speaker, str) or not speaker.strip():
            speaker = _speaker_from_words(segment.get("words")) or "SPEAKER_UNKNOWN"
        if speaker not in speaker_labels:
            speaker_labels[speaker] = f"Speaker {len(speaker_labels) + 1}"
        if not turns or turns[-1][0] != speaker:
            turns.append((speaker, []))
        turns[-1][1].append(text.strip())

    lines: list[str] = []
    for speaker, pieces in turns:
        utterance = " ".join(pieces).strip()
        if utterance:
            lines.append(f"{speaker_labels[speaker]}: {utterance}")
    return "\n".join(lines).strip()


def _speaker_from_words(words: object) -> str | None:
    if not isinstance(words, list):
        return None
    for word in words:
        if isinstance(word, dict) and isinstance(word.get("speaker"), str):
            speaker = word["speaker"].strip()
            if speaker:
                return speaker
    return None
