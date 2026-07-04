#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$repo_root/benchmark-curated/open-speech-meeting}"
manifest="$out_dir/manifest.csv"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to download curated human meeting fixtures" >&2
  exit 2
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required to prepare curated human meeting fixtures" >&2
  exit 2
fi

mkdir -p "$out_dir"

speaker1_url="https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0010_8k.wav"
speaker2_url="https://www.voiptroubleshooter.com/open_speech/american/OSR_us_000_0030_8k.wav"
speaker1_source="$out_dir/OSR_us_000_0010_8k.wav"
speaker2_source="$out_dir/OSR_us_000_0030_8k.wav"
speaker1_turn="$out_dir/speaker1_harvard_list_1.wav"
speaker2_turn="$out_dir/speaker2_harvard_list_3.wav"
silence="$out_dir/silence.wav"
concat_list="$out_dir/meeting_concat.txt"
meeting_audio="$out_dir/osr_harvard_two_speaker_meeting.wav"
source_note="$out_dir/SOURCE.txt"

if [[ ! -s "$speaker1_source" ]]; then
  curl -L --fail --silent --show-error --output "$speaker1_source" "$speaker1_url"
fi
if [[ ! -s "$speaker2_source" ]]; then
  curl -L --fail --silent --show-error --output "$speaker2_source" "$speaker2_url"
fi

# Keep only the first three complete List 1 sentences. The next sentence starts
# before 12s in this source file and would make the reference transcript wrong.
ffmpeg -y -hide_banner -loglevel error -i "$speaker1_source" -t 10.2 -ac 1 -ar 16000 -sample_fmt s16 "$speaker1_turn"
ffmpeg -y -hide_banner -loglevel error -i "$speaker2_source" -t 12.0 -ac 1 -ar 16000 -sample_fmt s16 "$speaker2_turn"
ffmpeg -y -hide_banner -loglevel error -f lavfi -i "anullsrc=r=16000:cl=mono" -t 0.5 -ac 1 -ar 16000 -sample_fmt s16 "$silence"

cat >"$concat_list" <<EOF
file '$speaker1_turn'
file '$silence'
file '$speaker2_turn'
EOF

ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i "$concat_list" -ac 1 -ar 16000 -sample_fmt s16 "$meeting_audio"

python3 - "$manifest" "$speaker1_turn" "$speaker2_turn" "$silence" <<'PY'
from __future__ import annotations

import csv
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

manifest, speaker1_turn, speaker2_turn, silence = map(Path, sys.argv[1:])


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


speaker1_sentences = [
    "The birch canoe slid on the smooth planks.",
    "Glue the sheet to the dark blue background.",
    "It's easy to tell the depth of a well.",
]
speaker2_sentences = [
    "Paint the sockets in the wall dull green.",
    "The child crawled into the dense grass.",
    "Bribes fail where honest men work.",
]
silence_s = duration(silence)
d1 = duration(speaker1_turn)
d2 = duration(speaker2_turn)


def speech_intervals(path: Path, expected_count: int) -> list[tuple[float, float]]:
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        audio = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16).astype(np.float32)
    if audio.size == 0:
        return []
    audio = audio / 32768.0
    frame = max(1, int(0.03 * sample_rate))
    hop = max(1, int(0.01 * sample_rate))
    threshold = 0.02
    min_gap_s = 0.25
    min_duration_s = 0.25
    intervals: list[tuple[float, float]] = []
    start: float | None = None
    last_active: float | None = None
    for offset in range(0, max(1, audio.size - frame + 1), hop):
        window = audio[offset : offset + frame]
        rms = float(np.sqrt(np.mean(window * window))) if window.size else 0.0
        timestamp = offset / sample_rate
        if rms > threshold:
            if start is None:
                start = timestamp
            last_active = timestamp + (frame / sample_rate)
        elif start is not None and last_active is not None and timestamp - last_active > min_gap_s:
            intervals.append((start, last_active))
            start = None
            last_active = None
    if start is not None and last_active is not None:
        intervals.append((start, last_active))

    duration_s = audio.size / sample_rate
    padded = [
        (max(0.0, start - 0.08), min(duration_s, end + 0.12))
        for start, end in intervals
        if end - start >= min_duration_s
    ]
    while len(padded) > expected_count:
        gaps = [
            (padded[index + 1][0] - padded[index][1], index)
            for index in range(len(padded) - 1)
        ]
        _gap, index = min(gaps, key=lambda item: item[0])
        padded[index : index + 2] = [(padded[index][0], padded[index + 1][1])]
    if len(padded) != expected_count:
        step = duration_s / expected_count
        padded = [(index * step, (index + 1) * step) for index in range(expected_count)]
    return [(round(start, 3), round(end, 3)) for start, end in padded]


segments = []
for sentence, (start, end) in zip(speaker1_sentences, speech_intervals(speaker1_turn, len(speaker1_sentences)), strict=True):
    segments.append({"text": sentence, "start": start, "end": end, "speaker": "Speaker 1"})
speaker2_offset = d1 + silence_s
for sentence, (start, end) in zip(speaker2_sentences, speech_intervals(speaker2_turn, len(speaker2_sentences)), strict=True):
    segments.append(
        {
            "text": sentence,
            "start": round(speaker2_offset + start, 3),
            "end": round(speaker2_offset + end, 3),
            "speaker": "Speaker 2",
        }
    )

speaker1_text = " ".join(speaker1_sentences)
speaker2_text = " ".join(speaker2_sentences)
text = f"Speaker 1: {speaker1_text}\nSpeaker 2: {speaker2_text}"
with manifest.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["id", "audio", "text", "segments_json"])
    writer.writeheader()
    writer.writerow(
        {
            "id": "osr_harvard_two_speaker_meeting",
            "audio": "osr_harvard_two_speaker_meeting.wav",
            "text": text,
            "segments_json": json.dumps(segments, separators=(",", ":")),
        }
    )
PY

cat >"$source_note" <<'EOF'
Fixture source: Open Speech Repository, American English Harvard sentences.
Source page: https://www.voiptroubleshooter.com/open_speech/american.html
Audio files: OSR_us_000_0010_8k.wav and OSR_us_000_0030_8k.wav
Transcript source: Harvard Sentences Lists 1 and 3, https://www.cs.columbia.edu/~hgs/audio/harvard.html

This fixture concatenates short turns from two Open Speech Repository speakers
with silence between turns. It is curated human speech with reference speaker
labels and timestamps for Meeting benchmark validation. It is not a natural
meeting recording.

The Open Speech Repository page states the speech material is freely available
for VoIP testing, research, development, marketing, and other reasonable
applications, with source attribution required.
EOF

echo "$manifest"
