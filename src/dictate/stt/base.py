"""Shared STT interfaces and type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

FasterWhisperModel = Literal[
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "turbo",
    "large-v3-turbo",
]
WhisperCppModel = Literal[
    "base",
    "small",
    "turbo",
    "large-v3-turbo",
    "large-v3-turbo-q5_0",
    "large-v3-turbo-q8_0",
]
ComputeDevice = Literal["cpu", "cuda", "auto"]
ComputeType = Literal["int8", "float16", "float32"]
SttBackend = Literal["faster-whisper", "nemo-canary", "whisper-cpp"]


@dataclass(frozen=True, slots=True)
class SttCapabilities:
    supports_hotwords: bool = False
    supports_prompt_bias: bool = False
    supports_language_hint: bool = True
    supports_word_timestamps: bool = False


class SpeechToText:
    """Base speech-to-text backend interface."""

    backend_name = "base"
    model_name = ""
    capabilities = SttCapabilities()

    @property
    def model(self) -> Any:
        raise NotImplementedError

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        hotwords: str | None = None,
        prompt_context: str | None = None,
    ) -> str:
        raise NotImplementedError

    def release(self) -> None:
        """Release backend resources (for example GPU memory caches)."""
        return
