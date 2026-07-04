#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$repo_root/benchmark-curated/open-speech-harvard}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to download curated human speech fixtures" >&2
  exit 2
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required to prepare curated human speech fixtures" >&2
  exit 2
fi

mkdir -p "$out_dir"

source_url="https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0010_8k.wav"
source_wav="$out_dir/OSR_us_000_0010_8k.wav"
target_wav="$out_dir/osr_us_000_0010_harvard_list_1.wav"
manifest="$out_dir/manifest.csv"
source_note="$out_dir/SOURCE.txt"

if [[ ! -s "$source_wav" ]]; then
  curl -L --fail --silent --show-error --output "$source_wav" "$source_url"
fi

ffmpeg -y -hide_banner -loglevel error \
  -i "$source_wav" \
  -ac 1 -ar 16000 -sample_fmt s16 \
  "$target_wav"

duration="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$target_wav")"
reference="The birch canoe slid on the smooth planks. Glue the sheet to the dark blue background. It's easy to tell the depth of a well. These days a chicken leg is a rare dish. Rice is often served in round bowls. The juice of lemons makes fine punch. The box was thrown beside the parked truck. The hogs were fed chopped corn and garbage. Four hours of steady work faced us. A large size in stockings is hard to sell."
segments_json="$(python3 - "$reference" "$duration" <<'PY'
import json
import sys

text = sys.argv[1]
duration = float(sys.argv[2])
print(json.dumps([{"text": text, "start": 0.0, "end": round(duration, 3)}]))
PY
)"

python3 - "$manifest" "$reference" "$segments_json" <<'PY'
import csv
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
reference = sys.argv[2]
segments_json = sys.argv[3]
with manifest.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["id", "audio", "text", "segments_json"])
    writer.writeheader()
    writer.writerow(
        {
            "id": "osr_us_000_0010_harvard_list_1",
            "audio": "osr_us_000_0010_harvard_list_1.wav",
            "text": reference,
            "segments_json": segments_json,
        }
    )
PY

cat >"$source_note" <<'EOF'
Fixture source: Open Speech Repository, American English Harvard sentences.
Source page: https://www.voiptroubleshooter.com/open_speech/american.html
Audio file: OSR_us_000_0010_8k.wav
Transcript source: Harvard Sentences List 1, https://www.cs.columbia.edu/~hgs/audio/harvard.html

The Open Speech Repository page states the speech material is freely available
for VoIP testing, research, development, marketing, and other reasonable
applications, with source attribution required.
EOF

echo "$manifest"
