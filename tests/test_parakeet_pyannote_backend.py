from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dictate.stt.parakeet_pyannote_backend import (
    PYANNOTE_COMMUNITY_MODEL,
    ParakeetPyannoteSpeechToText,
    SpeakerTurn,
    _annotation_turns,
    _format_labelled_turns,
    pyannote_model_source,
    pyannote_token,
)
from dictate.stt.parakeet_speaker_backend import _coerce_turns
from dictate.stt.base import TranscriptSegment


class _FakeSegment:
    def __init__(self, start: float, end: float) -> None:
        self.start = start
        self.end = end


class _FakeAnnotation:
    def itertracks(self, yield_label: bool = False):  # noqa: ANN201
        assert yield_label is True
        yield _FakeSegment(1.0, 2.0), None, "SPEAKER_02"
        yield _FakeSegment(0.0, 1.0), None, "SPEAKER_01"


class _FakeDiarization:
    exclusive_speaker_diarization = _FakeAnnotation()


class _FakeAsr:
    def __init__(self) -> None:
        self.segment_lengths: list[int] = []
        self.released = False

    def transcribe(self, audio, **_kwargs):  # noqa: ANN001, ANN201
        self.segment_lengths.append(len(audio))
        return f"text-{len(audio)}"

    def release(self) -> None:
        self.released = True


class _FakeSegmentAsr(_FakeAsr):
    def transcribe_segments(self, audio, **_kwargs):  # noqa: ANN001, ANN201
        self.segment_lengths.append(len(audio))
        return [
            TranscriptSegment(text=f"first-{len(audio)}", t_start=0.1, t_end=0.4),
            TranscriptSegment(text=f"second-{len(audio)}", t_start=0.5, t_end=0.9),
        ]


class ParakeetPyannoteBackendTests(unittest.TestCase):
    def test_env_token_priority(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DICTATE_HF_TOKEN": "dictate-token",
                "HUGGINGFACE_HUB_TOKEN": "hub-token",
                "HF_TOKEN": "hf-token",
            },
            clear=True,
        ):
            self.assertEqual(pyannote_token(), "dictate-token")

    def test_token_falls_back_to_huggingface_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_path = Path(temp_dir) / "token"
            token_path.write_text("cached-token\n", encoding="utf-8")
            with (
                patch.dict(os.environ, {"HF_HOME": temp_dir}, clear=True),
                patch("dictate.stt.parakeet_pyannote_backend.Path.home", return_value=Path(temp_dir)),
            ):
                self.assertEqual(pyannote_token(), "cached-token")

    def test_model_source_defaults_to_community_model(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(pyannote_model_source(), PYANNOTE_COMMUNITY_MODEL)

    def test_model_source_prefers_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"DICTATE_PYANNOTE_MODEL_PATH": temp_dir}, clear=True):
                self.assertEqual(pyannote_model_source(), temp_dir)

    def test_annotation_turns_uses_exclusive_itertracks(self) -> None:
        self.assertEqual(
            _annotation_turns(_FakeAnnotation()),
            [
                SpeakerTurn(start=0.0, end=1.0, speaker="SPEAKER_01"),
                SpeakerTurn(start=1.0, end=2.0, speaker="SPEAKER_02"),
            ],
        )

    def test_annotation_turns_accepts_serialized_list(self) -> None:
        self.assertEqual(
            _annotation_turns(
                [
                    {"start": 2, "end": 3, "speaker": "b"},
                    {"start": 0, "end": 1, "speaker": "a"},
                ]
            ),
            [
                SpeakerTurn(start=0.0, end=1.0, speaker="a"),
                SpeakerTurn(start=2.0, end=3.0, speaker="b"),
            ],
        )

    def test_coerce_turns_accepts_sortformer_segment_lines(self) -> None:
        self.assertEqual(
            _coerce_turns(["1.20 2.30 speaker_1", "0.00 0.90 speaker_0"]),
            [
                SpeakerTurn(start=0.0, end=0.9, speaker="speaker_0"),
                SpeakerTurn(start=1.2, end=2.3, speaker="speaker_1"),
            ],
        )

    def test_format_labelled_turns_groups_consecutive_speaker_text(self) -> None:
        self.assertEqual(
            _format_labelled_turns(
                [
                    ("Speaker 1", "hello"),
                    ("Speaker 1", "again"),
                    ("Speaker 2", "reply"),
                ]
            ),
            "Speaker 1: hello again\nSpeaker 2: reply",
        )

    def test_factory_shape_without_loading_heavy_runtime(self) -> None:
        stt = ParakeetPyannoteSpeechToText(
            model_name="parakeet-tdt-0.6b-v3",
            device="cuda",
            compute_type="int8",
        )
        self.assertEqual(stt.backend_name, "parakeet-pyannote")
        self.assertEqual(stt.model_name, "parakeet-tdt-0.6b-v3")
        self.assertTrue(stt.capabilities.supports_speaker_attribution)

    def test_transcribe_diarized_uses_speaker_turn_segments(self) -> None:
        stt = ParakeetPyannoteSpeechToText()
        fake_asr = _FakeAsr()
        stt._asr = fake_asr  # type: ignore[assignment]
        stt._pipeline = lambda _path: _FakeDiarization()

        out = stt.transcribe_diarized(np.ones(32000, dtype=np.float32))

        self.assertEqual(fake_asr.segment_lengths, [16000, 16000])
        self.assertEqual(out, "Speaker 1: text-16000\nSpeaker 2: text-16000")

    def test_transcribe_diarized_segments_offsets_parakeet_subsegment_timestamps(self) -> None:
        stt = ParakeetPyannoteSpeechToText()
        fake_asr = _FakeSegmentAsr()
        stt._asr = fake_asr  # type: ignore[assignment]
        stt._pipeline = lambda _path: [
            {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
            {"start": 2.0, "end": 3.0, "speaker": "SPEAKER_02"},
        ]

        segments = stt.transcribe_diarized_segments(np.ones(48000, dtype=np.float32))

        self.assertEqual(fake_asr.segment_lengths, [16000, 16000])
        self.assertEqual([segment.speaker_label for segment in segments], ["Speaker 1", "Speaker 1", "Speaker 2", "Speaker 2"])
        self.assertEqual([segment.text for segment in segments], ["first-16000", "second-16000", "first-16000", "second-16000"])
        self.assertAlmostEqual(segments[0].t_start or 0.0, 1.1)
        self.assertAlmostEqual(segments[0].t_end or 0.0, 1.4)
        self.assertAlmostEqual(segments[2].t_start or 0.0, 2.1)
        self.assertAlmostEqual(segments[3].t_end or 0.0, 2.9)

    def test_transcribe_diarized_segments_clamps_turns_to_audio_duration(self) -> None:
        stt = ParakeetPyannoteSpeechToText()
        fake_asr = _FakeAsr()
        stt._asr = fake_asr  # type: ignore[assignment]
        stt._pipeline = lambda _path: [{"start": -1.0, "end": 3.0, "speaker": "SPEAKER_01"}]

        segments = stt.transcribe_diarized_segments(np.ones(16000, dtype=np.float32))

        self.assertEqual(fake_asr.segment_lengths, [16000])
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].t_start, 0.0)
        self.assertEqual(segments[0].t_end, 1.0)

    def test_transcribe_diarized_falls_back_to_plain_asr_without_turns(self) -> None:
        stt = ParakeetPyannoteSpeechToText()
        fake_asr = _FakeAsr()
        stt._asr = fake_asr  # type: ignore[assignment]
        stt._pipeline = lambda _path: []

        out = stt.transcribe_diarized(np.ones(16000, dtype=np.float32))

        self.assertEqual(out, "text-16000")

    def test_missing_token_for_remote_model_fails_loudly(self) -> None:
        stt = ParakeetPyannoteSpeechToText()
        fake_pyannote = types.ModuleType("pyannote")
        fake_audio = types.ModuleType("pyannote.audio")
        fake_audio.Pipeline = object
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.dict(os.environ, {"HF_HOME": temp_dir}, clear=True),
                patch("dictate.stt.parakeet_pyannote_backend.Path.home", return_value=Path(temp_dir)),
                patch.dict(sys.modules, {"pyannote": fake_pyannote, "pyannote.audio": fake_audio}),
            ):
                with self.assertRaisesRegex(RuntimeError, "requires a Hugging Face token"):
                    stt._pyannote_pipeline()

    def test_local_model_path_does_not_require_token(self) -> None:
        fake_pipeline = object()

        class _FakePipeline:
            @staticmethod
            def from_pretrained(model_ref: str, token: str | None = None):  # noqa: ANN205
                calls.append((model_ref, token))
                return fake_pipeline

        calls: list[tuple[str, str | None]] = []
        fake_pyannote = types.ModuleType("pyannote")
        fake_audio = types.ModuleType("pyannote.audio")
        fake_audio.Pipeline = _FakePipeline
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.dict(os.environ, {"DICTATE_PYANNOTE_MODEL_PATH": temp_dir}, clear=True),
                patch.dict(sys.modules, {"pyannote": fake_pyannote, "pyannote.audio": fake_audio}),
            ):
                stt = ParakeetPyannoteSpeechToText(device="cpu")
                self.assertIs(stt._pyannote_pipeline(), fake_pipeline)

        self.assertEqual(calls, [(str(Path(temp_dir)), None)])

    def test_release_clears_pipeline_and_releases_asr(self) -> None:
        stt = ParakeetPyannoteSpeechToText()
        fake_asr = _FakeAsr()
        stt._asr = fake_asr  # type: ignore[assignment]
        stt._pipeline = object()

        stt.release()

        self.assertTrue(fake_asr.released)
        self.assertIsNone(stt._pipeline)


if __name__ == "__main__":
    unittest.main()
