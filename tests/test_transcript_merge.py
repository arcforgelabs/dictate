from __future__ import annotations

import unittest

from dictate.transcript_merge import merge_transcript_piece, prompt_tail


class TranscriptMergeTests(unittest.TestCase):
    def test_merge_removes_overlapping_words(self) -> None:
        merged = merge_transcript_piece("the quick brown", "brown fox jumps")
        self.assertEqual(merged, "fox jumps")

    def test_prompt_tail_limits_length(self) -> None:
        text = " ".join(f"word{i}" for i in range(80))
        tail = prompt_tail(text, max_chars=40)
        self.assertLessEqual(len(tail), 40)
        self.assertTrue(tail)
