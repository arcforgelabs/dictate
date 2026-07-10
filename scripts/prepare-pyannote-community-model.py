#!/usr/bin/env python3
"""Stage pyannote Community-1 for offline bundled Meeting mode."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download


MODEL_ID = "pyannote/speaker-diarization-community-1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Directory to receive the model snapshot.")
    args = parser.parse_args()

    output = Path(args.output).expanduser().resolve()
    token = (
        os.environ.get("DICTATE_HF_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or os.environ.get("HF_TOKEN")
    )

    snapshot = snapshot_download(
        repo_id=MODEL_ID,
        token=token,
        local_dir=str(output),
        local_dir_use_symlinks=False,
    )

    snapshot_path = Path(snapshot).resolve()
    if snapshot_path != output:
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(snapshot_path, output, symlinks=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
