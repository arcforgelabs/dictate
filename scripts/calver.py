#!/usr/bin/env python3
"""Pick and check Dictate CalVer release versions.

A release version is YYYY.M.N. YYYY.M is the UTC month the release is cut
in. N is the release count in that month, not the day: the first release of
a month is 1, and each later release is the highest stable N already tagged
in that month plus 1. N can be more than 31. Older releases used the day as
N; those tags stay as they are and still count.

Three kinds of release share a base YYYY.M.N (docs/RELEASING.md):

- a beta, YYYY.M.N-beta.B: a pre-release of the upcoming stable YYYY.M.N.
  B counts from 1 for each base.
- a stable release, YYYY.M.N.
- a correction, YYYY.M.N-C: a repackage of a published stable release.
  C counts from 1.

Version order is PEP 440 order: a beta is older than its final, and a
correction is newer (2026.10.1-beta.1 < 2026.10.1 < 2026.10.1-1).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]
# YYYY.M.N with an optional correction -C. No leading zeros.
VERSION_RE = re.compile(r"^(20\d{2})\.([1-9]|1[0-2])\.([1-9]\d*)(?:-([1-9]\d*))?$")
# YYYY.M.N-beta.B. No leading zeros.
BETA_RE = re.compile(r"^(20\d{2})\.([1-9]|1[0-2])\.([1-9]\d*)-beta\.([1-9]\d*)$")
CHANNELS = ("beta", "stable", "correction")


class ReleaseVersionError(ValueError):
    pass


class Release(NamedTuple):
    """One release version: its base, and a beta or correction number.

    Compare releases with order_key(), not as tuples.
    """

    year: int
    month: int
    count: int
    beta: int = 0
    correction: int = 0

    @property
    def base(self) -> str:
        return f"{self.year}.{self.month}.{self.count}"

    @property
    def channel(self) -> str:
        if self.beta:
            return "beta"
        return "correction" if self.correction else "stable"

    @property
    def npm_dist_tag(self) -> str:
        return "beta" if self.beta else "latest"

    @property
    def version(self) -> str:
        if self.beta:
            return f"{self.base}-beta.{self.beta}"
        if self.correction:
            return f"{self.base}-{self.correction}"
        return self.base

    @property
    def pep440(self) -> str:
        if self.beta:
            return f"{self.base}b{self.beta}"
        if self.correction:
            return f"{self.base}.post{self.correction}"
        return self.base

    def order_key(self) -> tuple[int, int, int, int, int]:
        """PEP 440 order: beta B < final < correction C, for one base."""
        if self.beta:
            return (self.year, self.month, self.count, 0, self.beta)
        return (self.year, self.month, self.count, 1, self.correction)

    def describe(self) -> dict[str, object]:
        return {
            "version": self.version,
            "tag": f"v{self.version}",
            "base": self.base,
            "channel": self.channel,
            "npmDistTag": self.npm_dist_tag,
            "prerelease": bool(self.beta),
            "pep440": self.pep440,
        }


def parse_release(value: str) -> Release | None:
    """Parse a beta, stable or correction version or tag. Other text gives None."""
    text = value.strip().removeprefix("v")
    if match := BETA_RE.fullmatch(text):
        year, month, count, beta = (int(part) for part in match.groups())
        return Release(year, month, count, beta=beta)
    if match := VERSION_RE.fullmatch(text):
        year, month, count, correction = match.groups()
        return Release(int(year), int(month), int(count), correction=int(correction or 0))
    return None


def parse_version(value: str) -> tuple[int, int, int, int] | None:
    """Return (year, month, n, correction) for a stable version or tag.

    A beta is not a stable version, so it gives None.
    """
    release = parse_release(value)
    if release is None or release.beta:
        return None
    return (release.year, release.month, release.count, release.correction)


def stable_versions(tags: Iterable[str]) -> list[tuple[int, int, int, int]]:
    """Parse the stable release tags, sorted as numbers, oldest first."""
    return sorted(parsed for tag in tags if (parsed := parse_version(tag)))


def newest(versions: Iterable[str]) -> str | None:
    """The newest release version in PEP 440 order. Text that is not a release is skipped."""
    releases = [release for value in versions if (release := parse_release(value))]
    if not releases:
        return None
    return max(releases, key=Release.order_key).version


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


def next_beta(base: str, tags: Iterable[str]) -> str:
    """The next beta of BASE: one more than its highest tagged beta."""
    numbers = [
        release.beta
        for tag in tags
        if (release := parse_release(tag)) and release.beta and release.base == base
    ]
    return f"{base}-beta.{max(numbers, default=0) + 1}"


def next_correction(base: str, tags: Iterable[str]) -> str:
    """The next correction of BASE: one more than its highest tagged correction."""
    numbers = [
        release.correction
        for tag in tags
        if (release := parse_release(tag)) and not release.beta and release.base == base
    ]
    return f"{base}-{max(numbers, default=0) + 1}"


def require_next(version: str, tags: Iterable[str], today: date | None = None) -> None:
    """Refuse a version that is not the next release of its kind.

    - A stable release must be the next release this month.
    - A beta must be a pre-release of the next stable release this month,
      with the next beta number for that base.
    - A correction X-C must correct X, the latest stable release this month,
      and C must not be tagged yet.
    """
    tags = list(tags)
    release = parse_release(version)
    if release is None:
        raise ReleaseVersionError(
            f"expected CalVer YYYY.M.N, YYYY.M.N-beta.B or YYYY.M.N-C, got: {version}"
        )
    expected = next_version(tags, today)
    if release.beta:
        if release.base != expected:
            raise ReleaseVersionError(
                f"{version} is a beta of {release.base}, which is not the next release "
                f"this month, {expected}."
            )
        wanted = next_beta(release.base, tags)
        if release.version != wanted:
            raise ReleaseVersionError(f"{version} is not the next beta of {release.base}, {wanted}.")
        return
    if not release.correction:
        if release.version != expected:
            raise ReleaseVersionError(
                f"{version} is not the next release this month, {expected}. "
                "N counts releases in the month; it is not the day."
            )
        return
    released = stable_versions(tags)
    year, month, count, correction = release.year, release.month, release.count, release.correction
    if expected != f"{year}.{month}.{count + 1}" or (year, month, count, 0) not in released:
        raise ReleaseVersionError(
            f"{version} corrects {release.base}, which is not the latest release this month. "
            f"Use the next release, {expected}."
        )
    if (year, month, count, correction) in released:
        raise ReleaseVersionError(f"{version} is already tagged. Use the next release, {expected}.")


def plan(channel: str, base: str, tags: Iterable[str], today: date | None = None) -> Release:
    """The next release of CHANNEL for a commit whose version files hold BASE.

    A beta and a stable release are of the upcoming stable version BASE. A
    correction repackages BASE, the latest stable release.
    """
    tags = list(tags)
    parsed = parse_release(base)
    if parsed is None or parsed.beta or parsed.correction:
        raise ReleaseVersionError(f"the version files must hold a stable YYYY.M.N, not {base}")
    if channel == "beta":
        version = next_beta(base, tags)
    elif channel == "stable":
        version = base
    elif channel == "correction":
        version = next_correction(base, tags)
    else:
        raise ReleaseVersionError(f"channel must be one of {', '.join(CHANNELS)}, not {channel}")
    require_next(version, tags, today)
    release = parse_release(version)
    assert release is not None
    return release


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
    next_parser.add_argument(
        "--channel",
        choices=CHANNELS,
        default="stable",
        help="stable (default), beta (needs --base) or correction (needs --base)",
    )
    next_parser.add_argument("--base", help="the stable YYYY.M.N the beta or correction is of")
    check_parser = commands.add_parser("check", help="fail unless VERSION is the next release of its kind")
    check_parser.add_argument("version")
    plan_parser = commands.add_parser(
        "plan", help="print the next tag for a channel as JSON (the release workflows use it)"
    )
    plan_parser.add_argument("--channel", choices=CHANNELS, required=True)
    plan_parser.add_argument("--base", required=True, help="the version the commit's files hold")
    describe_parser = commands.add_parser("describe", help="print a release tag's facts as JSON")
    describe_parser.add_argument("tag")
    newest_parser = commands.add_parser("newest", help="print the newest version in PEP 440 order")
    newest_parser.add_argument("versions", nargs="+")
    for sub in (next_parser, check_parser, plan_parser):
        sub.add_argument(
            "--today",
            type=parse_today,
            default=None,
            help="UTC release date, YYYY-MM-DD (default: today). Only the month is used.",
        )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "describe":
        release = parse_release(args.tag)
        if release is None or not args.tag.startswith("v"):
            raise SystemExit(f"{args.tag} is not a release tag (vYYYY.M.N, vYYYY.M.N-beta.B or vYYYY.M.N-C)")
        print(json.dumps(release.describe(), indent=2))
        return 0
    if args.command == "newest":
        found = newest(args.versions)
        if found is None:
            raise SystemExit("no release version given")
        print(found)
        return 0
    tags = git_tags()
    try:
        if args.command == "next":
            if args.channel == "stable" and not args.base:
                print(next_version(tags, args.today))
            elif not args.base:
                raise ReleaseVersionError(f"--channel {args.channel} needs --base")
            else:
                print(plan(args.channel, args.base, tags, args.today).version)
            return 0
        if args.command == "plan":
            print(json.dumps(plan(args.channel, args.base, tags, args.today).describe(), indent=2))
            return 0
        require_next(args.version, tags, args.today)
    except ReleaseVersionError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"{args.version} is the next release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
