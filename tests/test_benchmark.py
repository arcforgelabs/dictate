from __future__ import annotations

import csv
import json
import tempfile
import unittest
import wave
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dictate.benchmark import (
    _run_from_args,
    diarization_error_rate,
    load_manifest,
    parse_speaker_labelled_text,
    segment_boundary_mae_s,
    speaker_confusion_rate,
)
from dictate.stt import SttCapabilities, TranscriptSegment


class _FakeBenchmarkStt:
    backend_name = "fake"
    model_name = "fake-model"
    capabilities = SttCapabilities(supports_speaker_attribution=True)

    @property
    def model(self) -> str:
        return "loaded"

    def transcribe(self, audio, language=None, hotwords=None):  # noqa: ANN001, ANN201
        del audio, language, hotwords
        return "hello world"

    def transcribe_diarized_segments(
        self,
        audio,
        language=None,
        hotwords=None,
    ):  # noqa: ANN001, ANN201
        del audio, language, hotwords
        return [
            TranscriptSegment(
                text="hello",
                t_start=0.0,
                t_end=0.5,
                speaker_label="Speaker 1",
            ),
            TranscriptSegment(
                text="world",
                t_start=0.5,
                t_end=1.0,
                speaker_label="Speaker 2",
            ),
        ]


class _FakePlainSegmentBenchmarkStt:
    backend_name = "fake-plain-segments"
    model_name = "fake-model"
    capabilities = SttCapabilities(supports_word_timestamps=True)

    @property
    def model(self) -> str:
        return "loaded"

    def transcribe(self, audio, language=None, hotwords=None):  # noqa: ANN001, ANN201
        del audio, language, hotwords
        return "plain fallback"

    def transcribe_segments(self, audio, language=None, hotwords=None):  # noqa: ANN001, ANN201
        del audio, language, hotwords
        return [
            TranscriptSegment(text="hello", t_start=0.0, t_end=0.5),
            TranscriptSegment(text="world", t_start=0.5, t_end=1.0),
        ]


class _FailingBenchmarkStt:
    backend_name = "failing"
    model_name = "fake-model"
    capabilities = SttCapabilities(supports_speaker_attribution=True)

    @property
    def model(self) -> str:
        return "loaded"

    def transcribe_diarized_segments(
        self,
        audio,
        language=None,
        hotwords=None,
    ):  # noqa: ANN001, ANN201
        del audio, language, hotwords
        raise RuntimeError("missing speaker model")


class BenchmarkTests(unittest.TestCase):
    def test_parse_speaker_labelled_text(self) -> None:
        segments = parse_speaker_labelled_text("Speaker 1: hello\nSpeaker 2: reply")
        assert segments is not None
        self.assertEqual(
            [segment.speaker_label for segment in segments],
            ["Speaker 1", "Speaker 2"],
        )
        self.assertEqual([segment.text for segment in segments], ["hello", "reply"])

    def test_segment_metrics(self) -> None:
        reference = [
            TranscriptSegment(text="hello", t_start=0.0, t_end=0.5, speaker_label="A"),
            TranscriptSegment(text="world", t_start=0.5, t_end=1.0, speaker_label="B"),
        ]
        hypothesis = [
            TranscriptSegment(text="hello", t_start=0.1, t_end=0.6, speaker_label="A"),
            TranscriptSegment(text="world", t_start=0.6, t_end=1.2, speaker_label="C"),
        ]
        self.assertAlmostEqual(speaker_confusion_rate(reference, hypothesis) or 0.0, 1.0 / 9.0)
        self.assertAlmostEqual(segment_boundary_mae_s(reference, hypothesis) or 0, 0.125)

    def test_speaker_confusion_uses_time_overlap_not_segment_index(self) -> None:
        reference = [
            TranscriptSegment(text="one", t_start=0.0, t_end=2.0, speaker_label="Speaker 1"),
            TranscriptSegment(text="two", t_start=2.5, t_end=4.5, speaker_label="Speaker 2"),
        ]
        hypothesis = [
            TranscriptSegment(text="a", t_start=0.1, t_end=0.8, speaker_label="speaker_0"),
            TranscriptSegment(text="b", t_start=1.0, t_end=1.8, speaker_label="speaker_0"),
            TranscriptSegment(text="c", t_start=2.6, t_end=3.2, speaker_label="speaker_1"),
            TranscriptSegment(text="d", t_start=3.4, t_end=4.4, speaker_label="speaker_1"),
        ]

        self.assertEqual(speaker_confusion_rate(reference, hypothesis), 0.0)

    def test_segment_boundary_stats_match_split_speaker_segments_by_overlap(self) -> None:
        reference = [
            TranscriptSegment(text="one", t_start=0.0, t_end=2.0, speaker_label="Speaker 1"),
            TranscriptSegment(text="two", t_start=2.5, t_end=4.5, speaker_label="Speaker 2"),
        ]
        hypothesis = [
            TranscriptSegment(text="a", t_start=0.1, t_end=0.8, speaker_label="speaker_0"),
            TranscriptSegment(text="b", t_start=1.0, t_end=1.9, speaker_label="speaker_0"),
            TranscriptSegment(text="c", t_start=2.6, t_end=3.2, speaker_label="speaker_1"),
            TranscriptSegment(text="d", t_start=3.4, t_end=4.4, speaker_label="speaker_1"),
        ]

        self.assertAlmostEqual(segment_boundary_mae_s(reference, hypothesis) or 0.0, 0.1)

    def test_diarization_error_rate_uses_best_speaker_mapping(self) -> None:
        reference = [
            TranscriptSegment(text="hello", t_start=0.0, t_end=1.0, speaker_label="Speaker 1"),
            TranscriptSegment(text="world", t_start=1.0, t_end=2.0, speaker_label="Speaker 2"),
        ]
        renamed_hypothesis = [
            TranscriptSegment(text="hello", t_start=0.0, t_end=1.0, speaker_label="SPEAKER_00"),
            TranscriptSegment(text="world", t_start=1.0, t_end=2.0, speaker_label="SPEAKER_01"),
        ]
        confused_hypothesis = [
            TranscriptSegment(text="hello", t_start=0.0, t_end=2.0, speaker_label="SPEAKER_00"),
        ]

        self.assertEqual(diarization_error_rate(reference, renamed_hypothesis), 0.0)
        self.assertEqual(diarization_error_rate(reference, confused_hypothesis), 0.5)

    def test_load_manifest_reads_reference_segments_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.csv"
            segments = [
                {
                    "text": "hello",
                    "start": 0.0,
                    "end": 0.5,
                    "speaker": "Speaker 1",
                }
            ]
            with manifest.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "audio", "text", "segments_json"])
                writer.writeheader()
                writer.writerow(
                    {
                        "id": "sample",
                        "audio": "sample.wav",
                        "text": "hello",
                        "segments_json": json.dumps(segments),
                    }
                )

            samples = load_manifest(manifest, root, limit=0)

            self.assertEqual(samples[0].sample_id, "sample")
            assert samples[0].reference_segments is not None
            self.assertEqual(samples[0].reference_segments[0].speaker_label, "Speaker 1")
            self.assertEqual(samples[0].reference_segments[0].t_end, 0.5)

    def test_run_benchmark_writes_json_report_for_diarized_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_path = root / "sample.wav"
            _write_test_wav(wav_path)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "sample,sample.wav,Speaker 1: hello Speaker 2: world,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":0.5,"
                "\"\"speaker\"\":\"\"Speaker 1\"\"},{\"\"text\"\":\"\"world\"\","
                "\"\"start\"\":0.5,\"\"end\"\":1,\"\"speaker\"\":\"\"Speaker 2\"\"}]\"\n",
                encoding="utf-8",
            )
            json_output = root / "report.json"
            args = Namespace(
                manifest=str(manifest),
                audio_root=str(root),
                stt_backend="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                device="cpu",
                language="en",
                hotwords=None,
                limit=0,
                diarize=True,
                require_speaker_attribution=True,
                json_output=str(json_output),
                run_label="unit",
                max_mean_wer=None,
                max_mean_rtf=None,
                max_mean_der=None,
                max_mean_speaker_confusion_rate=None,
                max_mean_segment_boundary_mae_s=None,
                require_timestamp_metrics=False,
                require_der_metrics=False,
            )

            with (
                patch("dictate.benchmark.create_speech_to_text", return_value=_FakeBenchmarkStt()),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 0)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(report["run_label"], "unit")
            self.assertEqual(report["config"]["backend"], "parakeet-pyannote")
            self.assertTrue(report["config"]["diarize"])
            self.assertIn("onnxruntime_providers", report["environment"])
            self.assertIn("machine", report["environment"])
            self.assertEqual(report["summary"]["samples"], 1)
            self.assertEqual(
                report["samples"][0]["hypothesis_segments"][0]["speaker_label"],
                "Speaker 1",
            )
            self.assertEqual(report["summary"]["mean_der"], 0.0)
            self.assertEqual(report["samples"][0]["diarization_error_rate"], 0.0)
            self.assertEqual(report["samples"][0]["speaker_confusion_rate"], 0.0)
            self.assertEqual(report["samples"][0]["segment_boundary_mae_s"], 0.0)
            self.assertEqual(report["samples"][0]["segment_boundary_pair_count"], 4)

    def test_run_benchmark_passes_quality_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_path = root / "sample.wav"
            _write_test_wav(wav_path)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "sample,sample.wav,Speaker 1: hello Speaker 2: world,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":0.5,"
                "\"\"speaker\"\":\"\"Speaker 1\"\"},{\"\"text\"\":\"\"world\"\","
                "\"\"start\"\":0.5,\"\"end\"\":1,\"\"speaker\"\":\"\"Speaker 2\"\"}]\"\n",
                encoding="utf-8",
            )
            json_output = root / "report.json"
            args = Namespace(
                manifest=str(manifest),
                audio_root=str(root),
                stt_backend="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                device="cpu",
                language="en",
                hotwords=None,
                limit=0,
                diarize=True,
                require_speaker_attribution=True,
                json_output=str(json_output),
                run_label="unit-gated",
                max_mean_wer=0.6,
                max_mean_rtf=999.0,
                max_mean_der=0.0,
                max_mean_speaker_confusion_rate=0.0,
                max_mean_segment_boundary_mae_s=0.0,
                require_timestamp_metrics=True,
                require_der_metrics=True,
            )

            with (
                patch("dictate.benchmark.create_speech_to_text", return_value=_FakeBenchmarkStt()),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 0)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertTrue(all(gate["passed"] for gate in report["gates"]))
            self.assertEqual(report["summary"]["segment_boundary_pair_count"], 4)
            self.assertEqual(report["summary"]["mean_der"], 0.0)

    def test_run_benchmark_fails_when_timestamp_metrics_required_but_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_path = root / "sample.wav"
            _write_test_wav(wav_path)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "sample,sample.wav,Speaker 1: hello Speaker 2: world,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"speaker\"\":\"\"Speaker 1\"\"},"
                "{\"\"text\"\":\"\"world\"\",\"\"speaker\"\":\"\"Speaker 2\"\"}]\"\n",
                encoding="utf-8",
            )
            json_output = root / "report.json"
            args = Namespace(
                manifest=str(manifest),
                audio_root=str(root),
                stt_backend="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                device="cpu",
                language="en",
                hotwords=None,
                limit=0,
                diarize=True,
                require_speaker_attribution=True,
                json_output=str(json_output),
                run_label="unit-gated-missing-timestamps",
                max_mean_wer=None,
                max_mean_rtf=None,
                max_mean_der=None,
                max_mean_speaker_confusion_rate=None,
                max_mean_segment_boundary_mae_s=None,
                require_timestamp_metrics=True,
                require_der_metrics=False,
            )

            with (
                patch("dictate.benchmark.create_speech_to_text", return_value=_FakeBenchmarkStt()),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 2)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            gate = next(gate for gate in report["gates"] if gate["name"] == "manifest_validation")
            self.assertFalse(gate["passed"])
            self.assertIn("timestamped reference segments", gate["value"])

    def test_run_benchmark_fails_when_der_metrics_required_but_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_path = root / "sample.wav"
            _write_test_wav(wav_path)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "sample,sample.wav,hello world,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":0.5},"
                "{\"\"text\"\":\"\"world\"\",\"\"start\"\":0.5,\"\"end\"\":1}]\"\n",
                encoding="utf-8",
            )
            json_output = root / "report.json"
            args = Namespace(
                manifest=str(manifest),
                audio_root=str(root),
                stt_backend="parakeet",
                model="parakeet-tdt-0.6b-v2",
                device="cpu",
                language="en",
                hotwords=None,
                limit=0,
                diarize=False,
                require_speaker_attribution=False,
                json_output=str(json_output),
                run_label="unit-missing-der",
                max_mean_wer=None,
                max_mean_rtf=None,
                max_mean_der=None,
                max_mean_speaker_confusion_rate=None,
                max_mean_segment_boundary_mae_s=None,
                require_timestamp_metrics=False,
                require_der_metrics=True,
            )

            with (
                patch("dictate.benchmark.create_speech_to_text", return_value=_FakePlainSegmentBenchmarkStt()),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 2)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            gate = next(gate for gate in report["gates"] if gate["name"] == "manifest_validation")
            self.assertFalse(gate["passed"])
            self.assertIn("timestamped speaker reference segments", gate["value"])

    def test_validate_manifest_only_rejects_generated_fixture_as_curated_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_root = root / "benchmark-fixtures" / "flite-smoke"
            fixture_root.mkdir(parents=True)
            wav_path = fixture_root / "flite_sample.wav"
            _write_test_wav(wav_path)
            manifest = fixture_root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "flite_sample,flite_sample.wav,hello,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":1}]\"\n",
                encoding="utf-8",
            )
            args = Namespace(
                manifest=str(manifest),
                audio_root=str(fixture_root),
                stt_backend="parakeet",
                model="parakeet-tdt-0.6b-v2",
                device="cpu",
                language="en",
                hotwords=None,
                limit=0,
                diarize=False,
                require_speaker_attribution=False,
                json_output=None,
                run_label="unit-curated-validation",
                fixture_class="curated-human",
                fixture_notes=None,
                validate_manifest_only=True,
                max_mean_wer=None,
                max_mean_rtf=None,
                max_mean_der=None,
                max_mean_speaker_confusion_rate=None,
                max_mean_segment_boundary_mae_s=None,
                require_timestamp_metrics=True,
                require_der_metrics=False,
            )

            exit_code = _run_from_args(args)

        self.assertEqual(exit_code, 2)

    def test_validate_manifest_only_accepts_curated_human_meeting_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_path = root / "meeting.wav"
            _write_test_wav(wav_path)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "human_meeting_1,meeting.wav,Speaker 1: hello Speaker 2: world,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":0.5,"
                "\"\"speaker\"\":\"\"Speaker 1\"\"},{\"\"text\"\":\"\"world\"\","
                "\"\"start\"\":0.5,\"\"end\"\":1,\"\"speaker\"\":\"\"Speaker 2\"\"}]\"\n",
                encoding="utf-8",
            )
            args = Namespace(
                manifest=str(manifest),
                audio_root=str(root),
                stt_backend="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                device="cuda",
                language="en",
                hotwords=None,
                limit=0,
                diarize=True,
                require_speaker_attribution=True,
                json_output=None,
                run_label="unit-curated-meeting-validation",
                fixture_class="curated-human",
                fixture_notes="unit test human-style meeting fixture",
                validate_manifest_only=True,
                max_mean_wer=None,
                max_mean_rtf=None,
                max_mean_der=None,
                max_mean_speaker_confusion_rate=None,
                max_mean_segment_boundary_mae_s=None,
                require_timestamp_metrics=True,
                require_der_metrics=True,
            )

            exit_code = _run_from_args(args)

        self.assertEqual(exit_code, 0)

    def test_run_benchmark_writes_json_report_for_runtime_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_path = root / "sample.wav"
            _write_test_wav(wav_path)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "sample,sample.wav,Speaker 1: hello,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":1,"
                "\"\"speaker\"\":\"\"Speaker 1\"\"}]\"\n",
                encoding="utf-8",
            )
            json_output = root / "report.json"
            args = Namespace(
                manifest=str(manifest),
                audio_root=str(root),
                stt_backend="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                device="cuda",
                language="en",
                hotwords=None,
                limit=0,
                diarize=True,
                require_speaker_attribution=True,
                json_output=str(json_output),
                run_label="unit-runtime-failure",
                max_mean_wer=None,
                max_mean_rtf=None,
                max_mean_der=None,
                max_mean_speaker_confusion_rate=None,
                max_mean_segment_boundary_mae_s=None,
                require_timestamp_metrics=True,
                require_der_metrics=True,
            )

            with (
                patch("dictate.benchmark.create_speech_to_text", return_value=_FailingBenchmarkStt()),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 2)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["failed_sample"], "sample")
            self.assertEqual(report["summary"]["completed_samples"], 0)
            self.assertIn("missing speaker model", report["summary"]["error"])
            self.assertEqual(report["gates"][0]["name"], "benchmark_runtime")
            self.assertFalse(report["gates"][0]["passed"])

    def test_run_benchmark_uses_plain_timestamp_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_path = root / "sample.wav"
            _write_test_wav(wav_path)
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "sample,sample.wav,hello world,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":0.5},"
                "{\"\"text\"\":\"\"world\"\",\"\"start\"\":0.5,\"\"end\"\":1}]\"\n",
                encoding="utf-8",
            )
            json_output = root / "report.json"
            args = Namespace(
                manifest=str(manifest),
                audio_root=str(root),
                stt_backend="parakeet",
                model="parakeet-tdt-0.6b-v2",
                device="cpu",
                language="en",
                hotwords=None,
                limit=0,
                diarize=False,
                require_speaker_attribution=False,
                json_output=str(json_output),
                run_label="unit-plain-timestamps",
                max_mean_wer=0.0,
                max_mean_rtf=999.0,
                max_mean_der=None,
                max_mean_speaker_confusion_rate=None,
                max_mean_segment_boundary_mae_s=0.0,
                require_timestamp_metrics=True,
                require_der_metrics=False,
            )

            with (
                patch("dictate.benchmark.create_speech_to_text", return_value=_FakePlainSegmentBenchmarkStt()),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 0)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(report["samples"][0]["hypothesis"], "hello\nworld")
            self.assertEqual(report["samples"][0]["segment_boundary_pair_count"], 4)
            self.assertTrue(all(gate["passed"] for gate in report["gates"]))


def _write_test_wav(path: Path) -> None:
    samples = np.zeros(16000, dtype=np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(samples.tobytes())


if __name__ == "__main__":
    unittest.main()
