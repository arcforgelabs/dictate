"""faster-whisper backend adapter."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Literal

import numpy as np

from dictate.stt.base import ComputeDevice, ComputeType, SpeechToText, SttCapabilities

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

DecodeProfile = Literal["quality", "note"]

# Per-mode decode params. "quality" (default) favors accuracy for dictation
# (one-shot PTT, dictation stream chunks, CPU fallback). "note" keeps the
# lighter master-tuned params so long note streaming stays cheap on weak CPUs
# (note backlog aborts the session, so a heavier decode risks a hard regression).
_DECODE_PROFILES: dict[str, dict[str, int]] = {
    "quality": {"beam_size": 5, "min_silence_duration_ms": 500, "speech_pad_ms": 400},
    "note": {"beam_size": 1, "min_silence_duration_ms": 300, "speech_pad_ms": 50},
}


def _normalize_model_name(model_name: str) -> str:
    if model_name == "large-v3-turbo":
        return "turbo"
    return model_name


class FasterWhisperSpeechToText(SpeechToText):
    """Low-latency transcription using faster-whisper."""

    backend_name = "faster-whisper"
    capabilities = SttCapabilities(
        supports_hotwords=True,
        supports_prompt_bias=False,
        supports_language_hint=True,
        supports_streaming_chunks=True,
    )

    def __init__(
        self,
        model_name: str = "turbo",
        device: ComputeDevice = "auto",
        compute_type: ComputeType = "int8",
    ):
        self.model_name = _normalize_model_name(model_name)
        self.device = device
        self.compute_type = compute_type
        self._model: WhisperModel | None = None

    @property
    def model(self) -> WhisperModel:
        if self._model is None:
            from faster_whisper import WhisperModel

            logger.info(
                "Loading faster-whisper model: %s (%s)",
                self.model_name,
                self.compute_type,
            )
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=_cpu_threads(),
            )
            logger.info("Model loaded")
        return self._model

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
        *,
        initial_prompt: str | None = None,
        long_form: bool = False,
        decode_profile: DecodeProfile = "quality",
    ) -> str:
        """
        Transcribe with hallucination-suppression defaults.

        Whisper can hallucinate at the tail of a recording (trailing silence / ambient noise). Two
        things make this worse in push-to-talk workflows:

        - `condition_on_previous_text=True` lets the model condition on its own earlier output and
          "continue the thought" even when there's no speech, producing plausible but fabricated
          endings. We disable it to prevent hallucination chaining across segments.
        - Low-confidence "no-speech" segments near the end can still decode into text.
          `no_speech_threshold=0.6` (faster-whisper's own default) suppresses these segments
          instead of turning them into words; we keep the library default rather than loosening it.

        ``decode_profile`` selects beam size + VAD padding. The default "quality" profile tunes VAD
        padding generously (rather than tightened) so onset speech isn't clipped at chunk/window
        boundaries — the cause of boundary-mangled dictation text. The "note" profile keeps the
        lighter master-tuned params so long note streaming stays cheap on weak CPUs.

        Long-form chunked capture re-enables ``condition_on_previous_text`` and threads an
        ``initial_prompt`` tail for continuity across windows.
        """
        prompt = initial_prompt or prompt_context
        profile = _DECODE_PROFILES.get(decode_profile, _DECODE_PROFILES["quality"])
        segments, _info = self.model.transcribe(
            audio,
            language=language,
            beam_size=profile["beam_size"],
            condition_on_previous_text=long_form,
            initial_prompt=prompt or None,
            no_speech_threshold=0.6,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=profile["min_silence_duration_ms"],
                speech_pad_ms=profile["speech_pad_ms"],
            ),
            hotwords=hotwords,
        )
        return " ".join(seg.text.strip() for seg in segments)

    def release(self) -> None:
        self._model = None


def _cpu_threads() -> int:
    configured = os.environ.get("DICTATE_CPU_THREADS")
    if configured:
        try:
            return max(1, int(configured))
        except ValueError:
            pass
    return max(4, os.cpu_count() or 4)
