#!/usr/bin/env python3
"""Generate Dictate CalVer release versions."""

from __future__ import annotations

import argparse
from datetime import date


def release_version(day: date) -> str:
    return f"{day.year}.{day.month}.{day.day}"


def pep440_version(day: date) -> str:
    return release_version(day)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Dictate CalVer versions")
    parser.add_argument("--date", type=_parse_date, default=date.today())
    parser.add_argument(
        "--sequence",
        type=int,
        default=1,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--format",
        choices=["release", "pep440"],
        default="release",
        help="release and pep440 both print YYYY.M.D",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.sequence != 1:
        raise SystemExit("--sequence is no longer supported; use the release date as YYYY.M.D")
    if args.format == "pep440":
        print(pep440_version(args.date))
    else:
        print(release_version(args.date))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
