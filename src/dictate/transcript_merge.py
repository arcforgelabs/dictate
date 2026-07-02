"""Helpers for stitching streamed transcript chunks."""

from __future__ import annotations

import string

MAX_OVERLAP_WORDS = 12

# Strip surrounding punctuation for the seam comparison only (not the output).
_PUNCT = string.punctuation


def _normalize_word(word: str) -> str:
    """Case- and surrounding-punctuation-insensitive form for overlap comparison."""
    return word.strip(_PUNCT).casefold()


def merge_transcript_piece(previous_tail: str, new_text: str, *, max_overlap_words: int = MAX_OVERLAP_WORDS) -> str:
    """Return ``new_text`` with any word overlap against ``previous_tail`` removed.

    The overlap comparison is case- and surrounding-punctuation-insensitive so a
    seam word that differs only in casing/punctuation across a chunk boundary
    (e.g. "jumps." vs "Jumps") is still deduped. The returned remainder preserves
    the original casing/punctuation of ``new_text``; only the comparison is normalized.
    """
    cleaned = new_text.strip()
    if not cleaned:
        return ""
    tail = previous_tail.strip()
    if not tail:
        return cleaned
    prev_words = tail.split()
    new_words = cleaned.split()
    prev_norm = [_normalize_word(word) for word in prev_words]
    new_norm = [_normalize_word(word) for word in new_words]
    limit = min(max_overlap_words, len(prev_words), len(new_words))
    for overlap in range(limit, 0, -1):
        if prev_norm[-overlap:] == new_norm[:overlap]:
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
