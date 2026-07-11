#!/usr/bin/env python3
"""Stage the bundled Parakeet v2 int8 ONNX runtime files."""

from __future__ import annotations

import argparse

from dictate.stt.parakeet_backend import prepare_parakeet_v2_int8_model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Directory to receive the Parakeet model files.")
    args = parser.parse_args()
    prepare_parakeet_v2_int8_model(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
