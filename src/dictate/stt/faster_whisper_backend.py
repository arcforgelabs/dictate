"""faster-whisper backend adapter."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import numpy as np

from dictate.stt.base import ComputeDevice, ComputeType, SpeechToText, SttCapabilities

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


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
    ) -> str:
        """
        Transcribe with hallucination-suppression defaults.

        Whisper can hallucinate at the tail of a recording (trailing silence / ambient noise). Two
        things make this worse in push-to-talk workflows:

        - `condition_on_previous_text=True` lets the model condition on its own earlier output and
          "continue the thought" even when there's no speech, producing plausible but fabricated
          endings. We disable it to prevent hallucination chaining across segments.
        - Low-confidence "no-speech" segments near the end can still decode into text. Setting a
          higher `no_speech_threshold` suppresses these segments instead of turning them into words.

        We also tighten VAD padding/silence detection so less trailing non-speech audio is fed into
        the decoder in the first place.

        Long-form chunked note capture re-enables ``condition_on_previous_text`` and threads an
        ``initial_prompt`` tail for continuity across windows.
        """
        prompt = initial_prompt or prompt_context
        segments, _info = self.model.transcribe(
            audio,
            language=language,
            beam_size=1,
            condition_on_previous_text=long_form,
            initial_prompt=prompt or None,
            no_speech_threshold=0.6,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=300,
                speech_pad_ms=50,
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
