#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$repo_root/benchmark-fixtures/flite-smoke}"
manifest="$out_dir/manifest.csv"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is required to generate benchmark fixtures" >&2
  exit 1
fi

if ! ffmpeg -hide_banner -loglevel error -f lavfi -i "flite=text='probe':voice=kal" -t 0.1 -f null - >/dev/null 2>&1; then
  echo "This ffmpeg build does not include the flite speech source" >&2
  exit 1
fi

mkdir -p "$out_dir"
cat >"$manifest" <<'CSV'
id,audio,text,segments_json
flite_hello,flite_hello.wav,hello world,"[{""text"":""hello world"",""start"":0,""end"":1.4}]"
flite_review,flite_review.wav,schedule a review with the project nova platform team,"[{""text"":""schedule a review with the project nova platform team"",""start"":0,""end"":3.4}]"
CSV

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "flite=text='hello world':voice=kal" \
  -ar 16000 -ac 1 -sample_fmt s16 "$out_dir/flite_hello.wav"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "flite=text='schedule a review with the project nova platform team':voice=kal" \
  -ar 16000 -ac 1 -sample_fmt s16 "$out_dir/flite_review.wav"

echo "$manifest"
