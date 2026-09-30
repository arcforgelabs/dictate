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
from dictate.stt.base import TranscriptSegment

ResultStatus = Literal["ok", "empty", "too_short", "no_speech", "error"]


@dataclass(slots=True)
class TranscriptionResult:
    status: ResultStatus
    duration_s: float
    text: str = ""
    segments: list[TranscriptSegment] | None = None
    error: str | None = None


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
        require_speaker_attribution: bool = False,
        decode_profile: str = "quality",
    ) -> TranscriptionResult:
        """Transcribe audio on the configured local backend.

        ``decode_profile`` selects the decode params; callers pass "note" for
        note-mode recordings to use the lighter note profile.
        """
        return self._do_transcribe(
            audio,
            language,
            min_duration_s=min_duration_s,
            diarize=diarize,
            require_speaker_attribution=require_speaker_attribution,
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
        require_speaker_attribution: bool,
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
        supports_speaker_attribution = bool(
            getattr(self.stt.capabilities, "supports_speaker_attribution", False)
        )
        if diarize and require_speaker_attribution and not supports_speaker_attribution:
            return TranscriptionResult(
                status="error",
                duration_s=duration,
                error=(
                    f"{self.stt.backend_name} does not support required speaker "
                    "attribution for meeting transcription"
                ),
            )
        try:
            segments: list[TranscriptSegment] | None = None
            segment_transcriber = _defined_method(self.stt, "transcribe_diarized_segments")
            diarized_transcriber = _defined_method(self.stt, "transcribe_diarized")
            if diarize and segment_transcriber is not None:
                segments = segment_transcriber(
                    audio,
                    language=language,
                    hotwords=lexicon_plan.decode_hotwords,
                )
                text = _segments_to_text(segments).strip()
            elif diarize and diarized_transcriber is not None:
                text = diarized_transcriber(
                    audio,
                    language=language,
                    hotwords=lexicon_plan.decode_hotwords,
                ).strip()
            else:
                plain_segment_transcriber = _defined_method(self.stt, "transcribe_segments")
                if plain_segment_transcriber is not None:
                    try:
                        segments = plain_segment_transcriber(
                            audio,
                            language=language,
                            hotwords=lexicon_plan.decode_hotwords,
                            prompt_context=lexicon_plan.prompt_context,
                            decode_profile=decode_profile,
                        )
                    except TypeError:
                        segments = plain_segment_transcriber(
                            audio,
                            language=language,
                            hotwords=lexicon_plan.decode_hotwords,
                            prompt_context=lexicon_plan.prompt_context,
                        )
                    text = _segments_to_text(segments).strip()
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
                        # and is returned as an error result below.
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
            if segments:
                segments = [
                    TranscriptSegment(
                        text=apply_post_corrections(
                            segment.text,
                            hotwords=lexicon_plan.post_hotwords,
                            replacements=lexicon_plan.post_replacements,
                        ).strip(),
                        t_start=segment.t_start,
                        t_end=segment.t_end,
                        speaker_id=segment.speaker_id,
                        speaker_label=segment.speaker_label,
                    )
                    for segment in segments
                ]

        if not text:
            return TranscriptionResult(status="no_speech", duration_s=duration)

        return TranscriptionResult(
            status="ok",
            duration_s=duration,
            text=text,
            segments=segments,
        )

    def release(self) -> None:
        """Release STT resources."""
        self.stt.release()


def _segments_to_text(segments: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    current_speaker: str | None = None
    current_parts: list[str] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        speaker = segment.speaker_label or segment.speaker_id
        if speaker:
            if current_parts and current_speaker != speaker:
                lines.append(_format_segment_line(current_speaker, current_parts))
                current_parts = []
            current_speaker = speaker
            current_parts.append(text)
        else:
            if current_parts:
                lines.append(_format_segment_line(current_speaker, current_parts))
                current_parts = []
                current_speaker = None
            lines.append(text)
    if current_parts:
        lines.append(_format_segment_line(current_speaker, current_parts))
    return "\n".join(line for line in lines if line).strip()


def _format_segment_line(speaker: str | None, parts: list[str]) -> str:
    text = " ".join(part.strip() for part in parts if part.strip()).strip()
    return f"{speaker}: {text}" if speaker else text


def _defined_method(obj: object, name: str):
    if name not in dir(obj):
        return None
    method = getattr(obj, name, None)
    return method if callable(method) else None

