#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lane="all"
dry_run=0
preflight=1
python_cmd=()
results_dir="$repo_root/benchmark-results"

usage() {
  cat <<'EOF'
Usage: scripts/run-transcription-lane-benchmarks.sh [--lane LANE] [--dry-run] [--skip-preflight]

Run Dictate's canonical transcription lane benchmark commands and write the
JSON artifacts consumed by docs/TRANSCRIPTION_PLAN.md and the plan audit.

Lanes:
  cpu                 Parakeet v2 English CPU
  cuda                Parakeet v2 English NVIDIA CUDA
  cuda-multilingual   Parakeet v3 multilingual NVIDIA CUDA
  cuda-human          Parakeet v2 English NVIDIA CUDA on curated human speech
  cuda-human-v3       Parakeet v3 multilingual NVIDIA CUDA on curated human speech
  amd                 Parakeet v2 English AMD runtime
  amd-multilingual    Parakeet v3 multilingual AMD runtime
  amd-human           Parakeet v2 English AMD runtime on curated human speech
  amd-human-v3        Parakeet v3 multilingual AMD runtime on curated human speech
  meeting             Parakeet + pyannote Meeting speaker attribution
  meeting-diarizen    Parakeet + DiariZen Meeting speaker attribution
  meeting-sortformer  Parakeet + NVIDIA Sortformer Meeting speaker attribution
  meeting-human       Parakeet + pyannote Meeting on curated human meeting audio
  meeting-diarizen-human
                      Parakeet + DiariZen Meeting on curated human meeting audio
  meeting-sortformer-human
                      Parakeet + Sortformer Meeting on curated human meeting audio
  all                 Run every lane above

Environment:
  DICTATE_BENCHMARK_CMD  Command used to invoke Dictate. Defaults to
                         "uv run dictate" from the repository root.
  DICTATE_HUMAN_MANIFEST Curated-human ASR manifest for *-human ASR lanes.
  DICTATE_HUMAN_AUDIO_ROOT
                         Audio root for DICTATE_HUMAN_MANIFEST. Defaults to
                         the manifest directory.
  DICTATE_MEETING_HUMAN_MANIFEST
                         Curated-human meeting manifest with segments_json.
  DICTATE_MEETING_HUMAN_AUDIO_ROOT
                         Audio root for DICTATE_MEETING_HUMAN_MANIFEST.

Preflight:
  Each selected lane runs "dictate doctor --quick" first for the exact
  backend/model/device. This fails fast when CUDA, AMD providers, or the
  gated Meeting speaker model are unavailable. Use --skip-preflight only when
  deliberately collecting a failed benchmark artifact.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lane)
      lane="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --skip-preflight)
      preflight=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$lane" in
  cpu|cuda|cuda-multilingual|cuda-human|cuda-human-v3|amd|amd-multilingual|amd-human|amd-human-v3|meeting|meeting-diarizen|meeting-sortformer|meeting-human|meeting-diarizen-human|meeting-sortformer-human|all) ;;
  *)
    echo "Unknown lane: $lane" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ -n "${DICTATE_BENCHMARK_CMD:-}" ]]; then
  # shellcheck disable=SC2206
  python_cmd=(${DICTATE_BENCHMARK_CMD})
else
  python_cmd=(uv run dictate)
fi

run_cmd() {
  if [[ "$dry_run" -eq 1 ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

generate_fixtures() {
  case "$1" in
    meeting)
      run_cmd "$repo_root/scripts/generate-meeting-benchmark-fixtures.sh"
      ;;
    *)
      run_cmd "$repo_root/scripts/generate-long-benchmark-fixtures.sh"
      ;;
  esac
}

run_preflight() {
  local backend="$1"
  local device="$2"
  local model="$3"

  if [[ "$preflight" -eq 0 ]]; then
    return 0
  fi

  run_cmd "${python_cmd[@]}" doctor \
    --stt-backend "$backend" \
    --model "$model" \
    --device "$device" \
    --quick \
    --type-backend pynput
}

run_parakeet_lane() {
  local device="$1"
  local model="$2"
  local artifact="$3"
  local label="$4"
  local fixture_class="${5:-synthetic}"
  local manifest="${6:-$repo_root/benchmark-fixtures/flite-long/manifest-3x.csv}"
  local audio_root="${7:-$repo_root/benchmark-fixtures/flite-long}"

  run_preflight parakeet "$device" "$model"
  if [[ "$fixture_class" == "synthetic" ]]; then
    generate_fixtures long
  fi
  mkdir -p "$results_dir"
  run_cmd "${python_cmd[@]}" benchmark \
    --manifest "$manifest" \
    --audio-root "$audio_root" \
    --stt-backend parakeet \
    --model "$model" \
    --device "$device" \
    --language en \
    --fixture-class "$fixture_class" \
    --require-timestamp-metrics \
    --max-mean-wer 0.60 \
    --max-mean-rtf 1.00 \
    --max-mean-segment-boundary-mae-s 1.00 \
    --json-output "$results_dir/$artifact" \
    --run-label "$label"
}

run_meeting_lane() {
  local backend="$1"
  local artifact="$2"
  local label="$3"
  local fixture_class="${4:-synthetic}"
  local manifest="${5:-$repo_root/benchmark-fixtures/flite-meeting-smoke/manifest.csv}"
  local audio_root="${6:-$repo_root/benchmark-fixtures/flite-meeting-smoke}"

  run_preflight "$backend" cuda parakeet-tdt-0.6b-v2
  if [[ "$fixture_class" == "synthetic" ]]; then
    generate_fixtures meeting
  fi
  mkdir -p "$results_dir"
  run_cmd "${python_cmd[@]}" benchmark \
    --manifest "$manifest" \
    --audio-root "$audio_root" \
    --stt-backend "$backend" \
    --model parakeet-tdt-0.6b-v2 \
    --device cuda \
    --language en \
    --fixture-class "$fixture_class" \
    --diarize \
    --require-speaker-attribution \
    --require-timestamp-metrics \
    --require-der-metrics \
    --max-mean-der 0.20 \
    --max-mean-segment-boundary-mae-s 0.50 \
    --max-mean-speaker-confusion-rate 0.15 \
    --json-output "$results_dir/$artifact" \
    --run-label "$label"
}

human_manifest() {
  if [[ -z "${DICTATE_HUMAN_MANIFEST:-}" ]]; then
    if [[ "$dry_run" -eq 1 ]]; then
      printf '%s\n' '${DICTATE_HUMAN_MANIFEST}'
      return 0
    fi
    echo "DICTATE_HUMAN_MANIFEST is required for $lane" >&2
    exit 2
  fi
  printf '%s\n' "$DICTATE_HUMAN_MANIFEST"
}

human_audio_root() {
  if [[ -n "${DICTATE_HUMAN_AUDIO_ROOT:-}" ]]; then
    printf '%s\n' "$DICTATE_HUMAN_AUDIO_ROOT"
  elif [[ "$dry_run" -eq 1 && -z "${DICTATE_HUMAN_MANIFEST:-}" ]]; then
    printf '%s\n' '${DICTATE_HUMAN_AUDIO_ROOT:-dirname DICTATE_HUMAN_MANIFEST}'
  else
    dirname "$(human_manifest)"
  fi
}

meeting_human_manifest() {
  if [[ -z "${DICTATE_MEETING_HUMAN_MANIFEST:-}" ]]; then
    if [[ "$dry_run" -eq 1 ]]; then
      printf '%s\n' '${DICTATE_MEETING_HUMAN_MANIFEST}'
      return 0
    fi
    echo "DICTATE_MEETING_HUMAN_MANIFEST is required for $lane" >&2
    exit 2
  fi
  printf '%s\n' "$DICTATE_MEETING_HUMAN_MANIFEST"
}

meeting_human_audio_root() {
  if [[ -n "${DICTATE_MEETING_HUMAN_AUDIO_ROOT:-}" ]]; then
    printf '%s\n' "$DICTATE_MEETING_HUMAN_AUDIO_ROOT"
  elif [[ "$dry_run" -eq 1 && -z "${DICTATE_MEETING_HUMAN_MANIFEST:-}" ]]; then
    printf '%s\n' '${DICTATE_MEETING_HUMAN_AUDIO_ROOT:-dirname DICTATE_MEETING_HUMAN_MANIFEST}'
  else
    dirname "$(meeting_human_manifest)"
  fi
}

run_lane() {
  case "$1" in
    cpu)
      run_parakeet_lane cpu parakeet-tdt-0.6b-v2 \
        parakeet-v2-cpu-flite-long-3x-gated.json \
        local-cpu-flite-long-3x-gated
      ;;
    cuda)
      run_parakeet_lane cuda parakeet-tdt-0.6b-v2 \
        parakeet-v2-cuda-flite-long-3x-gated.json \
        local-cuda-flite-long-3x-gated
      ;;
    cuda-multilingual)
      run_parakeet_lane cuda parakeet-tdt-0.6b-v3 \
        parakeet-v3-cuda-flite-long-3x-gated.json \
        local-cuda-parakeet-v3-flite-long-3x-gated
      ;;
    cuda-human)
      run_parakeet_lane cuda parakeet-tdt-0.6b-v2 \
        parakeet-v2-cuda-human-gated.json \
        local-cuda-human-gated \
        curated-human "$(human_manifest)" "$(human_audio_root)"
      ;;
    cuda-human-v3)
      run_parakeet_lane cuda parakeet-tdt-0.6b-v3 \
        parakeet-v3-cuda-human-gated.json \
        local-cuda-parakeet-v3-human-gated \
        curated-human "$(human_manifest)" "$(human_audio_root)"
      ;;
    amd)
      run_parakeet_lane amd parakeet-tdt-0.6b-v2 \
        parakeet-v2-amd-flite-long-3x-gated.json \
        local-amd-flite-long-3x-gated
      ;;
    amd-multilingual)
      run_parakeet_lane amd parakeet-tdt-0.6b-v3 \
        parakeet-v3-amd-flite-long-3x-gated.json \
        local-amd-parakeet-v3-flite-long-3x-gated
      ;;
    amd-human)
      run_parakeet_lane amd parakeet-tdt-0.6b-v2 \
        parakeet-v2-amd-human-gated.json \
        local-amd-human-gated \
        curated-human "$(human_manifest)" "$(human_audio_root)"
      ;;
    amd-human-v3)
      run_parakeet_lane amd parakeet-tdt-0.6b-v3 \
        parakeet-v3-amd-human-gated.json \
        local-amd-parakeet-v3-human-gated \
        curated-human "$(human_manifest)" "$(human_audio_root)"
      ;;
    meeting)
      run_meeting_lane parakeet-pyannote \
        parakeet-pyannote-cuda-flite-meeting.json \
        local-cuda-pyannote-flite-meeting-gated
      ;;
    meeting-diarizen)
      run_meeting_lane parakeet-diarizen \
        parakeet-diarizen-cuda-flite-meeting.json \
        local-cuda-diarizen-flite-meeting-gated
      ;;
    meeting-sortformer)
      run_meeting_lane parakeet-sortformer \
        parakeet-sortformer-cuda-flite-meeting.json \
        local-cuda-sortformer-flite-meeting-gated
      ;;
    meeting-human)
      run_meeting_lane parakeet-pyannote \
        parakeet-pyannote-cuda-human-meeting.json \
        local-cuda-pyannote-human-meeting-gated \
        curated-human "$(meeting_human_manifest)" "$(meeting_human_audio_root)"
      ;;
    meeting-diarizen-human)
      run_meeting_lane parakeet-diarizen \
        parakeet-diarizen-cuda-human-meeting.json \
        local-cuda-diarizen-human-meeting-gated \
        curated-human "$(meeting_human_manifest)" "$(meeting_human_audio_root)"
      ;;
    meeting-sortformer-human)
      run_meeting_lane parakeet-sortformer \
        parakeet-sortformer-cuda-human-meeting.json \
        local-cuda-sortformer-human-meeting-gated \
        curated-human "$(meeting_human_manifest)" "$(meeting_human_audio_root)"
      ;;
  esac
}

if [[ "$lane" == "all" ]]; then
  for item in cpu cuda cuda-multilingual amd amd-multilingual meeting meeting-diarizen meeting-sortformer; do
    run_lane "$item"
  done
else
  run_lane "$lane"
fi
