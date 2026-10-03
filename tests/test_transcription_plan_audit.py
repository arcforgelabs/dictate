from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
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
    def test_audit_has_no_meeting_or_gpu_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_minimal_plan(root)
            _write_scripts(root)
            _write_benchmark(
                root / "benchmark-results" / "parakeet-v2-cpu-flite-long-3x-gated.json",
                device="cpu",
                rtfx=10.0,
            )

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["canonical_plan"].status, "pass")
        self.assertEqual(gates["benchmark_fixture_tooling"].status, "pass")
        self.assertEqual(gates["update_scope_decision"].status, "pass")
        self.assertFalse(audit_module.has_blockers(gates.values()))
        # Meeting was removed (#140) and CPU is the only device: neither gates readiness.
        self.assertNotIn("meeting_speaker_attribution", gates)
        self.assertFalse({name for name in gates if name.startswith(("cuda_", "amd_"))})

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

            items = audit_module.readiness_report(audit_module.audit(root))

        self.assertTrue(items)
        self.assertEqual({item.status for item in items}, {"ready"})
        self.assertNotIn("Meeting", [item.name for item in items])

    def test_fixture_tooling_gate_requires_no_gpu_tooling(self) -> None:
        source = AUDIT_PATH.read_text(encoding="utf-8").lower()
        for gpu_marker in ("cuda", "amd", "directml", "dmlexecutionprovider", "gpu"):
            self.assertNotIn(gpu_marker, source)

    def test_fixture_tooling_gate_requires_no_meeting_tooling(self) -> None:
        source = AUDIT_PATH.read_text(encoding="utf-8").lower()
        for marker in ("meeting", "pyannote", "diarizen", "sortformer", "diariz"):
            self.assertNotIn(marker, source)

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

            gates = {gate.name: gate for gate in audit_module.audit(root)}

        self.assertEqual(gates["update_scope_decision"].status, "fail")
        self.assertIn("Staged update preparation", gates["update_scope_decision"].detail)


class RepositoryPlanReadinessTests(unittest.TestCase):
    """Run the audit against this checkout's real plan and scripts."""

    def test_plan_checklist_names_exactly_the_reported_items(self) -> None:
        plan = (ROOT / "docs" / "TRANSCRIPTION_PLAN.md").read_text(encoding="utf-8")
        section = plan.split("## Human-Test Acceptance Checklist", 1)[1].split("\n## ", 1)[0]
        checklist = re.findall(r"^\d+\.\s+\*\*(.+?):\*\*", section, re.MULTILINE)
        items = audit_module.readiness_report(audit_module.audit(ROOT))

        self.assertEqual(checklist, [item.name for item in items])
        for name in checklist:
            self.assertNotRegex(name, r"(?i)nvidia|amd|cuda|gpu|meeting")

    def test_readiness_report_on_this_checkout(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = audit_module.main(["--readiness", "--root", str(ROOT)])
        report = output.getvalue()
        # Shown in the CI log as the readiness transcript for the tested commit.
        print("\ntranscription_plan_audit.py --readiness on this checkout:\n" + report, file=sys.stderr)

        self.assertEqual(exit_code, 0)
        statuses = {
            line[9:].split("  ", 1)[0].strip(): line[:9].strip()
            for line in report.splitlines()
            if line.strip()
        }
        self.assertEqual(
            list(statuses),
            ["CPU English", "Plain recording", "Windows VM", "Packaging", "Regression"],
        )
        # Every item is decided by files tracked in Git.
        for name, status in statuses.items():
            self.assertEqual(status, "READY", name)


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
        "generate-long-benchmark-fixtures.sh",
        "import-transcription-evidence.py",
        "run-human-test-readiness.sh",
        "run-human-test-readiness.ps1",
    ]:
        (scripts / name).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    runner_text = (
        "#!/usr/bin/env bash\n"
        "# --skip-preflight doctor --stt-backend parakeet "
        "cpu-human --fixture-class --device cpu\n"
        if preflighted_runner
        else "#!/usr/bin/env bash\n"
    )
    (scripts / "run-transcription-lane-benchmarks.sh").write_text(runner_text, encoding="utf-8")
    readiness_runner_text = (
        "#!/usr/bin/env bash\n"
        "# transcription_plan_audit.py --readiness dictate doctor dictate --once\n"
    )
    (scripts / "run-human-test-readiness.sh").write_text(
        readiness_runner_text,
        encoding="utf-8",
    )
    readiness_runner_ps1_text = (
        "# transcription_plan_audit.py --readiness -m dictate doctor "
        "-m dictate --once\n"
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
            "promotion-status.txt cpu-parakeet-v2 machine.txt "
            "parakeet-v2-cpu-human-gated.json\n"
        )
    (scripts / "collect-transcription-evidence.sh").write_text(collector_text, encoding="utf-8")
    ps_collector_text = "param()\n"
    if evidence_collector:
        ps_collector_text += (
            "# benchmark-results/*.json transcription_plan_audit.py --json "
            "lane-runner-dry-run.txt human-lane-dry-run.txt lane-readiness.txt "
            "promotion-status.txt cpu-parakeet-v2 machine.txt Compress-Archive "
            "parakeet-v2-cpu-flite-long-3x-gated.json "
            "parakeet-v2-cpu-human-gated.json\n"
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
                    "segment_boundary_pair_count": boundary_pairs,
                },
                "gates": [{"name": "mean_rtf", "passed": True}],
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
