from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path

from dictate.benchmark import load_manifest


class BenchmarkFixtureGeneratorTests(unittest.TestCase):
    def test_transcription_lane_runner_dry_run_lists_canonical_artifacts(self) -> None:
        command = _shell_script_command("scripts/run-transcription-lane-benchmarks.sh")
        completed = subprocess.run(
            [*command, "--dry-run"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout
        for artifact in [
            "parakeet-v2-cpu-flite-long-3x-gated.json",
            "parakeet-v2-cuda-flite-long-3x-gated.json",
            "parakeet-v3-cuda-flite-long-3x-gated.json",
            "parakeet-v2-amd-flite-long-3x-gated.json",
            "parakeet-v3-amd-flite-long-3x-gated.json",
            "parakeet-pyannote-cuda-flite-meeting.json",
            "parakeet-diarizen-cuda-flite-meeting.json",
            "parakeet-sortformer-cuda-flite-meeting.json",
        ]:
            self.assertIn(artifact, output)
        self.assertIn("doctor --stt-backend parakeet --model parakeet-tdt-0.6b-v2 --device amd", output)
        self.assertIn(
            "doctor --stt-backend parakeet-pyannote --model parakeet-tdt-0.6b-v2 --device cuda",
            output,
        )
        self.assertIn(
            "doctor --stt-backend parakeet-diarizen --model parakeet-tdt-0.6b-v2 --device cuda",
            output,
        )
        self.assertIn(
            "doctor --stt-backend parakeet-sortformer --model parakeet-tdt-0.6b-v2 --device cuda",
            output,
        )
        self.assertIn("--require-speaker-attribution", output)
        self.assertIn("--require-der-metrics", output)
        self.assertIn("--max-mean-wer 0.60", output)

    def test_curated_human_fixture_generator_is_registered_for_cuda_promotion(self) -> None:
        text = Path("scripts/generate-curated-human-asr-fixture.sh").read_text(encoding="utf-8")
        self.assertIn("Open Speech Repository", text)
        self.assertIn("OSR_us_000_0010_8k.wav", text)
        self.assertIn("Harvard Sentences List 1", text)
        self.assertIn("manifest.csv", text)

    def test_curated_human_meeting_fixture_generator_is_registered_for_meeting_promotion(self) -> None:
        text = Path("scripts/generate-curated-human-meeting-fixture.sh").read_text(encoding="utf-8")
        self.assertIn("Open Speech Repository", text)
        self.assertIn("OSR_us_000_0010_8k.wav", text)
        self.assertIn("OSR_us_000_0030_8k.wav", text)
        self.assertIn("Speaker 1", text)
        self.assertIn("Speaker 2", text)

    def test_transcription_lane_runner_can_select_amd_only(self) -> None:
        command = _shell_script_command("scripts/run-transcription-lane-benchmarks.sh")
        completed = subprocess.run(
            [*command, "--lane", "amd", "--dry-run"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--device amd", completed.stdout)
        self.assertIn("parakeet-v2-amd-flite-long-3x-gated.json", completed.stdout)
        self.assertNotIn("parakeet-v2-cuda-flite-long-3x-gated.json", completed.stdout)

    def test_amd_promotion_runner_dry_run_lists_required_human_artifacts(self) -> None:
        command = _shell_script_command("scripts/run-amd-promotion-benchmarks.sh")
        completed = subprocess.run(
            [*command, "--dry-run", "--collect-evidence"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("generate-curated-human-asr-fixture.sh", completed.stdout)
        self.assertIn("--lane amd-human", completed.stdout)
        self.assertIn("--lane amd-human-v3", completed.stdout)
        self.assertIn("transcription_plan_audit.py", completed.stdout)
        self.assertIn("collect-transcription-evidence.sh", completed.stdout)

    def test_windows_amd_promotion_runner_contains_required_markers(self) -> None:
        text = Path("scripts/run-amd-promotion-benchmarks.ps1").read_text(encoding="utf-8")
        for marker in [
            "parakeet-v2-amd-human-gated.json",
            "parakeet-v3-amd-human-gated.json",
            "DmlExecutionProvider",
            "pip\", \"install\", \"-e\", \".[amd]",
            "NoInstallAmdExtra",
            "DICTATE_HUMAN_MANIFEST",
            "collect-transcription-evidence.ps1",
            "transcription_plan_audit.py",
        ]:
            self.assertIn(marker, text)

    def test_human_test_readiness_wrappers_contain_manual_smoke_markers(self) -> None:
        shell_text = Path("scripts/run-human-test-readiness.sh").read_text(encoding="utf-8")
        for marker in [
            "transcription_plan_audit.py --readiness",
            "dictate doctor",
            "dictate --once",
            "run-amd-promotion-benchmarks.sh",
            "real audio",
        ]:
            self.assertIn(marker, shell_text)

        ps_text = Path("scripts/run-human-test-readiness.ps1").read_text(encoding="utf-8")
        for marker in [
            "transcription_plan_audit.py",
            "--readiness",
            "-m dictate doctor",
            "-m dictate --once",
            "run-amd-promotion-benchmarks.ps1",
            "real audio",
        ]:
            self.assertIn(marker, ps_text)

    def test_transcription_lane_runner_can_skip_preflight_for_failure_artifacts(self) -> None:
        command = _shell_script_command("scripts/run-transcription-lane-benchmarks.sh")
        completed = subprocess.run(
            [*command, "--lane", "meeting", "--skip-preflight", "--dry-run"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn(" doctor ", completed.stdout)
        self.assertIn("parakeet-pyannote-cuda-flite-meeting.json", completed.stdout)

    def test_transcription_evidence_collector_dry_run_lists_handoff_bundle_contents(self) -> None:
        command = _shell_script_command("scripts/collect-transcription-evidence.sh")
        completed = subprocess.run(
            [*command, "--dry-run"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout
        self.assertIn("benchmark-results/*.json", output)
        self.assertIn("audit.json", output)
        self.assertIn("lane-runner-dry-run.txt", output)
        self.assertIn("human-lane-dry-run.txt", output)
        self.assertIn("lane-readiness.txt", output)
        self.assertIn("promotion-status.txt", output)
        self.assertIn("machine.txt", output)
        self.assertNotIn("TOKEN", output.upper())

    def test_import_transcription_evidence_dry_run_reads_zip_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "transcription-evidence-test"
            results = bundle_root / "benchmark-results"
            results.mkdir(parents=True)
            (results / "parakeet-v2-amd-human-gated.json").write_text(
                '{"config":{"device":"amd"},"summary":{"mean_rtfx":12}}',
                encoding="utf-8",
            )
            archive = root / "bundle.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.write(
                    results / "parakeet-v2-amd-human-gated.json",
                    "transcription-evidence-test/benchmark-results/parakeet-v2-amd-human-gated.json",
                )
            repo = root / "repo"
            repo.mkdir()

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/import-transcription-evidence.py",
                    str(archive),
                    "--repo-root",
                    str(repo),
                    "--dry-run",
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("would import", completed.stdout)
            self.assertFalse((repo / "benchmark-results" / "parakeet-v2-amd-human-gated.json").exists())

    def test_import_transcription_evidence_reads_tar_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_root = root / "transcription-evidence-test"
            results = bundle_root / "benchmark-results"
            results.mkdir(parents=True)
            artifact = results / "parakeet-v3-amd-human-gated.json"
            artifact.write_text(
                '{"config":{"device":"amd"},"summary":{"mean_rtfx":12}}',
                encoding="utf-8",
            )
            archive = root / "bundle.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(bundle_root, arcname="transcription-evidence-test")
            repo = root / "repo"
            repo.mkdir()

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/import-transcription-evidence.py",
                    str(archive),
                    "--repo-root",
                    str(repo),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            imported = repo / "benchmark-results" / artifact.name
            self.assertTrue(imported.exists())
            self.assertEqual(imported.read_text(encoding="utf-8"), artifact.read_text(encoding="utf-8"))

    def test_import_transcription_evidence_rejects_malformed_benchmark_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "bundle"
            results = bundle / "benchmark-results"
            results.mkdir(parents=True)
            (results / "parakeet-v2-amd-human-gated.json").write_text(
                '{"config":{"device":"amd"}}',
                encoding="utf-8",
            )
            repo = root / "repo"
            repo.mkdir()

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/import-transcription-evidence.py",
                    str(bundle),
                    "--repo-root",
                    str(repo),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 2)
            self.assertIn("missing object field: summary", completed.stderr)
            self.assertFalse((repo / "benchmark-results" / "parakeet-v2-amd-human-gated.json").exists())

    def test_import_transcription_evidence_preserves_existing_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "bundle"
            results = bundle / "benchmark-results"
            results.mkdir(parents=True)
            artifact = results / "parakeet-v2-amd-human-gated.json"
            artifact.write_text(
                '{"config":{"device":"amd"},"summary":{"mean_rtfx":12}}',
                encoding="utf-8",
            )
            repo = root / "repo"
            destination = repo / "benchmark-results"
            destination.mkdir(parents=True)
            target = destination / artifact.name
            target.write_text('{"old": true}', encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/import-transcription-evidence.py",
                    str(bundle),
                    "--repo-root",
                    str(repo),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("skip existing", completed.stdout)
            self.assertEqual(target.read_text(encoding="utf-8"), '{"old": true}')

    def test_windows_transcription_evidence_collector_contains_handoff_markers(self) -> None:
        text = Path("scripts/collect-transcription-evidence.ps1").read_text(encoding="utf-8")
        for marker in [
            "benchmark-results/*.json",
            "transcription_plan_audit.py --json",
            "lane-runner-dry-run.txt",
            "human-lane-dry-run.txt",
            "lane-readiness.txt",
            "promotion-status.txt",
            "cuda-parakeet-v2",
            "meeting-sortformer",
            "machine.txt",
            "Compress-Archive",
            "parakeet-v2-amd-flite-long-3x-gated.json",
            "parakeet-v3-amd-flite-long-3x-gated.json",
            "parakeet-pyannote-cuda-flite-meeting.json",
            "parakeet-diarizen-cuda-flite-meeting.json",
            "parakeet-sortformer-cuda-flite-meeting.json",
            "parakeet-v2-cuda-human-gated.json",
            "parakeet-v3-cuda-human-gated.json",
            "parakeet-v2-amd-human-gated.json",
            "parakeet-v3-amd-human-gated.json",
            "parakeet-pyannote-cuda-human-meeting.json",
            "parakeet-diarizen-cuda-human-meeting.json",
            "parakeet-sortformer-cuda-human-meeting.json",
        ]:
            self.assertIn(marker, text)
        self.assertNotIn("Get-ChildItem Env:", text)

    def test_gitignore_excludes_default_evidence_bundle_directory(self) -> None:
        ignored = Path(".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("evidence-bundles/", ignored)

    def test_generate_long_fixtures_writes_repeat_manifest_for_gpu_comparison(self) -> None:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            self.skipTest("ffmpeg and ffprobe are required for fixture generation")

        script = Path("scripts/generate-long-benchmark-fixtures.sh")
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "long"
            completed = subprocess.run(
                [str(script), str(out_dir)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            if completed.returncode != 0 and "flite" in completed.stderr:
                self.skipTest(completed.stderr.strip())
            self.assertEqual(completed.returncode, 0, completed.stderr)

            manifest = out_dir / "manifest-3x.csv"
            samples = load_manifest(manifest, out_dir, limit=0)
            audio = out_dir / "flite_long.wav"
            with wave.open(str(audio), "rb") as handle:
                duration_s = handle.getnframes() / float(handle.getframerate())

        self.assertEqual([sample.sample_id for sample in samples], ["flite_long_1", "flite_long_2", "flite_long_3"])
        self.assertGreater(duration_s, 30.0)
        self.assertTrue(all(sample.audio_path.name == "flite_long.wav" for sample in samples))
        self.assertTrue(all(sample.reference_segments for sample in samples))
        for sample in samples:
            assert sample.reference_segments is not None
            self.assertEqual(len(sample.reference_segments), 1)
            self.assertAlmostEqual(sample.reference_segments[0].t_start or 0.0, 0.0)
            self.assertGreater(sample.reference_segments[0].t_end or 0.0, 30.0)

    def test_generate_meeting_fixtures_writes_timestamped_speaker_manifest(self) -> None:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            self.skipTest("ffmpeg and ffprobe are required for fixture generation")

        script = Path("scripts/generate-meeting-benchmark-fixtures.sh")
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "meeting"
            completed = subprocess.run(
                [str(script), str(out_dir)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            if completed.returncode != 0 and "flite" in completed.stderr:
                self.skipTest(completed.stderr.strip())
            self.assertEqual(completed.returncode, 0, completed.stderr)

            manifest = out_dir / "manifest.csv"
            samples = load_manifest(manifest, out_dir, limit=0)

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].sample_id, "flite_meeting")
        assert samples[0].reference_segments is not None
        self.assertEqual(
            [segment.speaker_label for segment in samples[0].reference_segments],
            ["Speaker 1", "Speaker 2", "Speaker 1"],
        )
        self.assertTrue(
            all(
                segment.t_start is not None
                and segment.t_end is not None
                and segment.t_end > segment.t_start
                for segment in samples[0].reference_segments
            )
        )

    def test_generate_curated_human_meeting_fixture_writes_timestamped_speaker_manifest(self) -> None:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None or shutil.which("curl") is None:
            self.skipTest("curl, ffmpeg, and ffprobe are required for curated fixture generation")

        script = Path("scripts/generate-curated-human-meeting-fixture.sh")
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "meeting"
            completed = subprocess.run(
                [str(script), str(out_dir)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            manifest = out_dir / "manifest.csv"
            samples = load_manifest(manifest, out_dir, limit=0)

        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].sample_id, "osr_harvard_two_speaker_meeting")
        assert samples[0].reference_segments is not None
        self.assertEqual(
            [segment.speaker_label for segment in samples[0].reference_segments],
            ["Speaker 1", "Speaker 1", "Speaker 1", "Speaker 2", "Speaker 2", "Speaker 2"],
        )
        self.assertIn("Paint the sockets in the wall dull green.", samples[0].reference)
        self.assertNotIn("The small pup gnawed a hole in the sock.", samples[0].reference)
        self.assertTrue(
            all(
                segment.t_start is not None
                and segment.t_end is not None
                and segment.t_end > segment.t_start
                for segment in samples[0].reference_segments
            )
        )


def _shell_script_command(path: str) -> list[str]:
    script = Path(path)
    if sys.platform.startswith("win"):
        bash = shutil.which("bash")
        if bash is None:
            raise unittest.SkipTest("bash is required to run shell script dry-run tests on Windows")
        return [bash, str(script)]
    return [str(script)]


if __name__ == "__main__":
    unittest.main()
