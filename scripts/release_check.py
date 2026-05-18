#!/usr/bin/env python3
"""Validate that release metadata matches a CalVer tag."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path


CALVER_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Dictate release metadata")
    parser.add_argument(
        "--tag",
        default=None,
        help="Expected release tag, with or without the leading v",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    pyproject_version = _read_pyproject_version(repo_root / "pyproject.toml")
    npm_version = _read_package_json_version(repo_root / "package.json")
    version_values = _read_version_module(repo_root / "src" / "dictate" / "version.py")

    expected = _normalize_tag(args.tag) if args.tag else pyproject_version
    _require_calver(expected)
    _require_equal("pyproject.toml project.version", pyproject_version, expected)
    _require_equal("package.json version", npm_version, expected)
    _require_equal("RELEASE_VERSION", version_values["RELEASE_VERSION"], expected)
    _require_equal("PACKAGE_VERSION", version_values["PACKAGE_VERSION"], expected)

    print(f"release metadata OK: {expected}")
    return 0


def _read_pyproject_version(path: Path) -> str:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    return str(data["project"]["version"])


def _read_package_json_version(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data["version"])


def _read_version_module(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id not in {"RELEASE_VERSION", "PACKAGE_VERSION"}:
            continue
        values[target.id] = ast.literal_eval(node.value)
    missing = {"RELEASE_VERSION", "PACKAGE_VERSION"} - values.keys()
    if missing:
        raise SystemExit(f"missing version metadata: {', '.join(sorted(missing))}")
    return values


def _normalize_tag(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def _require_calver(version: str) -> None:
    if not CALVER_RE.fullmatch(version):
        raise SystemExit(f"expected CalVer YYYY.M.D or same-day patch YYYY.M.D-N, got: {version}")


def _require_equal(label: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise SystemExit(f"{label} is {actual}, expected {expected}")


if __name__ == "__main__":
    raise SystemExit(main())
