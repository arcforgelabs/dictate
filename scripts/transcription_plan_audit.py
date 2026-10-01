#!/usr/bin/env python3
"""Audit local evidence for docs/TRANSCRIPTION_PLAN.md human-test readiness."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Gate:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class ReadinessItem:
    name: str
    status: str
    detail: str
    gates: list[str]


def audit(root: Path) -> list[Gate]:
    root = root.resolve()
    gates = [
        _plan_doc_gate(root),
        _fixture_tooling_gate(root),
        _meeting_promotion_gate(root),
        _windows_vm_evidence_gate(root),
        _update_scope_gate(root),
    ]
    return gates


def has_blockers(gates: Iterable[Gate]) -> bool:
    return any(gate.status in {"missing", "blocked", "fail"} for gate in gates)


def readiness_report(gates: Iterable[Gate]) -> list[ReadinessItem]:
    by_name = {gate.name: gate for gate in gates}

    def status_for(required: list[str]) -> str:
        selected = [by_name[name] for name in required]
        if any(gate.status in {"missing", "blocked", "fail"} for gate in selected):
            return "blocked"
        return "ready"

    def detail_for(required: list[str], ready_detail: str) -> str:
        blockers = [
            f"{gate.name}: {gate.detail}"
            for gate in (by_name[name] for name in required)
            if gate.status in {"missing", "blocked", "fail"}
        ]
        return "; ".join(blockers) if blockers else ready_detail

    items = [
        ReadinessItem(
            name="CPU English",
            status=status_for(["canonical_plan", "benchmark_fixture_tooling"]),
            detail=detail_for(
                ["canonical_plan", "benchmark_fixture_tooling"],
                "Parakeet-first CPU lane and benchmark tooling are documented; run a real microphone smoke on the target machine.",
            ),
            gates=["canonical_plan", "benchmark_fixture_tooling"],
        ),
        ReadinessItem(
            name="Meeting",
            status=status_for(["meeting_speaker_attribution"]),
            detail=detail_for(
                ["meeting_speaker_attribution"],
                "At least one local Meeting lane has curated-human DER, speaker, and timestamp evidence.",
            ),
            gates=["meeting_speaker_attribution"],
        ),
        ReadinessItem(
            name="Plain recording",
            status=status_for(["canonical_plan"]),
            detail=detail_for(
                ["canonical_plan"],
                "Record and push-to-talk share the non-meeting ASR path; run a real microphone smoke on the target machine.",
            ),
            gates=["canonical_plan"],
        ),
        ReadinessItem(
            name="Windows VM",
            status=status_for(["windows_vm_package_evidence"]),
            detail=detail_for(
                ["windows_vm_package_evidence"],
                "Windows install, lifecycle, no-bundle build, and MSIX evidence are documented.",
            ),
            gates=["windows_vm_package_evidence"],
        ),
        ReadinessItem(
            name="Packaging",
            status=status_for(["windows_vm_package_evidence", "update_scope_decision"]),
            detail=detail_for(
                ["windows_vm_package_evidence", "update_scope_decision"],
                "Store/MSIX route is tested and staged updates are explicitly deferred from human testing.",
            ),
            gates=["windows_vm_package_evidence", "update_scope_decision"],
        ),
        ReadinessItem(
            name="Regression",
            status=status_for(["benchmark_fixture_tooling"]),
            detail=detail_for(
                ["benchmark_fixture_tooling"],
                "Run the latest documented Python/UI regression commands before handoff.",
            ),
            gates=["benchmark_fixture_tooling"],
        ),
    ]
    return items


def _plan_doc_gate(root: Path) -> Gate:
    path = root / "docs" / "TRANSCRIPTION_PLAN.md"
    if not path.exists():
        return Gate("canonical_plan", "missing", "docs/TRANSCRIPTION_PLAN.md is missing")
    text = path.read_text(encoding="utf-8")
    required = [
        "## Deployable Goal",
        "## Human-Test Acceptance Checklist",
        "Deployment blockers before calling this plan complete:",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        return Gate("canonical_plan", "fail", f"missing sections: {', '.join(missing)}")
    return Gate("canonical_plan", "pass", "canonical deployment goal and blockers are documented")


def _fixture_tooling_gate(root: Path) -> Gate:
    scripts = [
        "scripts/collect-transcription-evidence.ps1",
        "scripts/collect-transcription-evidence.sh",
        "scripts/generate-benchmark-fixtures.sh",
        "scripts/generate-curated-human-asr-fixture.sh",
        "scripts/generate-curated-human-meeting-fixture.sh",
        "scripts/generate-long-benchmark-fixtures.sh",
        "scripts/generate-meeting-benchmark-fixtures.sh",
        "scripts/import-transcription-evidence.py",
        "scripts/run-human-test-readiness.sh",
        "scripts/run-human-test-readiness.ps1",
        "scripts/run-transcription-lane-benchmarks.sh",
    ]
    missing = [script for script in scripts if not (root / script).exists()]
    if missing:
        return Gate("benchmark_fixture_tooling", "missing", f"missing: {', '.join(missing)}")
    runner = root / "scripts" / "run-transcription-lane-benchmarks.sh"
    runner_text = runner.read_text(encoding="utf-8")
    required = [
        "--skip-preflight",
        "doctor",
        "--stt-backend",
        "parakeet-pyannote",
        "parakeet-diarizen",
        "parakeet-sortformer",
        "cpu-human",
        "meeting-human",
        "--fixture-class",
        "--device cpu",
    ]
    missing_runner_markers = [needle for needle in required if needle not in runner_text]
    if missing_runner_markers:
        return Gate(
            "benchmark_fixture_tooling",
            "fail",
            f"lane runner missing preflight markers: {', '.join(missing_runner_markers)}",
        )
    readiness_runner = root / "scripts" / "run-human-test-readiness.sh"
    readiness_runner_text = readiness_runner.read_text(encoding="utf-8")
    required_readiness_runner = [
        "transcription_plan_audit.py --readiness",
        "dictate doctor",
        "dictate --once",
    ]
    missing_readiness_runner_markers = [
        needle for needle in required_readiness_runner if needle not in readiness_runner_text
    ]
    if missing_readiness_runner_markers:
        return Gate(
            "benchmark_fixture_tooling",
            "fail",
            "human-test readiness runner missing markers: "
            + ", ".join(missing_readiness_runner_markers),
        )
    readiness_runner_ps1 = root / "scripts" / "run-human-test-readiness.ps1"
    readiness_runner_ps1_text = readiness_runner_ps1.read_text(encoding="utf-8")
    required_readiness_runner_ps1 = [
        "transcription_plan_audit.py",
        "--readiness",
        "-m dictate doctor",
        "-m dictate --once",
    ]
    missing_readiness_runner_ps1_markers = [
        needle for needle in required_readiness_runner_ps1 if needle not in readiness_runner_ps1_text
    ]
    if missing_readiness_runner_ps1_markers:
        return Gate(
            "benchmark_fixture_tooling",
            "fail",
            "Windows human-test readiness runner missing markers: "
            + ", ".join(missing_readiness_runner_ps1_markers),
        )
    collector_markers = {
        "scripts/collect-transcription-evidence.sh": [
            "benchmark-results/*.json",
            "transcription_plan_audit.py --json",
            "lane-runner-dry-run.txt",
            "human-lane-dry-run.txt",
            "lane-readiness.txt",
            "promotion-status.txt",
            "cpu-parakeet-v2",
            "meeting-sortformer",
            "machine.txt",
            "parakeet-v2-cpu-human-gated.json",
            "parakeet-pyannote-cpu-human-meeting.json",
        ],
        "scripts/collect-transcription-evidence.ps1": [
            "benchmark-results/*.json",
            "transcription_plan_audit.py --json",
            "lane-runner-dry-run.txt",
            "human-lane-dry-run.txt",
            "lane-readiness.txt",
            "promotion-status.txt",
            "cpu-parakeet-v2",
            "meeting-sortformer",
            "machine.txt",
            "Compress-Archive",
            "parakeet-v2-cpu-flite-long-3x-gated.json",
            "parakeet-diarizen-cpu-flite-meeting.json",
            "parakeet-sortformer-cpu-flite-meeting.json",
            "parakeet-v2-cpu-human-gated.json",
            "parakeet-pyannote-cpu-human-meeting.json",
        ],
    }
    missing_collector_markers: list[str] = []
    for relative, required_collector in collector_markers.items():
        collector_text = (root / relative).read_text(encoding="utf-8")
        missing_collector_markers.extend(
            f"{relative}: {needle}" for needle in required_collector if needle not in collector_text
        )
    if missing_collector_markers:
        return Gate(
            "benchmark_fixture_tooling",
            "fail",
            f"evidence collector missing markers: {', '.join(missing_collector_markers)}",
        )
    required_shell_collector = [
        "benchmark-results/*.json",
        "transcription_plan_audit.py --json",
        "lane-runner-dry-run.txt",
        "lane-readiness.txt",
        "machine.txt",
    ]
    shell_collector = root / "scripts" / "collect-transcription-evidence.sh"
    shell_collector_text = shell_collector.read_text(encoding="utf-8")
    missing_shell_markers = [
        needle for needle in required_shell_collector if needle not in shell_collector_text
    ]
    if missing_shell_markers:
        return Gate(
            "benchmark_fixture_tooling",
            "fail",
            f"evidence collector missing markers: {', '.join(missing_shell_markers)}",
        )
    gitignore = root / ".gitignore"
    gitignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if "evidence-bundles/" not in gitignore_text.splitlines():
        return Gate(
            "benchmark_fixture_tooling",
            "fail",
            "evidence-bundles/ is not ignored by Git",
        )
    return Gate(
        "benchmark_fixture_tooling",
        "pass",
        "fixture generators, preflighted lane runner, and evidence collector exist",
    )


def _meeting_promotion_gate(root: Path) -> Gate:
    targets = [
        ("benchmark-results/parakeet-pyannote-cpu-human-meeting.json", "parakeet-pyannote"),
        ("benchmark-results/parakeet-diarizen-cpu-human-meeting.json", "parakeet-diarizen"),
        ("benchmark-results/parakeet-sortformer-cpu-human-meeting.json", "parakeet-sortformer"),
    ]
    missing = [relative for relative, _backend in targets if not (root / relative).exists()]
    if missing:
        return Gate(
            "meeting_speaker_attribution",
            "blocked",
            "missing curated-human meeting benchmark artifacts: " + ", ".join(missing),
        )

    details: list[str] = []
    blockers: list[str] = []
    passing: list[str] = []
    for relative, expected_backend in targets:
        path = root / relative
        try:
            report = _read_json(path)
        except Exception as exc:  # noqa: BLE001
            return Gate("meeting_speaker_attribution", "fail", f"could not parse {relative}: {exc}")
        failed_gates = [
            gate.get("name", "unknown")
            for gate in report.get("gates", [])
            if gate.get("passed") is False
        ]
        if failed_gates:
            blockers.append(f"{expected_backend} failed gates: {', '.join(failed_gates)}")
            continue
        config = report.get("config", {})
        if config.get("backend") != expected_backend or config.get("diarize") is not True:
            return Gate(
                "meeting_speaker_attribution",
                "fail",
                f"{expected_backend} artifact is not a diarized {expected_backend} run",
            )
        if config.get("fixture_class") != "curated-human":
            return Gate(
                "meeting_speaker_attribution",
                "fail",
                f"{expected_backend} artifact is not marked fixture_class='curated-human'",
            )
        if config.get("device") != "cpu":
            return Gate(
                "meeting_speaker_attribution",
                "fail",
                f"{expected_backend} artifact was not a CPU run: device={config.get('device')!r}",
            )
        if config.get("require_speaker_attribution") is not True:
            return Gate(
                "meeting_speaker_attribution",
                "fail",
                f"{expected_backend} artifact did not require speaker attribution",
            )
        summary = report.get("summary", {})
        if summary.get("mean_der") is None:
            blockers.append(f"{expected_backend} has no DER metric")
            continue
        completed = summary.get("completed_samples", summary.get("samples"))
        if not isinstance(completed, int) or completed <= 0:
            blockers.append(f"{expected_backend} has no completed samples")
            continue
        boundary_pairs = summary.get("segment_boundary_pair_count")
        if not isinstance(boundary_pairs, int) or boundary_pairs <= 0:
            blockers.append(f"{expected_backend} has no timestamp boundary evidence")
            continue
        der = summary.get("mean_der")
        details.append(f"{expected_backend} DER {float(der):.3f}")
        passing.append(expected_backend)
    if not passing:
        return Gate(
            "meeting_speaker_attribution",
            "blocked",
            "meeting candidate blockers: " + "; ".join(blockers),
        )
    return Gate(
        "meeting_speaker_attribution",
        "pass",
        "local meeting lane promoted with DER, timestamps, speakers, and no failed gates: "
        + "; ".join(details)
        + (f"; remaining candidates: {'; '.join(blockers)}" if blockers else ""),
    )


def _windows_vm_evidence_gate(root: Path) -> Gate:
    plan = root / "docs" / "TRANSCRIPTION_PLAN.md"
    if not plan.exists():
        return Gate("windows_vm_package_evidence", "missing", "plan is missing")
    text = plan.read_text(encoding="utf-8")
    required = [
        "mode install --timeout 1800",
        "mode lifecycle --timeout 2400",
        "mode build --timeout 1800",
        "mode msix --timeout 2400",
        "dictate-ui-shell.exe",
        "engine\\dictate-engine.exe",
        "evidence collector dry-run",
        "314",
        "196",
        "ArcForgeDictate_2026.7.4.0_x64.msix",
    ]
    missing = [needle for needle in required if needle not in text]
    if missing:
        return Gate("windows_vm_package_evidence", "fail", f"plan missing VM evidence markers: {', '.join(missing)}")
    return Gate(
        "windows_vm_package_evidence",
        "pass",
        "current Windows install/lifecycle/build/MSIX VM evidence is documented",
    )


def _update_scope_gate(root: Path) -> Gate:
    plan = root / "docs" / "TRANSCRIPTION_PLAN.md"
    if not plan.exists():
        return Gate("update_scope_decision", "missing", "plan is missing")
    text = plan.read_text(encoding="utf-8")
    required = [
        "Staged update preparation is deferred out of the human-test release.",
        "The human-test release uses the tested immediate source update path",
        "mode lifecycle --timeout 2400",
        "post-update doctor again reported Parakeet v2",
    ]
    missing = [needle for needle in required if needle not in text]
    if missing:
        return Gate("update_scope_decision", "fail", f"plan missing update-scope markers: {', '.join(missing)}")
    return Gate("update_scope_decision", "pass", "staged update preparation is explicitly deferred and source update smoke is documented")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _print_text(gates: list[Gate]) -> None:
    width = max(len(gate.name) for gate in gates)
    for gate in gates:
        print(f"{gate.status.upper():7} {gate.name:<{width}}  {gate.detail}")


def _print_readiness(items: list[ReadinessItem]) -> None:
    width = max(len(item.name) for item in items)
    for item in items:
        print(f"{item.status.upper():9} {item.name:<{width}}  {item.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="Print the human-test acceptance checklist mapped to audit evidence",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when any gate is missing, blocked, or failed",
    )
    args = parser.parse_args(argv)
    gates = audit(args.root)
    if args.readiness:
        items = readiness_report(gates)
        if args.json:
            print(json.dumps([asdict(item) for item in items], indent=2))
        else:
            _print_readiness(items)
    elif args.json:
        print(json.dumps([asdict(gate) for gate in gates], indent=2))
    else:
        _print_text(gates)
    return 2 if args.strict and has_blockers(gates) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
