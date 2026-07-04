#!/usr/bin/env python3
"""Import benchmark JSON artifacts from a transcription evidence bundle."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import benchmark-results/*.json from a Dictate evidence bundle.",
    )
    parser.add_argument(
        "bundle",
        help="Evidence bundle directory, .zip, .tar.gz, or .tgz archive.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root. Defaults to this script's parent repository.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List artifacts that would be imported without copying.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing benchmark-results JSON artifacts.",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Run scripts/transcription_plan_audit.py after importing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    destination = repo_root / "benchmark-results"
    bundle = Path(args.bundle).expanduser().resolve()

    with tempfile.TemporaryDirectory(prefix="dictate-evidence-import-") as temp_dir:
        source_root = _materialize_bundle(bundle, Path(temp_dir))
        artifacts = sorted(source_root.glob("**/benchmark-results/*.json"))
        if not artifacts:
            print(f"No benchmark-results/*.json artifacts found in {bundle}", file=sys.stderr)
            return 2

        destination.mkdir(parents=True, exist_ok=True)
        copied = 0
        skipped = 0
        for artifact in artifacts:
            try:
                _validate_benchmark_artifact(artifact)
            except ValueError as exc:
                print(f"Invalid benchmark artifact {artifact}: {exc}", file=sys.stderr)
                return 2
            target = destination / artifact.name
            if target.exists() and not args.overwrite:
                skipped += 1
                print(f"skip existing  {target.relative_to(repo_root)}")
                continue
            action = "would import" if args.dry_run else "import"
            print(f"{action:13} {artifact.name} -> {target.relative_to(repo_root)}")
            if not args.dry_run:
                shutil.copy2(artifact, target)
            copied += 1

    print(f"artifacts_imported={0 if args.dry_run else copied}")
    print(f"artifacts_skipped={skipped}")

    if args.audit and not args.dry_run:
        completed = subprocess.run(
            [sys.executable, "scripts/transcription_plan_audit.py"],
            cwd=repo_root,
            check=False,
        )
        return completed.returncode
    return 0


def _materialize_bundle(bundle: Path, temp_dir: Path) -> Path:
    if bundle.is_dir():
        return bundle
    if not bundle.exists():
        raise SystemExit(f"Evidence bundle not found: {bundle}")
    if zipfile.is_zipfile(bundle):
        with zipfile.ZipFile(bundle) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                relative = _safe_member_path(member.filename)
                if relative is None:
                    continue
                target = temp_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return temp_dir
    if tarfile.is_tarfile(bundle):
        with tarfile.open(bundle) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                relative = _safe_member_path(member.name)
                if relative is None:
                    continue
                source = archive.extractfile(member)
                if source is None:
                    continue
                target = temp_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        return temp_dir
    raise SystemExit(f"Unsupported evidence bundle format: {bundle}")


def _safe_member_path(name: str) -> Path | None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def _validate_benchmark_artifact(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("expected top-level JSON object")
    if not isinstance(payload.get("config"), dict):
        raise ValueError("missing object field: config")
    if not isinstance(payload.get("summary"), dict):
        raise ValueError("missing object field: summary")


if __name__ == "__main__":
    raise SystemExit(main())
