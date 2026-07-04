#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$repo_root/benchmark-fixtures/flite-meeting-smoke}"
manifest="$out_dir/manifest.csv"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required to generate benchmark fixtures" >&2
  exit 1
fi

if ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffprobe is required to measure generated fixture timings" >&2
  exit 1
fi

probe_voice() {
  local voice="$1"
  ffmpeg -hide_banner -loglevel error \
    -f lavfi -i "flite=text='probe':voice=$voice" \
    -t 0.1 -f null - >/dev/null 2>&1
}

for voice in kal slt; do
  if ! probe_voice "$voice"; then
    echo "This ffmpeg build does not include the flite '$voice' voice" >&2
    exit 1
  fi
done

duration_s() {
  ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$1"
}

mkdir -p "$out_dir"
speaker1_a="$out_dir/speaker1_a.wav"
speaker2_a="$out_dir/speaker2_a.wav"
speaker1_b="$out_dir/speaker1_b.wav"
silence="$out_dir/silence.wav"
concat_list="$out_dir/meeting_concat.txt"
audio="$out_dir/flite_meeting.wav"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "flite=text='we need the launch note finished today':voice=kal" \
  -ar 16000 -ac 1 -sample_fmt s16 "$speaker1_a"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "flite=text='i will review the timeline after lunch':voice=slt" \
  -ar 16000 -ac 1 -sample_fmt s16 "$speaker2_a"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "flite=text='great please send the action list':voice=kal" \
  -ar 16000 -ac 1 -sample_fmt s16 "$speaker1_b"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "anullsrc=r=16000:cl=mono" \
  -t 0.25 -ar 16000 -ac 1 -sample_fmt s16 "$silence"

cat >"$concat_list" <<EOF
file '$speaker1_a'
file '$silence'
file '$speaker2_a'
file '$silence'
file '$speaker1_b'
EOF

ffmpeg -hide_banner -loglevel error -y \
  -f concat -safe 0 -i "$concat_list" \
  -ar 16000 -ac 1 -sample_fmt s16 "$audio"

python3 - "$manifest" "$audio" "$speaker1_a" "$speaker2_a" "$speaker1_b" "$silence" <<'PY'
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

manifest, audio, speaker1_a, speaker2_a, speaker1_b, silence = map(Path, sys.argv[1:])


def duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nk=1:nw=1",
            str(path),
        ],
        text=True,
    )
    return float(out.strip())


silence_s = duration(silence)
d1 = duration(speaker1_a)
d2 = duration(speaker2_a)
d3 = duration(speaker1_b)
segments = [
    {
        "text": "we need the launch note finished today",
        "start": 0.0,
        "end": round(d1, 3),
        "speaker": "Speaker 1",
    },
    {
        "text": "i will review the timeline after lunch",
        "start": round(d1 + silence_s, 3),
        "end": round(d1 + silence_s + d2, 3),
        "speaker": "Speaker 2",
    },
    {
        "text": "great please send the action list",
        "start": round(d1 + silence_s + d2 + silence_s, 3),
        "end": round(d1 + silence_s + d2 + silence_s + d3, 3),
        "speaker": "Speaker 1",
    },
]
text = "Speaker 1: we need the launch note finished today\nSpeaker 2: i will review the timeline after lunch\nSpeaker 1: great please send the action list"
with manifest.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["id", "audio", "text", "segments_json"])
    writer.writeheader()
    writer.writerow(
        {
            "id": "flite_meeting",
            "audio": audio.name,
            "text": text,
            "segments_json": json.dumps(segments, separators=(",", ":")),
        }
    )
PY

echo "$manifest"
