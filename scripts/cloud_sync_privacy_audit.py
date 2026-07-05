#!/usr/bin/env python3
"""Repeatable privacy-surface audit for Dictate Pro cloud sync."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    detail: str

    def render(self, root: Path) -> str:
        rel = self.path.relative_to(root)
        return f"{rel}:{self.line}: {self.detail}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _line_number(text: str, needle: str) -> int:
    index = text.find(needle)
    if index < 0:
        return 1
    return text[:index].count("\n") + 1


def audit(root: Path = ROOT) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_audit_hotword_routine_output(root))
    findings.extend(_audit_pro_logging(root))
    findings.extend(_audit_telemetry_dependencies(root))
    findings.extend(_audit_release_gates(root))
    findings.extend(_audit_privacy_docs(root))
    return findings


def _audit_hotword_routine_output(root: Path) -> list[Finding]:
    path = root / "src" / "dictate" / "__main__.py"
    text = _read(path)
    findings: list[Finding] = []
    forbidden_fragments = [
        "Hotwords (native decode): {hotwords_str}",
        "Hotwords (prompt bias): {hotwords_str}",
        "Hotwords (post correction): {hotwords_str}",
        "join(hw)",
    ]
    for fragment in forbidden_fragments:
        if fragment in text:
            findings.append(
                Finding(path, _line_number(text, fragment), "routine output exposes hotword values")
            )
    if "_hotword_count_summary" not in text:
        findings.append(Finding(path, 1, "routine hotword output must use count-only summaries"))
    return findings


def _audit_pro_logging(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    pro_dir = root / "src" / "dictate" / "pro"
    log_line = re.compile(r"\b(?:logger\.\w+|print)\s*\(")
    sensitive_words = re.compile(
        r"\b(?:plaintext|transcript|dictation|payload|segments|audio|hotwords?|lexicon|text)\b",
        re.IGNORECASE,
    )
    allowed = {
        ("client.py", "Dictate signed upload unavailable; falling back to gateway body upload"),
        ("server.py", "pro-server route failed"),
    }
    for path in sorted(pro_dir.glob("*.py")):
        for line_no, line in enumerate(_read(path).splitlines(), start=1):
            if not log_line.search(line) or not sensitive_words.search(line):
                continue
            if any(path.name == allowed_path and allowed_text in line for allowed_path, allowed_text in allowed):
                continue
            findings.append(
                Finding(path, line_no, "Pro server/client logging references sync content terms")
            )
    return findings


def _audit_telemetry_dependencies(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    dependency_files = [
        root / "pyproject.toml",
        root / "package.json",
        root / "ui" / "package.json",
        root / "ui-shell" / "package.json",
        root / "ui-shell" / "src-tauri" / "Cargo.toml",
    ]
    telemetry_deps = re.compile(r"\b(sentry|posthog|rollbar|bugsnag|datadog-rum|analytics-node)\b", re.IGNORECASE)
    for path in dependency_files:
        text = _read(path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if telemetry_deps.search(line):
                findings.append(Finding(path, line_no, "unexpected telemetry/crash-reporting dependency"))
    return findings


def _audit_release_gates(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    workflow_paths = [
        root / ".github" / "workflows" / "ci.yml",
        root / ".github" / "workflows" / "npm-unstable.yml",
        root / ".github" / "workflows" / "release.yml",
    ]
    for path in workflow_paths:
        text = _read(path)
        if "scripts/cloud_sync_privacy_audit.py" not in text:
            findings.append(Finding(path, 1, "workflow must run cloud sync privacy audit"))
        if "scripts/cloud_sync_volume_smoke.py" not in text:
            findings.append(Finding(path, 1, "workflow must run cloud sync volume smoke"))
    return findings


def _audit_privacy_docs(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    deployment = root / "docs" / "deployment-security.md"
    text = _read(deployment)
    required_phrases = [
        "scripts/cloud_sync_privacy_audit.py",
        "customer transcript text",
        "synced lexicon terms",
        "crash reports",
        "analytics",
    ]
    for phrase in required_phrases:
        if phrase not in text:
            findings.append(Finding(deployment, 1, f"missing privacy review phrase: {phrase}"))
    return findings


def main() -> int:
    findings = audit(ROOT)
    if findings:
        print("cloud sync privacy audit failed:", file=sys.stderr)
        for finding in findings:
            print(f"  {finding.render(ROOT)}", file=sys.stderr)
        return 1
    print("cloud sync privacy audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
