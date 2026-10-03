#!/usr/bin/env python3
"""Stage third-party notices and model attributions beside the bundled engine.

Run after the models are staged. Copies THIRD_PARTY_NOTICES.md and the GNU
licence texts into the engine resource directory, and each model's
ATTRIBUTION.md into its model directory. Fails if a bundled model directory is
missing, so a build cannot ship a CC BY model without its attribution.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "packaging" / "notices"


def stage(engine_dir: Path) -> None:
    engine_dir = engine_dir.expanduser().resolve()
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", engine_dir / "THIRD_PARTY_NOTICES.md")
    shutil.copytree(NOTICES / "licenses", engine_dir / "licenses", dirs_exist_ok=True)
    for attribution in sorted((NOTICES / "models").glob("*/ATTRIBUTION.md")):
        model_dir = engine_dir / "models" / attribution.parent.name
        if not model_dir.is_dir():
            raise SystemExit(f"bundled model directory missing: {model_dir}")
        shutil.copy2(attribution, model_dir / "ATTRIBUTION.md")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-dir", required=True, help="Staged engine resource directory.")
    args = parser.parse_args()
    stage(Path(args.engine_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
