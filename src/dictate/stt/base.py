"""Shared STT interfaces and type definitions."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Literal, TextIO

import numpy as np

# Dictate runs on CPU only. int8 is the default; float32 loads the full-precision
# Parakeet ONNX files. There is no device choice.
ComputeType = Literal["int8", "float32"]
COMPUTE_TYPES: tuple[ComputeType, ...] = ("int8", "float32")
SttBackend = Literal[
    "parakeet",
    "parakeet-pyannote",
    "parakeet-diarizen",
    "parakeet-sortformer",
]


@dataclass(frozen=True, slots=True)
class SttCapabilities:
    supports_hotwords: bool = False
    supports_prompt_bias: bool = False
    supports_language_hint: bool = True
    supports_word_timestamps: bool = False
    supports_speaker_attribution: bool = False
    supports_streaming_chunks: bool = False


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """Structured transcript segment with optional speaker and timing metadata."""

    text: str
    t_start: float | None = None
    t_end: float | None = None
    speaker_id: str | None = None
    speaker_label: str | None = None


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
        """Release backend resources (for example the loaded model)."""
        return


def add_retired_device_argument(parser: argparse.ArgumentParser) -> None:
    """Accept the retired ``--device`` flag so existing scripts keep working.

    Dictate runs on CPU only. ``--device cpu`` and ``--device auto`` (what the
    installers used to pass) are silent no-ops; any other value is ignored with
    a one-line notice (see ``note_retired_device``). The flag is hidden from
    ``--help``.
    """
    parser.add_argument("--device", default=None, help=argparse.SUPPRESS)


def is_cpu_device_name(value: str) -> bool:
    """True for retired device names that need no notice: cpu, and auto (now always CPU)."""
    return value.strip().lower() in {"cpu", "auto"}


def note_retired_device(value: str | None, *, stream: TextIO | None = None) -> None:
    """Print a one-line notice when a retired non-CPU device was requested."""
    if value is None or is_cpu_device_name(value):
        return
    print(
        f"Ignoring --device {value}: Dictate runs on CPU only.",
        file=stream if stream is not None else sys.stderr,
    )
