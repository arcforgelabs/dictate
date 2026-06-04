#!/usr/bin/env python3
"""Synchronize Dictate release metadata from one CalVer version."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from calver import release_version


ROOT = Path(__file__).resolve().parents[1]
CALVER_RE = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}(?:-\d+)?$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Synchronize Dictate release metadata")
    parser.add_argument(
        "version",
        nargs="?",
        help="CalVer release version, e.g. 2026.6.4 or 2026.6.4-1",
    )
    parser.add_argument("--date", type=_parse_date, default=None, help="release date")
    parser.add_argument("--sequence", type=int, default=0, help="same-day patch sequence")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if files are not already synchronized; do not write changes",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    version = args.version or release_version(args.date or date.today(), args.sequence)
    _require_calver(version)

    changes = _planned_changes(version)
    if args.check:
        stale = [str(path.relative_to(ROOT)) for path, before, after in changes if before != after]
        if stale:
            raise SystemExit("release metadata is stale:\n" + "\n".join(stale))
    else:
        for path, before, after in changes:
            if before != after:
                path.write_text(after, encoding="utf-8")

    print(f"release metadata synchronized: {version}")
    return 0


def _planned_changes(version: str) -> list[tuple[Path, str, str]]:
    wix_version = _msi_safe_version(version)
    changes: list[tuple[Path, str, str]] = []

    changes.append(
        _json_change(
            ROOT / "ui" / "package-lock.json",
            lambda data: _set_package_lock_versions(data, version),
        )
    )

    regex_replacements = {
        ROOT / "package.json": [(r'(?m)^  "version": "[^"]+",', f'  "version": "{version}",')],
        ROOT / "ui" / "package.json": [
            (r'(?m)^  "version": "[^"]+",', f'  "version": "{version}",')
        ],
        ROOT / "ui-shell" / "package.json": [
            (r'(?m)^  "version": "[^"]+",', f'  "version": "{version}",')
        ],
        ROOT / "pyproject.toml": [(r'(?m)^version = "[^"]+"', f'version = "{version}"')],
        ROOT / "ui-shell" / "src-tauri" / "Cargo.toml": [
            (r'(?m)^version = "[^"]+"', f'version = "{version}"')
        ],
        ROOT / "ui-shell" / "src-tauri" / "tauri.conf.json": [
            (r'(?m)^  "version": "[^"]+",', f'  "version": "{version}",'),
            (
                r'(?m)^        "version": "[^"]+",',
                f'        "version": "{wix_version}",',
            ),
        ],
        ROOT / "src" / "dictate" / "version.py": [
            (r'RELEASE_VERSION = "[^"]+"', f'RELEASE_VERSION = "{version}"'),
            (r'PACKAGE_VERSION = "[^"]+"', f'PACKAGE_VERSION = "{version}"'),
        ],
        ROOT / "install.ps1": [
            (r'\$DictateVersion = "[^"]+"', f'$DictateVersion = "{version}"')
        ],
        ROOT / "update.ps1": [
            (r'\$DictateVersion = "[^"]+"', f'$DictateVersion = "{version}"')
        ],
        ROOT / "install-windows.ps1": [
            (
                r'New-ItemProperty -Force -Path \$keyPath -Name "DisplayVersion" -Value "[^"]+"',
                f'New-ItemProperty -Force -Path $keyPath -Name "DisplayVersion" -Value "{version}"',
            )
        ],
        ROOT / "scripts" / "windows-user-smoke.ps1": [
            (
                r'\$entry\.DisplayVersion -eq "[^"]+"',
                f'$entry.DisplayVersion -eq "{version}"',
            )
        ],
        ROOT / "src" / "dictate" / "doctor.py": [
            (
                r"New-ItemProperty -Force -Path \$keyPath -Name 'DisplayVersion' -Value '[^']+'",
                f"New-ItemProperty -Force -Path $keyPath -Name 'DisplayVersion' -Value '{version}'",
            )
        ],
        ROOT / "ui" / "src" / "App.jsx": [
            (r'const DEFAULT_VERSION = "[^"]+";', f'const DEFAULT_VERSION = "{version}";')
        ],
    }
    for path, replacements in regex_replacements.items():
        changes.append(_regex_change(path, replacements))

    return changes


def _json_change(path: Path, mutate) -> tuple[Path, str, str]:  # noqa: ANN001
    before = path.read_text(encoding="utf-8")
    data = json.loads(before)
    mutate(data)
    after = json.dumps(data, indent=2) + "\n"
    return path, before, after


def _regex_change(path: Path, replacements: list[tuple[str, str]]) -> tuple[Path, str, str]:
    before = path.read_text(encoding="utf-8")
    after = before
    for pattern, replacement in replacements:
        after, count = re.subn(pattern, replacement, after)
        if count == 0:
            raise SystemExit(f"{path.relative_to(ROOT)} did not match {pattern!r}")
    return path, before, after


def _set_package_lock_versions(data: dict, version: str) -> None:
    data["version"] = version
    packages = data.get("packages")
    if isinstance(packages, dict) and "" in packages:
        packages[""]["version"] = version


def _msi_safe_version(public_version: str) -> str:
    date_part, separator, sequence = public_version.partition("-")
    year, month, day = [int(part) for part in date_part.split(".")]
    patch_sequence = int(sequence) if separator else 0
    return f"{year - 2000}.{month}.{day}.{patch_sequence}"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _require_calver(version: str) -> None:
    if not CALVER_RE.fullmatch(version):
        raise SystemExit(f"expected CalVer YYYY.M.D or YYYY.M.D-N, got: {version}")


if __name__ == "__main__":
    raise SystemExit(main())
