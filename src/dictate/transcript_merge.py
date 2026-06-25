"""Helpers for stitching streamed transcript chunks."""

from __future__ import annotations

MAX_OVERLAP_WORDS = 12


def merge_transcript_piece(previous_tail: str, new_text: str, *, max_overlap_words: int = MAX_OVERLAP_WORDS) -> str:
    """Return ``new_text`` with any word overlap against ``previous_tail`` removed."""
    cleaned = new_text.strip()
    if not cleaned:
        return ""
    tail = previous_tail.strip()
    if not tail:
        return cleaned
    prev_words = tail.split()
    new_words = cleaned.split()
    limit = min(max_overlap_words, len(prev_words), len(new_words))
    for overlap in range(limit, 0, -1):
        if prev_words[-overlap:] == new_words[:overlap]:
            remainder = new_words[overlap:]
            return " ".join(remainder).strip()
    return cleaned


def prompt_tail(text: str, *, max_chars: int = 224) -> str:
    """Whisper initial-prompt tail — last words that fit the char budget."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[-max_chars:]
    if " " in clipped:
        return clipped.split(" ", 1)[1]
    return clipped
