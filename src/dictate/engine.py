"""Core dictation pipeline logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from dictate.lexicon import (
    LexiconMode,
    apply_post_corrections,
    build_lexicon_plan,
    normalize_lexicon_mode,
)
from dictate.stt import SpeechToText

ResultStatus = Literal["ok", "empty", "too_short", "no_speech", "error"]


@dataclass(slots=True)
class TranscriptionResult:
    status: ResultStatus
    duration_s: float
    text: str = ""
    error: str | None = None
    notice: str | None = None


class DictationEngine:
    """Shared speech->text logic used by daemon and one-shot CLI."""

    def __init__(
        self,
        stt: SpeechToText,
        sample_rate: int = 16000,
        min_duration_s: float = 0.3,
        hotwords: str | None = None,
        lexicon_mode: LexiconMode = "native",
        lexicon_replacements: dict[str, str] | None = None,
    ):
        self.stt = stt
        self.sample_rate = sample_rate
        self.min_duration_s = min_duration_s
        self.hotwords = hotwords
        self.lexicon_mode = normalize_lexicon_mode(lexicon_mode)
        self.lexicon_replacements = dict(lexicon_replacements or {})
        self._api_fallback_stt: SpeechToText | None = None

    @property
    def supports_hotwords(self) -> bool:
        return self.stt.capabilities.supports_hotwords

    def set_hotwords(self, hotwords: str | None) -> None:
        self.hotwords = hotwords

    def set_lexicon_mode(self, lexicon_mode: LexiconMode) -> None:
        self.lexicon_mode = normalize_lexicon_mode(lexicon_mode)

    def set_lexicon_replacements(self, replacements: dict[str, str] | None) -> None:
        self.lexicon_replacements = dict(replacements or {})

    def duration_s(self, audio: np.ndarray) -> float:
        return len(audio) / self.sample_rate

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> TranscriptionResult:
        """Transcribe audio and classify common non-success outcomes."""
        if audio.size == 0:
            return TranscriptionResult(status="empty", duration_s=0.0)

        duration = self.duration_s(audio)
        if duration < self.min_duration_s:
            return TranscriptionResult(status="too_short", duration_s=duration)

        lexicon_plan = build_lexicon_plan(
            stt=self.stt,
            hotwords=self.hotwords,
            lexicon_mode=self.lexicon_mode,
            replacements=self.lexicon_replacements,
        )
        try:
            text = self.stt.transcribe(
                audio,
                language=language,
                hotwords=lexicon_plan.decode_hotwords,
                prompt_context=lexicon_plan.prompt_context,
            ).strip()
        except Exception as exc:  # noqa: BLE001
            if not _api_fallback_allowed(self.stt):
                return TranscriptionResult(
                    status="error",
                    duration_s=duration,
                    error=str(exc),
                )
            return self._transcribe_with_cpu_fallback(
                audio,
                language=language,
                primary_error=exc,
            )

        if lexicon_plan.post_hotwords or lexicon_plan.post_replacements:
            text = apply_post_corrections(
                text,
                hotwords=lexicon_plan.post_hotwords,
                replacements=lexicon_plan.post_replacements,
            ).strip()

        if not text:
            return TranscriptionResult(status="no_speech", duration_s=duration)

        return TranscriptionResult(
            status="ok",
            duration_s=duration,
            text=text,
        )

    def release(self) -> None:
        """Release primary and fallback STT resources."""
        try:
            self.stt.release()
        finally:
            self.release_api_fallback()

    def release_api_fallback(self) -> None:
        """Release any cached CPU fallback model."""
        if self._api_fallback_stt is None:
            return
        try:
            self._api_fallback_stt.release()
        finally:
            self._api_fallback_stt = None

    def _transcribe_with_cpu_fallback(
        self,
        audio: np.ndarray,
        *,
        language: str | None,
        primary_error: Exception,
    ) -> TranscriptionResult:
        fallback_stt = self._api_fallback_stt
        if fallback_stt is None:
            try:
                fallback_stt = _create_cpu_whisper_fallback()
            except Exception as fallback_load_error:  # noqa: BLE001
                return TranscriptionResult(
                    status="error",
                    duration_s=self.duration_s(audio),
                    error=_fallback_error_message(
                        self.stt,
                        primary_error=primary_error,
                        fallback_error=fallback_load_error,
                    ),
                )
            self._api_fallback_stt = fallback_stt

        fallback_plan = build_lexicon_plan(
            stt=fallback_stt,
            hotwords=self.hotwords,
            lexicon_mode=self.lexicon_mode,
            replacements=self.lexicon_replacements,
        )
        try:
            text = fallback_stt.transcribe(
                audio,
                language=language,
                hotwords=fallback_plan.decode_hotwords,
                prompt_context=fallback_plan.prompt_context,
            ).strip()
        except Exception as fallback_error:  # noqa: BLE001
            return TranscriptionResult(
                status="error",
                duration_s=self.duration_s(audio),
                error=_fallback_error_message(
                    self.stt,
                    primary_error=primary_error,
                    fallback_error=fallback_error,
                ),
            )

        if fallback_plan.post_hotwords or fallback_plan.post_replacements:
            text = apply_post_corrections(
                text,
                hotwords=fallback_plan.post_hotwords,
                replacements=fallback_plan.post_replacements,
            ).strip()

        if not text:
            return TranscriptionResult(
                status="no_speech",
                duration_s=self.duration_s(audio),
                notice=_fallback_notice_message(self.stt, primary_error),
            )
        return TranscriptionResult(
            status="ok",
            duration_s=self.duration_s(audio),
            text=text,
            notice=_fallback_notice_message(self.stt, primary_error),
        )


def _api_fallback_allowed(stt: SpeechToText) -> bool:
    return stt.backend_name in {"openai", "xai", "gemini"}


def _create_cpu_whisper_fallback() -> SpeechToText:
    from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText

    return FasterWhisperSpeechToText(model_name="base", device="cpu", compute_type="int8")


def _fallback_notice_message(stt: SpeechToText, primary_error: Exception) -> str:
    return (
        f"{_backend_label(stt)} transcription failed; "
        "used faster-whisper/base on CPU for this turn. "
        f"API error: {_short_error(primary_error)}"
    )


def _fallback_error_message(
    stt: SpeechToText,
    *,
    primary_error: Exception,
    fallback_error: Exception,
) -> str:
    return (
        f"{_backend_label(stt)} transcription failed: {_short_error(primary_error)}; "
        f"CPU fallback failed: {_short_error(fallback_error)}"
    )


def _backend_label(stt: SpeechToText) -> str:
    if stt.backend_name == "xai":
        return "xAI"
    if stt.backend_name == "openai":
        return "OpenAI"
    if stt.backend_name == "gemini":
        return "Gemini"
    return stt.backend_name


def _short_error(exc: Exception, limit: int = 240) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    if len(message) <= limit:
        return message
    return f"{message[: limit - 3]}..."
