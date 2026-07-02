from __future__ import annotations

import unittest

from dictate.transcript_merge import merge_transcript_piece, prompt_tail


class TranscriptMergeTests(unittest.TestCase):
    def test_merge_removes_overlapping_words(self) -> None:
        merged = merge_transcript_piece("the quick brown", "brown fox jumps")
        self.assertEqual(merged, "fox jumps")

    def test_merge_dedup_is_case_and_punctuation_insensitive(self) -> None:
        merged = merge_transcript_piece(
            "the quick brown fox jumps.",
            "Fox jumps over the lazy dog",
        )
        self.assertEqual(merged, "over the lazy dog")

    def test_merge_preserves_original_casing_of_remainder(self) -> None:
        merged = merge_transcript_piece("hello there", "There Bob SHOUTS loudly")
        self.assertEqual(merged, "Bob SHOUTS loudly")

    def test_prompt_tail_limits_length(self) -> None:
        text = " ".join(f"word{i}" for i in range(80))
        tail = prompt_tail(text, max_chars=40)
        self.assertLessEqual(len(tail), 40)
        self.assertTrue(tail)
