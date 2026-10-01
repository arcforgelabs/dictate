#!/usr/bin/env python3
"""Stage the bundled Parakeet v2 int8 ONNX runtime files.

Fetches the pinned revision once into the build model cache and copies it into
``--output``; a warm cache stages without network access.
"""

from __future__ import annotations

import argparse
import logging

from build_model_cache import default_cache_dir, pinned_revision

from dictate.stt.parakeet_backend import prepare_parakeet_v2_int8_model

MODEL_ID = "istupakov/parakeet-tdt-0.6b-v2-onnx"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Directory to receive the Parakeet model files.")
    parser.add_argument("--revision", default=pinned_revision(MODEL_ID), help="Hugging Face commit to stage.")
    parser.add_argument("--cache-dir", default=str(default_cache_dir()), help="Build model cache root.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    prepare_parakeet_v2_int8_model(args.output, revision=args.revision, cache_dir=args.cache_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
