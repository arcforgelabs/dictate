#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$repo_root/benchmark-fixtures/flite-long}"
manifest="$out_dir/manifest.csv"
repeat_manifest="$out_dir/manifest-3x.csv"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required to generate benchmark fixtures" >&2
  exit 1
fi

if ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffprobe is required to measure generated fixture timings" >&2
  exit 1
fi

if ! ffmpeg -hide_banner -loglevel error -f lavfi -i "flite=text='probe':voice=kal" -t 0.1 -f null - >/dev/null 2>&1; then
  echo "This ffmpeg build does not include the flite speech source" >&2
  exit 1
fi

mkdir -p "$out_dir"
audio="$out_dir/flite_long.wav"
fixture_text="today we are validating the dictate local transcription stack on a longer recording so that startup overhead does not dominate the benchmark. the model should transcribe the sentence repeatedly while the benchmark measures real time factor across cpu and cuda execution. today we are validating the dictate local transcription stack on a longer recording so that startup overhead does not dominate the benchmark. the model should transcribe the sentence repeatedly while the benchmark measures real time factor across cpu and cuda execution. today we are validating the dictate local transcription stack on a longer recording so that startup overhead does not dominate the benchmark. the model should transcribe the sentence repeatedly while the benchmark measures real time factor across cpu and cuda execution."

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "flite=text='$fixture_text':voice=kal" \
  -ar 16000 -ac 1 -sample_fmt s16 "$audio"

python3 - "$manifest" "$repeat_manifest" "$audio" "$fixture_text" <<'PY'
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

manifest, repeat_manifest, audio = map(Path, sys.argv[1:4])
text = sys.argv[4]

duration = float(
    subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(audio),
        ],
        text=True,
    ).strip()
)
segments_json = json.dumps(
    [{"text": text, "start": 0.0, "end": round(duration, 3)}],
    separators=(",", ":"),
)

with manifest.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["id", "audio", "text", "segments_json"])
    writer.writeheader()
    writer.writerow(
        {
            "id": "flite_long",
            "audio": audio.name,
            "text": text,
            "segments_json": segments_json,
        }
    )

with repeat_manifest.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["id", "audio", "text", "segments_json"])
    writer.writeheader()
    for index in range(1, 4):
        writer.writerow(
            {
                "id": f"flite_long_{index}",
                "audio": audio.name,
                "text": text,
                "segments_json": segments_json,
            }
        )
PY

echo "$repeat_manifest"
