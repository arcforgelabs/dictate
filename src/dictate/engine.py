"""Core dictation pipeline logic."""

from __future__ import annotations

import threading
from collections.abc import Callable
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
        # Optional callback for provider health reporting.
        # Signature: health_sink(healthy: bool, reason: str | None) -> None
        # Called after each online-backend transcription attempt; not called for
        # faster-whisper (on-device). Thread-safe: the lock guards the assignment.
        self._health_sink_lock = threading.Lock()
        self._health_sink: Callable[[bool, str | None], None] | None = None

    @property
    def health_sink(self) -> Callable[[bool, str | None], None] | None:
        with self._health_sink_lock:
            return self._health_sink

    @health_sink.setter
    def health_sink(self, fn: Callable[[bool, str | None], None] | None) -> None:
        with self._health_sink_lock:
            self._health_sink = fn

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

    def transcribe(
        self,
        audio: np.ndarray,
        language: str | None = None,
        *,
        min_duration_s: float | None = None,
        diarize: bool = False,
        decode_profile: str = "quality",
    ) -> TranscriptionResult:
        """Transcribe audio; fall back to on-device CPU on remote failure.

        ``decode_profile`` selects the on-device decode params; callers pass "note"
        for note-mode recordings so a CPU fallback keeps the lighter master-tuned
        params instead of the heavier dictation "quality" defaults.
        """
        return self._do_transcribe(
            audio,
            language,
            min_duration_s=min_duration_s,
            diarize=diarize,
            allow_cpu_fallback=True,
            decode_profile=decode_profile,
        )

    def transcribe_remote_only(
        self,
        audio: np.ndarray,
        language: str | None = None,
        *,
        min_duration_s: float | None = None,
        diarize: bool = False,
    ) -> TranscriptionResult:
        """Transcribe using the primary backend only; raise on remote failure.

        No CPU fallback.  Used by the daemon's retry loop for long recordings
        so each chunk can be retried before giving up and degrading.

        Unlike ``transcribe()``, failure does NOT call the ``health_sink`` —
        individual retry attempts should not prematurely mark the supervisor
        degraded.  The daemon's retry wrapper calls ``engine.transcribe()``
        for the final attempt, which does report to the sink.  Success on any
        retry attempt DOES call the sink (so a prior degradation can recover).
        """
        return self._do_transcribe(
            audio,
            language,
            min_duration_s=min_duration_s,
            diarize=diarize,
            allow_cpu_fallback=False,
            report_health_on_fail=False,
        )

    def transcribe_local(
        self,
        audio: np.ndarray,
        language: str | None = None,
        *,
        min_duration_s: float | None = None,
        initial_prompt: str | None = None,
        long_form: bool = False,
        decode_profile: str = "quality",
    ) -> TranscriptionResult:
        """Force on-device CPU transcription (for degraded sessions).

        Bypasses the primary STT backend entirely and never produces a
        fallback-notice message (the caller owns the degradation context).
        """
        if audio.size == 0:
            return TranscriptionResult(status="empty", duration_s=0.0)

        duration = self.duration_s(audio)
        duration_floor = self.min_duration_s if min_duration_s is None else min_duration_s
        if duration < duration_floor:
            return TranscriptionResult(status="too_short", duration_s=duration)

        return self._transcribe_with_cpu_fallback(
            audio,
            language=language,
            primary_error=None,
            initial_prompt=initial_prompt,
            long_form=long_form,
            decode_profile=decode_profile,
        )

    def transcribe_stream_chunk(
        self,
        audio: np.ndarray,
        language: str | None = None,
        *,
        initial_prompt: str | None = None,
        min_duration_s: float | None = None,
        long_form: bool = True,
        decode_profile: str = "quality",
    ) -> TranscriptionResult:
        """Transcribe one streamed chunk (note or dictation) on the active local backend.

        ``long_form`` enables ``condition_on_previous_text`` for mid-stream continuity;
        callers pass ``long_form=False`` for a stream's terminal chunk to avoid
        trailing-silence hallucination while still threading ``initial_prompt``.

        ``decode_profile`` selects the backend decode params: the default "quality"
        for dictation, "note" for note streaming (lighter params so long note
        capture stays cheap on weak CPUs — unchanged from master).
        """
        if audio.size == 0:
            return TranscriptionResult(status="empty", duration_s=0.0)

        duration = self.duration_s(audio)
        duration_floor = self.min_duration_s if min_duration_s is None else min_duration_s
        if duration < duration_floor:
            return TranscriptionResult(status="too_short", duration_s=duration)

        if _api_fallback_allowed(self.stt):
            return self.transcribe_local(
                audio,
                language,
                min_duration_s=min_duration_s,
                initial_prompt=initial_prompt,
                long_form=long_form,
                decode_profile=decode_profile,
            )

        lexicon_plan = build_lexicon_plan(
            stt=self.stt,
            hotwords=self.hotwords,
            lexicon_mode=self.lexicon_mode,
            replacements=self.lexicon_replacements,
        )
        try:
            try:
                text = self.stt.transcribe(
                    audio,
                    language=language,
                    hotwords=lexicon_plan.decode_hotwords,
                    prompt_context=lexicon_plan.prompt_context,
                    initial_prompt=initial_prompt,
                    long_form=long_form,
                    decode_profile=decode_profile,
                ).strip()
            except TypeError:
                # Degrade one kwarg at a time: first drop only decode_profile so a
                # backend that still honors initial_prompt/long_form keeps cross-chunk
                # threading; only if THAT also TypeErrors do we drop everything.
                try:
                    text = self.stt.transcribe(
                        audio,
                        language=language,
                        hotwords=lexicon_plan.decode_hotwords,
                        prompt_context=lexicon_plan.prompt_context,
                        initial_prompt=initial_prompt,
                        long_form=long_form,
                    ).strip()
                except TypeError:
                    text = self.stt.transcribe(
                        audio,
                        language=language,
                        hotwords=lexicon_plan.decode_hotwords,
                        prompt_context=lexicon_plan.prompt_context,
                    ).strip()
        except Exception as exc:  # noqa: BLE001
            return TranscriptionResult(
                status="error",
                duration_s=duration,
                error=str(exc),
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

    def _do_transcribe(
        self,
        audio: np.ndarray,
        language: str | None,
        *,
        min_duration_s: float | None,
        diarize: bool,
        allow_cpu_fallback: bool,
        report_health_on_fail: bool = True,
        decode_profile: str = "quality",
    ) -> TranscriptionResult:
        """Core transcription logic shared by public transcribe variants."""
        if audio.size == 0:
            return TranscriptionResult(status="empty", duration_s=0.0)

        duration = self.duration_s(audio)
        duration_floor = self.min_duration_s if min_duration_s is None else min_duration_s
        if duration < duration_floor:
            return TranscriptionResult(status="too_short", duration_s=duration)

        lexicon_plan = build_lexicon_plan(
            stt=self.stt,
            hotwords=self.hotwords,
            lexicon_mode=self.lexicon_mode,
            replacements=self.lexicon_replacements,
        )
        _online = self.stt.backend_name in {"xai", "openai", "gemini"}
        try:
            if diarize and hasattr(self.stt, "transcribe_diarized"):
                text = self.stt.transcribe_diarized(
                    audio,
                    language=language,
                    hotwords=lexicon_plan.decode_hotwords,
                ).strip()
            else:
                try:
                    text = self.stt.transcribe(
                        audio,
                        language=language,
                        hotwords=lexicon_plan.decode_hotwords,
                        prompt_context=lexicon_plan.prompt_context,
                        decode_profile=decode_profile,
                    ).strip()
                except TypeError:
                    # Backend predates decode_profile: retry without it, keeping the
                    # other kwargs. A genuine transcription failure is not a TypeError
                    # and still propagates to the CPU-fallback path below.
                    text = self.stt.transcribe(
                        audio,
                        language=language,
                        hotwords=lexicon_plan.decode_hotwords,
                        prompt_context=lexicon_plan.prompt_context,
                    ).strip()
        except Exception as exc:  # noqa: BLE001
            if _online and report_health_on_fail:
                self._report_health(False, _classify_health_error(exc))
            if not _api_fallback_allowed(self.stt):
                # Non-API (on-device) backend: return error directly; no fallback.
                return TranscriptionResult(
                    status="error",
                    duration_s=duration,
                    error=str(exc),
                )
            if not allow_cpu_fallback:
                # Caller wants raw remote failure (retry logic in daemon).
                raise
            return self._transcribe_with_cpu_fallback(
                audio,
                language=language,
                primary_error=exc,
                decode_profile=decode_profile,
            )

        if _online:
            self._report_health(True, None)

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
        primary_error: Exception | None,
        initial_prompt: str | None = None,
        long_form: bool = False,
        decode_profile: str = "quality",
    ) -> TranscriptionResult:
        """Fall back to on-device CPU whisper transcription.

        ``primary_error=None`` means a silent fallback (caller is already in
        degraded mode and wants no notice message on every chunk).
        """
        fallback_stt = self._api_fallback_stt
        if fallback_stt is None:
            try:
                fallback_stt = _create_cpu_whisper_fallback()
            except Exception as fallback_load_error:  # noqa: BLE001
                if primary_error is not None:
                    error = _fallback_error_message(
                        self.stt,
                        primary_error=primary_error,
                        fallback_error=fallback_load_error,
                    )
                else:
                    error = f"CPU fallback load failed: {fallback_load_error}"
                return TranscriptionResult(
                    status="error",
                    duration_s=self.duration_s(audio),
                    error=error,
                )
            self._api_fallback_stt = fallback_stt

        fallback_plan = build_lexicon_plan(
            stt=fallback_stt,
            hotwords=self.hotwords,
            lexicon_mode=self.lexicon_mode,
            replacements=self.lexicon_replacements,
        )
        try:
            try:
                text = fallback_stt.transcribe(
                    audio,
                    language=language,
                    hotwords=fallback_plan.decode_hotwords,
                    prompt_context=fallback_plan.prompt_context,
                    initial_prompt=initial_prompt,
                    long_form=long_form,
                    decode_profile=decode_profile,
                ).strip()
            except TypeError:
                # Degrade one kwarg at a time: drop decode_profile first (keep
                # initial_prompt/long_form), then fall back to the bare call.
                try:
                    text = fallback_stt.transcribe(
                        audio,
                        language=language,
                        hotwords=fallback_plan.decode_hotwords,
                        prompt_context=fallback_plan.prompt_context,
                        initial_prompt=initial_prompt,
                        long_form=long_form,
                    ).strip()
                except TypeError:
                    text = fallback_stt.transcribe(
                        audio,
                        language=language,
                        hotwords=fallback_plan.decode_hotwords,
                        prompt_context=fallback_plan.prompt_context,
                    ).strip()
        except Exception as fallback_error:  # noqa: BLE001
            if primary_error is not None:
                error = _fallback_error_message(
                    self.stt,
                    primary_error=primary_error,
                    fallback_error=fallback_error,
                )
            else:
                error = f"CPU fallback transcription failed: {fallback_error}"
            return TranscriptionResult(
                status="error",
                duration_s=self.duration_s(audio),
                error=error,
            )

        if fallback_plan.post_hotwords or fallback_plan.post_replacements:
            text = apply_post_corrections(
                text,
                hotwords=fallback_plan.post_hotwords,
                replacements=fallback_plan.post_replacements,
            ).strip()

        # Notice is only attached when there is an original remote error to report
        notice = _fallback_notice_message(self.stt, primary_error) if primary_error is not None else None

        if not text:
            return TranscriptionResult(
                status="no_speech",
                duration_s=self.duration_s(audio),
                notice=notice,
            )
        return TranscriptionResult(
            status="ok",
            duration_s=self.duration_s(audio),
            text=text,
            notice=notice,
        )


    def _report_health(self, healthy: bool, reason: str | None) -> None:
        """Call the health_sink callback if one is registered."""
        sink = self.health_sink
        if sink is not None:
            try:
                sink(healthy, reason)
            except Exception:  # noqa: BLE001 — never let health reporting crash transcription
                pass


def _classify_health_error(exc: Exception) -> str:
    """Map a transcription exception to a provider-health reason string.

    Returns one of: ``"auth"``, ``"rate-limit"``, ``"budget"``, ``"unreachable"``.
    """
    msg = str(exc).lower()

    # Auth failures — 401, 403, bad key messages
    if (
        "401" in msg
        or "403" in msg
        or "unauthorized" in msg
        or "forbidden" in msg
        or "authentication" in msg
        or "invalid api key" in msg
        or "invalid_api_key" in msg
        or "api key" in msg and "invalid" in msg
    ):
        return "auth"

    # Rate limiting — 429, explicit rate-limit messages
    if (
        "429" in msg
        or "rate limit" in msg
        or "rate_limit" in msg
        or "too many requests" in msg
        or "ratelimit" in msg
    ):
        return "rate-limit"

    # Budget / quota / billing exhaustion
    if (
        "402" in msg
        or "insufficient_quota" in msg
        or "quota" in msg
        or "billing" in msg
        or "credits" in msg
        or "budget" in msg
        or "payment" in msg
        or "plan limit" in msg
    ):
        return "budget"

    # Everything else: connectivity, timeout, DNS, server errors
    return "unreachable"


def _api_fallback_allowed(stt: SpeechToText) -> bool:
    return stt.backend_name in {"openai", "xai", "gemini"}


def _create_cpu_whisper_fallback() -> SpeechToText:
    from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText

    return FasterWhisperSpeechToText(model_name="base", device="cpu", compute_type="int8")


def _fallback_notice_message(stt: SpeechToText, primary_error: Exception | None) -> str:
    if primary_error is None:
        return f"Using on-device fallback (degraded mode)"
    return (
        f"{_backend_label(stt)} transcription failed; "
        "used faster-whisper/base on CPU for this turn. "
        f"API error: {_short_error(primary_error)}"
    )


def _fallback_error_message(
    stt: SpeechToText,
    *,
    primary_error: Exception | None,
    fallback_error: Exception,
) -> str:
    if primary_error is None:
        return f"CPU fallback failed: {_short_error(fallback_error)}"
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
