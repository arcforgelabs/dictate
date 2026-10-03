from __future__ import annotations

import contextlib
import csv
import io
import json
import tempfile
import unittest
import wave
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dictate import benchmark
from dictate.benchmark import (
    _run_from_args,
    build_parser,
    load_manifest,
    segment_boundary_mae_s,
)
from dictate.stt import SttCapabilities, TranscriptSegment


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
    capabilities = SttCapabilities()

    @property
    def model(self) -> str:
        return "loaded"

    def transcribe_segments(self, audio, language=None, hotwords=None):  # noqa: ANN001, ANN201
        del audio, language, hotwords
        raise RuntimeError("model load failed")


def _args(manifest: Path, root: Path, **overrides) -> Namespace:
    values = dict(
        manifest=str(manifest),
        audio_root=str(root),
        stt_backend="parakeet",
        model="parakeet-tdt-0.6b-v2",
        device="cpu",
        language="en",
        hotwords=None,
        limit=0,
        json_output=None,
        run_label="unit",
        max_mean_wer=None,
        max_mean_rtf=None,
        max_mean_segment_boundary_mae_s=None,
        require_timestamp_metrics=False,
    )
    values.update(overrides)
    return Namespace(**values)


_TIMED_MANIFEST = (
    "id,audio,text,segments_json\n"
    "sample,sample.wav,hello world,"
    "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":0.5},"
    "{\"\"text\"\":\"\"world\"\",\"\"start\"\":0.5,\"\"end\"\":1}]\"\n"
)


class BenchmarkTests(unittest.TestCase):
    def test_segment_boundary_mae(self) -> None:
        reference = [
            TranscriptSegment(text="hello", t_start=0.0, t_end=0.5),
            TranscriptSegment(text="world", t_start=0.5, t_end=1.0),
        ]
        hypothesis = [
            TranscriptSegment(text="hello", t_start=0.1, t_end=0.6),
            TranscriptSegment(text="world", t_start=0.6, t_end=1.2),
        ]
        self.assertAlmostEqual(segment_boundary_mae_s(reference, hypothesis) or 0, 0.125)

    def test_meeting_options_and_metrics_are_gone(self) -> None:
        # Meeting capture and its speaker benchmarks were removed (#140).
        for name in ("diarization_error_rate", "speaker_confusion_rate", "parse_speaker_labelled_text"):
            self.assertFalse(hasattr(benchmark, name), name)
        for option in ("--diarize", "--require-speaker-attribution", "--max-mean-der", "--require-der-metrics"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    build_parser().parse_args(["--manifest", "m.csv", option])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["--manifest", "m.csv", "--stt-backend", "parakeet-pyannote"])

    def test_load_manifest_reads_reference_segments_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.csv"
            # A speaker key from an older Meeting fixture is ignored, not an error.
            segments = [{"text": "hello", "start": 0.0, "end": 0.5, "speaker": "Speaker 1"}]
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
            self.assertEqual(samples[0].reference_segments[0].text, "hello")
            self.assertEqual(samples[0].reference_segments[0].t_end, 0.5)

    def test_run_benchmark_passes_quality_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_test_wav(root / "sample.wav")
            manifest = root / "manifest.csv"
            manifest.write_text(_TIMED_MANIFEST, encoding="utf-8")
            json_output = root / "report.json"
            args = _args(
                manifest,
                root,
                json_output=str(json_output),
                run_label="unit-gated",
                max_mean_wer=0.6,
                max_mean_rtf=999.0,
                max_mean_segment_boundary_mae_s=0.0,
                require_timestamp_metrics=True,
            )

            with (
                patch(
                    "dictate.benchmark.create_speech_to_text",
                    return_value=_FakePlainSegmentBenchmarkStt(),
                ),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 0)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(report["run_label"], "unit-gated")
            self.assertEqual(report["config"]["backend"], "parakeet")
            self.assertNotIn("diarize", report["config"])
            self.assertNotIn("mean_der", report["summary"])
            self.assertNotIn("onnxruntime_providers", report["environment"])
            self.assertIn("machine", report["environment"])
            self.assertTrue(all(gate["passed"] for gate in report["gates"]))
            self.assertEqual(report["summary"]["segment_boundary_pair_count"], 4)

    def test_run_benchmark_fails_when_timestamp_metrics_required_but_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_test_wav(root / "sample.wav")
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "sample,sample.wav,hello world,"
                "\"[{\"\"text\"\":\"\"hello\"\"},{\"\"text\"\":\"\"world\"\"}]\"\n",
                encoding="utf-8",
            )
            json_output = root / "report.json"
            args = _args(
                manifest,
                root,
                json_output=str(json_output),
                run_label="unit-gated-missing-timestamps",
                require_timestamp_metrics=True,
            )

            with (
                patch(
                    "dictate.benchmark.create_speech_to_text",
                    return_value=_FakePlainSegmentBenchmarkStt(),
                ),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 2)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            gate = next(gate for gate in report["gates"] if gate["name"] == "manifest_validation")
            self.assertFalse(gate["passed"])
            self.assertIn("timestamped reference segments", gate["value"])

    def test_validate_manifest_only_rejects_generated_fixture_as_curated_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_root = root / "benchmark-fixtures" / "flite-smoke"
            fixture_root.mkdir(parents=True)
            _write_test_wav(fixture_root / "flite_sample.wav")
            manifest = fixture_root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "flite_sample,flite_sample.wav,hello,"
                "\"[{\"\"text\"\":\"\"hello\"\",\"\"start\"\":0,\"\"end\"\":1}]\"\n",
                encoding="utf-8",
            )
            args = _args(
                manifest,
                fixture_root,
                run_label="unit-curated-validation",
                fixture_class="curated-human",
                fixture_notes=None,
                validate_manifest_only=True,
                require_timestamp_metrics=True,
            )

            exit_code = _run_from_args(args)

        self.assertEqual(exit_code, 2)

    def test_validate_manifest_only_accepts_curated_human_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_test_wav(root / "human.wav")
            manifest = root / "manifest.csv"
            manifest.write_text(
                "id,audio,text,segments_json\n"
                "human_1,human.wav,hello world,"
                "\"[{\"\"text\"\":\"\"hello world\"\",\"\"start\"\":0,\"\"end\"\":1}]\"\n",
                encoding="utf-8",
            )
            args = _args(
                manifest,
                root,
                run_label="unit-curated-validation",
                fixture_class="curated-human",
                fixture_notes="unit test human-style fixture",
                validate_manifest_only=True,
                require_timestamp_metrics=True,
            )

            exit_code = _run_from_args(args)

        self.assertEqual(exit_code, 0)

    def test_run_benchmark_writes_json_report_for_runtime_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_test_wav(root / "sample.wav")
            manifest = root / "manifest.csv"
            manifest.write_text(_TIMED_MANIFEST, encoding="utf-8")
            json_output = root / "report.json"
            args = _args(
                manifest,
                root,
                json_output=str(json_output),
                run_label="unit-runtime-failure",
                require_timestamp_metrics=True,
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
            self.assertIn("model load failed", report["summary"]["error"])
            self.assertEqual(report["gates"][0]["name"], "benchmark_runtime")
            self.assertFalse(report["gates"][0]["passed"])

    def test_run_benchmark_uses_plain_timestamp_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_test_wav(root / "sample.wav")
            manifest = root / "manifest.csv"
            manifest.write_text(_TIMED_MANIFEST, encoding="utf-8")
            json_output = root / "report.json"
            args = _args(
                manifest,
                root,
                json_output=str(json_output),
                run_label="unit-plain-timestamps",
                max_mean_wer=0.0,
                max_mean_rtf=999.0,
                max_mean_segment_boundary_mae_s=0.0,
                require_timestamp_metrics=True,
            )

            with (
                patch(
                    "dictate.benchmark.create_speech_to_text",
                    return_value=_FakePlainSegmentBenchmarkStt(),
                ),
                patch("dictate.benchmark.resolve_model_name", return_value="parakeet-tdt-0.6b-v2"),
            ):
                exit_code = _run_from_args(args)

            self.assertEqual(exit_code, 0)
            report = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(report["samples"][0]["hypothesis"], "hello\nworld")
            self.assertEqual(report["samples"][0]["segment_boundary_pair_count"], 4)
            self.assertNotIn("diarization_error_rate", report["samples"][0])
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
