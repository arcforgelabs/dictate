#!/usr/bin/env python3
"""Generate Dictate CalVer release versions."""

from __future__ import annotations

import argparse
from datetime import date


def release_version(day: date, sequence: int = 0) -> str:
    base = f"{day.year}.{day.month}.{day.day}"
    if sequence:
        return f"{base}-{sequence}"
    return base


def pep440_version(day: date, sequence: int = 0) -> str:
    return release_version(day, sequence=sequence)


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
        default=0,
        help="optional same-day patch sequence",
    )
    parser.add_argument(
        "--format",
        choices=["release", "pep440"],
        default="release",
        help="release and pep440 both print YYYY.M.D, or YYYY.M.D-N with --sequence",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.sequence < 0:
        raise SystemExit("--sequence must be zero or greater")
    if args.format == "pep440":
        print(pep440_version(args.date, sequence=args.sequence))
    else:
        print(release_version(args.date, sequence=args.sequence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
