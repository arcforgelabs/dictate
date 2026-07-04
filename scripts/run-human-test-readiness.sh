#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
device="auto"
skip_doctor=0

usage() {
  cat <<'EOF'
Usage: scripts/run-human-test-readiness.sh [--device cpu|cuda|amd|auto] [--skip-doctor]

Print Dictate's human-test readiness report and the manual checks that must be
performed on a tester machine. This does not claim the microphone checks passed;
it gives the tester the exact commands and expected outcomes.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      device="${2:-}"
      shift 2
      ;;
    --skip-doctor)
      skip_doctor=1
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

case "$device" in
  cpu|cuda|amd|auto) ;;
  *)
    echo "--device must be cpu, cuda, amd, or auto" >&2
    exit 2
    ;;
esac

cd "$repo_root"

echo "==> Human-test readiness"
python3 scripts/transcription_plan_audit.py --readiness

if [[ "$skip_doctor" -eq 0 ]]; then
  echo
  echo "==> Local Parakeet doctor ($device)"
  uv run python -m dictate doctor \
    --stt-backend parakeet \
    --model parakeet-tdt-0.6b-v2 \
    --device "$device" \
    --quick
fi

cat <<EOF

==> Manual microphone checks
Run these on each human-test machine and speak real audio when prompted:

  uv run python -m dictate --once --stt-backend parakeet --model parakeet-tdt-0.6b-v2 --device $device --language en

Expected:
  - The transcript reflects what was spoken.
  - It does not repeat stale fixture text.
  - Plain Record and push-to-talk use the same non-meeting ASR behavior.

For Meeting validation on a CUDA tester with the Sortformer lane installed:

  uv run python -m dictate doctor --stt-backend parakeet-sortformer --model parakeet-tdt-0.6b-v2 --device cuda --quick

Expected:
  - The app allows Meeting only when a speaker-attribution lane is ready.
  - A Meeting capture produces speaker/timestamp segment metadata.

For AMD/Radeon promotion:

  scripts/run-amd-promotion-benchmarks.sh --collect-evidence

Expected:
  - benchmark-results/parakeet-v2-amd-human-gated.json is produced.
  - benchmark-results/parakeet-v3-amd-human-gated.json is produced.
  - The artifact environment shows AMD/Radeon hardware provenance.
EOF
