"""Server-side xAI transcription relay for Dictate Pro."""

from __future__ import annotations

import json
import math
import os
import wave
from dataclasses import dataclass
from pathlib import Path

from dictate.pro.store import TranscriptSegmentRow
from dictate.stt.xai_backend import _extract_diarized_text, _keyterms, _post_multipart


@dataclass(slots=True)
class RelayResult:
    text: str
    segments: list[TranscriptSegmentRow]
    audio_duration_seconds: float
    billable_seconds: int
    provider_request_id: str | None
    raw_response: dict[str, object]


def relay_api_key() -> str:
    key = os.environ.get("DICTATE_PRO_XAI_API_KEY") or os.environ.get("XAI_API_KEY")
    if not key:
        raise RuntimeError("DICTATE_PRO_XAI_API_KEY is not configured on the relay.")
    return key.strip()


def audio_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate() or 1
        return frames / float(rate)


def billable_seconds_for_duration(duration_seconds: float) -> int:
    return max(1, int(math.ceil(duration_seconds)))


def transcribe_meeting_file(
    path: Path,
    *,
    language: str | None = None,
    hotwords: str | None = None,
    diarize: bool = True,
    api_key: str | None = None,
) -> RelayResult:
    duration = audio_duration_seconds(path)
    fields: list[tuple[str, str]] = []
    if diarize:
        fields.append(("diarize", "true"))
    if language:
        fields.extend([("format", "true"), ("language", language)])
    for keyterm in _keyterms(hotwords):
        fields.append(("keyterm", keyterm))

    timeout = max(30, min(900, int(duration * 10) + 30))
    base_url = os.environ.get("DICTATE_XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
    response_text = _post_multipart(
        url=f"{base_url}/stt",
        api_key=api_key or relay_api_key(),
        file_path=path,
        fields=fields,
        timeout=timeout,
    )
    payload = _parse_json(response_text)
    text = _extract_diarized_text(response_text) if diarize else _extract_plain_text(response_text)
    segments = parse_transcript_segments(payload, fallback_text=text)
    provider_request_id = _provider_request_id(payload)
    billable = billable_seconds_for_duration(duration)
    return RelayResult(
        text=text,
        segments=segments,
        audio_duration_seconds=duration,
        billable_seconds=billable,
        provider_request_id=provider_request_id,
        raw_response=payload,
    )


def _parse_json(response_text: str) -> dict[str, object]:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _extract_plain_text(response_text: str) -> str:
    payload = _parse_json(response_text)
    text = payload.get("text")
    return text.strip() if isinstance(text, str) else response_text.strip()


def _provider_request_id(payload: dict[str, object]) -> str | None:
    for key in ("id", "request_id", "requestId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_transcript_segments(payload: dict[str, object], *, fallback_text: str) -> list[TranscriptSegmentRow]:
    words = payload.get("words")
    if not isinstance(words, list):
        return [
            TranscriptSegmentRow(
                seq=0,
                speaker_id="0",
                speaker_label="Speaker 1",
                text=fallback_text,
                t_start=0.0,
                t_end=0.0,
            )
        ]

    speaker_labels: dict[object, str] = {}
    turns: list[tuple[object, list[dict[str, object]], float, float]] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        text = word.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        speaker = word.get("speaker", 0)
        if speaker not in speaker_labels:
            speaker_labels[speaker] = f"Speaker {len(speaker_labels) + 1}"
        start = _float_or(word.get("start"), 0.0)
        end = _float_or(word.get("end"), start)
        if not turns or turns[-1][0] != speaker:
            turns.append((speaker, [word], start, end))
        else:
            turns[-1][1].append(word)
            turns[-1] = (speaker, turns[-1][1], turns[-1][2], end)

    segments: list[TranscriptSegmentRow] = []
    for seq, (speaker, pieces, start, end) in enumerate(turns):
        text = " ".join(
            piece.get("text", "").strip()
            for piece in pieces
            if isinstance(piece.get("text"), str) and piece.get("text", "").strip()
        ).strip()
        if not text:
            continue
        segments.append(
            TranscriptSegmentRow(
                seq=seq,
                speaker_id=str(speaker),
                speaker_label=speaker_labels[speaker],
                text=text,
                t_start=start,
                t_end=end,
            )
        )
    if segments:
        return segments
    return [
        TranscriptSegmentRow(
            seq=0,
            speaker_id="0",
            speaker_label="Speaker 1",
            text=fallback_text,
            t_start=0.0,
            t_end=0.0,
        )
    ]


def _float_or(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
