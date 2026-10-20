#!/usr/bin/env python3
"""Pick and check Dictate CalVer release versions.

A release version is YYYY.M.N. YYYY.M is the UTC month the release is cut
in. N is the release count in that month, not the day: the first release of
a month is 1, and each later release is the highest stable N already tagged
in that month plus 1. N can be more than 31. Older releases used the day as
N and sometimes added a same-day correction -K; those tags stay as they are
and still count.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# YYYY.M.N with an optional legacy correction -K. No leading zeros.
VERSION_RE = re.compile(r"^(20\d{2})\.([1-9]|1[0-2])\.([1-9]\d*)(?:-([1-9]\d*))?$")


class ReleaseVersionError(ValueError):
    pass


def parse_version(value: str) -> tuple[int, int, int, int] | None:
    """Return (year, month, n, correction) for a stable version or tag."""
    match = VERSION_RE.fullmatch(value.strip().removeprefix("v"))
    if not match:
        return None
    year, month, count, correction = match.groups()
    return (int(year), int(month), int(count), int(correction or 0))


def stable_versions(tags: Iterable[str]) -> list[tuple[int, int, int, int]]:
    """Parse the stable release tags, sorted as numbers, oldest first."""
    return sorted(parsed for tag in tags if (parsed := parse_version(tag)))


def utc_today() -> date:
    return datetime.now(UTC).date()


def next_version(tags: Iterable[str], today: date | None = None) -> str:
    today = today or utc_today()
    counts = [
        count
        for year, month, count, _ in stable_versions(tags)
        if (year, month) == (today.year, today.month)
    ]
    return f"{today.year}.{today.month}.{max(counts, default=0) + 1}"


def require_next(version: str, tags: Iterable[str], today: date | None = None) -> None:
    """Refuse a version that is not the next release this month.

    A legacy correction X-K is still allowed when X is the latest stable
    release this month and X-K is not tagged yet.
    """
    tags = list(tags)
    parsed = parse_version(version)
    if parsed is None:
        raise ReleaseVersionError(f"expected CalVer YYYY.M.N or YYYY.M.N-K, got: {version}")
    expected = next_version(tags, today)
    year, month, count, correction = parsed
    if not correction:
        if version.removeprefix("v") != expected:
            raise ReleaseVersionError(
                f"{version} is not the next release this month, {expected}. "
                "N counts releases in the month; it is not the day."
            )
        return
    released = stable_versions(tags)
    latest_base = f"{year}.{month}.{count}"
    if expected != f"{year}.{month}.{count + 1}" or (year, month, count, 0) not in released:
        raise ReleaseVersionError(
            f"{version} corrects {latest_base}, which is not the latest release this month. "
            f"Use the next release, {expected}."
        )
    if parsed in released:
        raise ReleaseVersionError(f"{version} is already tagged. Use the next release, {expected}.")


def git_tags(root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "tag", "--list", "v20*"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.split()


def parse_today(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pick and check Dictate CalVer versions")
    commands = parser.add_subparsers(dest="command", required=True)
    next_parser = commands.add_parser("next", help="print the next release version")
    check_parser = commands.add_parser("check", help="fail unless VERSION is the next release")
    check_parser.add_argument("version")
    for sub in (next_parser, check_parser):
        sub.add_argument(
            "--today",
            type=parse_today,
            default=None,
            help="UTC release date, YYYY-MM-DD (default: today). Only the month is used.",
        )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    tags = git_tags()
    if args.command == "next":
        print(next_version(tags, args.today))
        return 0
    try:
        require_next(args.version, tags, args.today)
    except ReleaseVersionError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"{args.version} is the next release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
