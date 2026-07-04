from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts" / "transcription_plan_audit.py"
spec = importlib.util.spec_from_file_location("transcription_plan_audit", AUDIT_PATH)
assert spec is not None and spec.loader is not None
audit_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = audit_module
spec.loader.exec_module(audit_module)


class TranscriptionPlanAuditTests(unittest.TestCase):
    def test_audit_reports_synthetic_cuda_pass_and_external_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_meeting_failure(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["canonical_plan"].status, "pass")
        self.assertEqual(gates["benchmark_fixture_tooling"].status, "pass")
        self.assertEqual(gates["cuda_vs_cpu_synthetic"].status, "pass")
        self.assertEqual(gates["cuda_multilingual_synthetic"].status, "pass")
        self.assertEqual(gates["cuda_human_promotion"].status, "blocked")
        self.assertEqual(gates["meeting_speaker_attribution"].status, "blocked")
        self.assertIn("parakeet-pyannote", gates["meeting_speaker_attribution"].detail)
        self.assertIn("parakeet-diarizen", gates["meeting_speaker_attribution"].detail)
        self.assertIn("parakeet-sortformer", gates["meeting_speaker_attribution"].detail)
        self.assertEqual(gates["amd_radeon_performance"].status, "blocked")
        self.assertEqual(gates["update_scope_decision"].status, "pass")
        self.assertTrue(audit_module.has_blockers(gates.values()))

    def test_audit_accepts_promoted_meeting_and_amd_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-human-gated.json",
                device="cuda",
                rtfx=14.0,
                model="parakeet-tdt-0.6b-v2",
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-human-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-amd-human-gated.json",
                device="amd",
                rtfx=12.0,
                model="parakeet-tdt-0.6b-v2",
                boundary_pairs=4,
                fixture_class="curated-human",
                amd_hardware=True,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-amd-human-gated.json",
                device="amd",
                rtfx=13.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
                fixture_class="curated-human",
                amd_hardware=True,
            )
            _write_meeting_success(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["cuda_human_promotion"].status, "pass")
        self.assertEqual(gates["meeting_speaker_attribution"].status, "pass")
        self.assertEqual(gates["amd_radeon_performance"].status, "pass")

    def test_readiness_report_maps_missing_amd_artifacts_to_human_test_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-human-gated.json",
                device="cuda",
                rtfx=14.0,
                model="parakeet-tdt-0.6b-v2",
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-human-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_meeting_failure(root)
            _write_single_meeting_success(root, "parakeet-sortformer")

            items = {item.name: item for item in audit_module.readiness_report(audit_module.audit(root))}

        self.assertEqual(items["NVIDIA English"].status, "ready")
        self.assertEqual(items["NVIDIA multilingual"].status, "ready")
        self.assertEqual(items["Meeting"].status, "ready")
        self.assertEqual(items["AMD English"].status, "blocked")
        self.assertEqual(items["AMD multilingual"].status, "blocked")
        self.assertIn("parakeet-v2-amd-human-gated.json", items["AMD English"].detail)

    def test_readiness_report_marks_all_acceptance_items_ready_when_gates_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-human-gated.json",
                device="cuda",
                rtfx=14.0,
                model="parakeet-tdt-0.6b-v2",
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-human-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-amd-human-gated.json",
                device="amd",
                rtfx=12.0,
                model="parakeet-tdt-0.6b-v2",
                boundary_pairs=4,
                fixture_class="curated-human",
                amd_hardware=True,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-amd-human-gated.json",
                device="amd",
                rtfx=13.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
                fixture_class="curated-human",
                amd_hardware=True,
            )
            _write_meeting_success(root)

            items = audit_module.readiness_report(audit_module.audit(root))

        self.assertTrue(items)
        self.assertEqual({item.status for item in items}, {"ready"})

    def test_audit_accepts_one_promoted_meeting_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_meeting_failure(root)
            _write_single_meeting_success(root, "parakeet-sortformer")

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["meeting_speaker_attribution"].status, "pass")
        self.assertIn("parakeet-sortformer DER", gates["meeting_speaker_attribution"].detail)
        self.assertIn("remaining candidates", gates["meeting_speaker_attribution"].detail)

    def test_audit_rejects_single_generic_amd_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-amd-radeon.json",
                device="amd",
                rtfx=12.0,
                boundary_pairs=4,
            )
            _write_meeting_success(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["amd_radeon_performance"].status, "blocked")
        self.assertIn("parakeet-v2-amd-human-gated.json", gates["amd_radeon_performance"].detail)

    def test_audit_rejects_amd_artifacts_without_amd_hardware_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-human-gated.json",
                device="cuda",
                rtfx=14.0,
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-human-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-amd-human-gated.json",
                device="amd",
                rtfx=12.0,
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-amd-human-gated.json",
                device="amd",
                rtfx=13.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
                fixture_class="curated-human",
            )
            _write_meeting_success(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["amd_radeon_performance"].status, "blocked")
        self.assertIn("no AMD/Radeon hardware provenance", gates["amd_radeon_performance"].detail)

    def test_audit_rejects_lane_runner_without_preflight_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root, preflighted_runner=False)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_meeting_failure(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["benchmark_fixture_tooling"].status, "fail")
        self.assertIn("--skip-preflight", gates["benchmark_fixture_tooling"].detail)

    def test_audit_rejects_evidence_collector_without_required_bundle_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root, evidence_collector=False)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_meeting_failure(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["benchmark_fixture_tooling"].status, "fail")
        self.assertIn("evidence collector", gates["benchmark_fixture_tooling"].detail)

    def test_audit_rejects_evidence_collector_output_that_is_not_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            (root / ".gitignore").write_text("benchmark-results/\n", encoding="utf-8")
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_meeting_failure(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["benchmark_fixture_tooling"].status, "fail")
        self.assertIn("evidence-bundles", gates["benchmark_fixture_tooling"].detail)

    def test_audit_rejects_windows_plan_without_no_bundle_build_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root, include_build=False)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_meeting_failure(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["windows_vm_package_evidence"].status, "fail")
        self.assertIn("mode build --timeout 1800", gates["windows_vm_package_evidence"].detail)

    def test_audit_rejects_plan_without_update_scope_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root, include_update_scope=False)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=14.0,
            )
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v3-cuda-flite-long-3x-gated.json",
                device="cuda",
                rtfx=15.0,
                model="parakeet-tdt-0.6b-v3",
                boundary_pairs=4,
            )
            _write_meeting_failure(root)

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["update_scope_decision"].status, "fail")
        self.assertIn("Staged update preparation", gates["update_scope_decision"].detail)


def _write_minimal_plan(
    root: Path,
    *,
    include_build: bool = True,
    include_update_scope: bool = True,
) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True)
    (root / ".gitignore").write_text("evidence-bundles/\n", encoding="utf-8")
    build_markers = [
        "mode build --timeout 1800",
        "dictate-ui-shell.exe",
        "engine\\dictate-engine.exe",
    ] if include_build else []
    update_markers = [
        "Staged update preparation is deferred out of the human-test release.",
        "The human-test release uses the tested immediate source update path",
        "post-update doctor again reported Parakeet v2",
    ] if include_update_scope else []
    (docs / "TRANSCRIPTION_PLAN.md").write_text(
        "\n".join(
            [
                "## Deployable Goal",
                "## Human-Test Acceptance Checklist",
                "Deployment blockers before calling this plan complete:",
                "mode install --timeout 1800",
                "mode lifecycle --timeout 2400",
                *build_markers,
                *update_markers,
                "mode amd --timeout 1800",
                "mode msix --timeout 2400",
                "evidence collector dry-run",
                "314",
                "196",
                "ArcForgeDictate_2026.7.4.0_x64.msix",
            ]
        ),
        encoding="utf-8",
    )


def _write_scripts(
    root: Path,
    *,
    preflighted_runner: bool = True,
    evidence_collector: bool = True,
) -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for name in [
        "generate-benchmark-fixtures.sh",
        "generate-curated-human-asr-fixture.sh",
        "generate-curated-human-meeting-fixture.sh",
        "generate-long-benchmark-fixtures.sh",
        "generate-meeting-benchmark-fixtures.sh",
        "import-transcription-evidence.py",
        "run-amd-promotion-benchmarks.sh",
        "run-amd-promotion-benchmarks.ps1",
        "run-human-test-readiness.sh",
        "run-human-test-readiness.ps1",
    ]:
        (scripts / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    runner_text = (
        "#!/usr/bin/env bash\n"
        "# --skip-preflight doctor --stt-backend parakeet-pyannote "
        "--stt-backend parakeet-diarizen --stt-backend parakeet-sortformer "
        "cuda-human amd-human meeting-human --fixture-class --device amd\n"
        if preflighted_runner
        else "#!/usr/bin/env bash\n"
    )
    (scripts / "run-transcription-lane-benchmarks.sh").write_text(runner_text, encoding="utf-8")
    amd_runner_text = (
        "#!/usr/bin/env bash\n"
        "# generate-curated-human-asr-fixture.sh amd-human amd-human-v3 "
        "transcription_plan_audit.py collect-transcription-evidence.sh\n"
    )
    (scripts / "run-amd-promotion-benchmarks.sh").write_text(
        amd_runner_text,
        encoding="utf-8",
    )
    amd_runner_ps1_text = (
        "# parakeet-v2-amd-human-gated.json parakeet-v3-amd-human-gated.json "
        "DmlExecutionProvider transcription_plan_audit.py collect-transcription-evidence.ps1\n"
    )
    (scripts / "run-amd-promotion-benchmarks.ps1").write_text(
        amd_runner_ps1_text,
        encoding="utf-8",
    )
    readiness_runner_text = (
        "#!/usr/bin/env bash\n"
        "# transcription_plan_audit.py --readiness dictate doctor dictate --once "
        "run-amd-promotion-benchmarks.sh\n"
    )
    (scripts / "run-human-test-readiness.sh").write_text(
        readiness_runner_text,
        encoding="utf-8",
    )
    readiness_runner_ps1_text = (
        "# transcription_plan_audit.py --readiness -m dictate doctor "
        "-m dictate --once run-amd-promotion-benchmarks.ps1\n"
    )
    (scripts / "run-human-test-readiness.ps1").write_text(
        readiness_runner_ps1_text,
        encoding="utf-8",
    )
    collector_text = "#!/usr/bin/env bash\n"
    if evidence_collector:
        collector_text += (
            "# benchmark-results/*.json transcription_plan_audit.py --json "
            "lane-runner-dry-run.txt human-lane-dry-run.txt lane-readiness.txt "
            "promotion-status.txt cuda-parakeet-v2 meeting-sortformer machine.txt "
            "parakeet-v2-cuda-human-gated.json parakeet-v2-amd-human-gated.json "
            "parakeet-pyannote-cuda-human-meeting.json\n"
        )
    (scripts / "collect-transcription-evidence.sh").write_text(collector_text, encoding="utf-8")
    ps_collector_text = "param()\n"
    if evidence_collector:
        ps_collector_text += (
            "# benchmark-results/*.json transcription_plan_audit.py --json "
            "lane-runner-dry-run.txt human-lane-dry-run.txt lane-readiness.txt "
            "promotion-status.txt cuda-parakeet-v2 meeting-sortformer machine.txt Compress-Archive "
            "parakeet-v2-amd-flite-long-3x-gated.json "
            "parakeet-diarizen-cuda-flite-meeting.json "
            "parakeet-sortformer-cuda-flite-meeting.json "
            "parakeet-v2-cuda-human-gated.json parakeet-v2-amd-human-gated.json "
            "parakeet-pyannote-cuda-human-meeting.json\n"
        )
    (scripts / "collect-transcription-evidence.ps1").write_text(ps_collector_text, encoding="utf-8")


def _write_benchmark(
    path: Path,
    *,
    device: str,
    rtfx: float,
    model: str = "parakeet-tdt-0.6b-v2",
    boundary_pairs: int = 0,
    fixture_class: str = "synthetic",
    amd_hardware: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "config": {"device": device, "model": model, "fixture_class": fixture_class},
                "summary": {
                    "samples": 1,
                    "completed_samples": 1,
                    "mean_rtfx": rtfx,
                    "mean_der": None,
                    "segment_boundary_pair_count": boundary_pairs,
                },
                "gates": [{"name": "mean_rtf", "passed": True}],
                "environment": _benchmark_environment(amd_hardware=amd_hardware),
            }
        ),
        encoding="utf-8",
    )


def _benchmark_environment(*, amd_hardware: bool = False) -> dict[str, object]:
    if amd_hardware:
        return {
            "onnxruntime_providers": ["DmlExecutionProvider", "CPUExecutionProvider"],
            "gpu_summary": ["AMD Radeon RX 7800 XT"],
        }
    return {
        "onnxruntime_providers": ["CPUExecutionProvider"],
        "gpu_summary": ["NVIDIA GeForce RTX 4090"],
    }


def _write_meeting_failure(root: Path) -> None:
    for backend in ("parakeet-pyannote", "parakeet-diarizen", "parakeet-sortformer"):
        path = root / "benchmark-results" / f"{backend}-cuda-human-meeting.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "config": {"backend": backend, "device": "cuda", "diarize": True},
                    "summary": {"mean_der": None},
                    "gates": [{"name": "benchmark_runtime", "passed": False}],
                }
            ),
            encoding="utf-8",
        )


def _write_meeting_success(root: Path) -> None:
    for backend in ("parakeet-pyannote", "parakeet-diarizen", "parakeet-sortformer"):
        _write_single_meeting_success(root, backend)


def _write_single_meeting_success(root: Path, backend: str) -> None:
    path = root / "benchmark-results" / f"{backend}-cuda-human-meeting.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "config": {
                    "backend": backend,
                    "device": "cuda",
                    "diarize": True,
                    "require_speaker_attribution": True,
                    "fixture_class": "curated-human",
                },
                "summary": {
                    "samples": 1,
                    "completed_samples": 1,
                    "mean_der": 0.1,
                    "segment_boundary_pair_count": 4,
                },
                "gates": [{"name": "mean_der", "passed": True}],
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
