#!/usr/bin/env python3
"""Stage pyannote Community-1 for offline bundled Meeting mode.

The snapshot comes from the build model cache when the pinned revision is
already there, so a warm cache needs no Hugging Face token. A cache miss
downloads the gated snapshot once, which needs DICTATE_HF_TOKEN,
HUGGINGFACE_HUB_TOKEN, or HF_TOKEN.

``--check-cache`` is the build preflight: it exits non-zero only when the
pinned snapshot is not cached and no token is set. It imports nothing outside
the standard library, so it runs before the build venv exists.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from build_model_cache import cache_path, default_cache_dir, huggingface_token, pinned_revision

MODEL_ID = "pyannote/speaker-diarization-community-1"
COMPLETE_MARKER = ".dictate-snapshot-complete"
REQUIRED_FILES = (
    "config.yaml",
    "segmentation/pytorch_model.bin",
    "embedding/pytorch_model.bin",
    "plda/plda.npz",
    "plda/xvec_transform.npz",
)


def is_cached(snapshot: Path) -> bool:
    return (snapshot / COMPLETE_MARKER).is_file() and all(
        (snapshot / name).is_file() and (snapshot / name).stat().st_size > 0 for name in REQUIRED_FILES
    )


def missing_token_message(snapshot: Path) -> str:
    return (
        f"✗ pyannote Community-1 is not in the build model cache ({snapshot}); staging it needs a "
        "Hugging Face token via DICTATE_HF_TOKEN, HUGGINGFACE_HUB_TOKEN, or HF_TOKEN"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Directory to receive the model snapshot.")
    parser.add_argument("--revision", default=pinned_revision(MODEL_ID), help="Hugging Face commit to stage.")
    parser.add_argument("--cache-dir", default=str(default_cache_dir()), help="Build model cache root.")
    parser.add_argument(
        "--check-cache",
        action="store_true",
        help="Only check that staging can run: the snapshot is cached or a token is set.",
    )
    args = parser.parse_args()

    snapshot = cache_path(args.cache_dir, MODEL_ID, args.revision)
    token = huggingface_token()

    if args.check_cache:
        if is_cached(snapshot):
            print(f"✓ pyannote Community-1 cache hit: {snapshot}")
            return 0
        if token:
            print(f"▶ pyannote Community-1 cache miss: {snapshot}; will download with the Hugging Face token")
            return 0
        print(missing_token_message(snapshot), file=sys.stderr)
        return 1

    if not args.output:
        parser.error("--output is required unless --check-cache is given")
    output = Path(args.output).expanduser().resolve()

    if is_cached(snapshot):
        print(f"✓ pyannote Community-1 cache hit: {snapshot}")
    else:
        if not token:
            print(missing_token_message(snapshot), file=sys.stderr)
            return 1
        print(f"▶ pyannote Community-1 cache miss: downloading {MODEL_ID}@{args.revision}")
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=MODEL_ID, revision=args.revision, token=token, local_dir=str(snapshot))
        missing = [name for name in REQUIRED_FILES if not (snapshot / name).is_file()]
        if missing:
            print(f"✗ pyannote Community-1 snapshot is missing {', '.join(missing)}", file=sys.stderr)
            return 1
        (snapshot / COMPLETE_MARKER).write_text(f"{MODEL_ID}@{args.revision}\n", encoding="utf-8")

    if output.exists():
        shutil.rmtree(output)
    # Leave out Hugging Face's download metadata (.cache/) and the cache marker:
    # neither belongs in the bundle, and the metadata carries timestamps.
    shutil.copytree(
        snapshot,
        output,
        symlinks=False,
        ignore=shutil.ignore_patterns(".cache", COMPLETE_MARKER),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
