#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dry_run=0
skip_preflight=0
collect_evidence=0

usage() {
  cat <<'EOF'
Usage: scripts/run-amd-promotion-benchmarks.sh [--dry-run] [--skip-preflight] [--collect-evidence]

Run the two AMD Radeon promotion lanes required by docs/TRANSCRIPTION_PLAN.md:

  benchmark-results/parakeet-v2-amd-human-gated.json
  benchmark-results/parakeet-v3-amd-human-gated.json

If DICTATE_HUMAN_MANIFEST is not set, the script prepares Dictate's curated
Open Speech Repository ASR fixture and uses that manifest. The target machine
must expose an AMD-capable ONNX Runtime provider through Dictate doctor:
MIGraphXExecutionProvider, ROCMExecutionProvider, or DmlExecutionProvider.

Environment:
  DICTATE_BENCHMARK_CMD       Command used by the lane runner.
                              Defaults to "uv run python -m dictate".
  DICTATE_HUMAN_MANIFEST      Optional curated-human ASR manifest.
  DICTATE_HUMAN_AUDIO_ROOT    Optional audio root. Defaults to manifest dir.

Options:
  --dry-run          Print the commands without loading models.
  --skip-preflight   Pass through to the lane runner. Use only when deliberately
                     collecting failed benchmark artifacts.
  --collect-evidence Run scripts/collect-transcription-evidence.sh after lanes.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      dry_run=1
      shift
      ;;
    --skip-preflight)
      skip_preflight=1
      shift
      ;;
    --collect-evidence)
      collect_evidence=1
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

run_cmd() {
  if [[ "$dry_run" -eq 1 ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

lane_args=()
if [[ "$skip_preflight" -eq 1 ]]; then
  lane_args+=(--skip-preflight)
fi
if [[ "$dry_run" -eq 1 ]]; then
  lane_args+=(--dry-run)
fi

if [[ -z "${DICTATE_HUMAN_MANIFEST:-}" ]]; then
  fixture_dir="$repo_root/benchmark-curated/open-speech-harvard"
  run_cmd "$repo_root/scripts/generate-curated-human-asr-fixture.sh" "$fixture_dir"
  export DICTATE_HUMAN_MANIFEST="$fixture_dir/manifest.csv"
  export DICTATE_HUMAN_AUDIO_ROOT="$fixture_dir"
elif [[ -z "${DICTATE_HUMAN_AUDIO_ROOT:-}" ]]; then
  export DICTATE_HUMAN_AUDIO_ROOT="$(dirname "$DICTATE_HUMAN_MANIFEST")"
fi

export DICTATE_BENCHMARK_CMD="${DICTATE_BENCHMARK_CMD:-uv run python -m dictate}"

run_cmd "$repo_root/scripts/run-transcription-lane-benchmarks.sh" \
  --lane amd-human \
  "${lane_args[@]}"
run_cmd "$repo_root/scripts/run-transcription-lane-benchmarks.sh" \
  --lane amd-human-v3 \
  "${lane_args[@]}"

run_cmd python3 "$repo_root/scripts/transcription_plan_audit.py"

if [[ "$collect_evidence" -eq 1 ]]; then
  run_cmd "$repo_root/scripts/collect-transcription-evidence.sh"
fi
