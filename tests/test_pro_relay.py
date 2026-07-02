"""Tests for xAI relay segment parsing."""

from __future__ import annotations

import unittest

from dictate.pro.relay import billable_seconds_for_duration, parse_transcript_segments


class ProRelayTests(unittest.TestCase):
    def test_parse_words_into_segments(self) -> None:
        payload = {
            "text": "hello there",
            "words": [
                {"text": "hello", "speaker": 0, "start": 0.0, "end": 0.4},
                {"text": "there", "speaker": 0, "start": 0.5, "end": 0.9},
                {"text": "yes", "speaker": 1, "start": 1.0, "end": 1.3},
            ],
        }
        segments = parse_transcript_segments(payload, fallback_text="hello there")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].speaker_label, "Speaker 1")
        self.assertEqual(segments[1].speaker_label, "Speaker 2")

    def test_billable_seconds_round_up(self) -> None:
        self.assertEqual(billable_seconds_for_duration(0.2), 1)
        self.assertEqual(billable_seconds_for_duration(61.0), 61)


if __name__ == "__main__":
    unittest.main()
