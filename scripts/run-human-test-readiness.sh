#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skip_doctor=0

usage() {
  cat <<'EOF'
Usage: scripts/run-human-test-readiness.sh [--skip-doctor]

Print Dictate's human-test readiness report and the manual checks that must be
performed on a tester machine. This does not claim the microphone checks passed;
it gives the tester the exact commands and expected outcomes. Dictate runs on
the CPU only.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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

cd "$repo_root"

echo "==> Human-test readiness"
python3 scripts/transcription_plan_audit.py --readiness

if [[ "$skip_doctor" -eq 0 ]]; then
  echo
  echo "==> Local Parakeet doctor (cpu)"
  uv run python -m dictate doctor \
    --stt-backend parakeet \
    --model parakeet-tdt-0.6b-v2 \
    --device cpu \
    --quick
fi

cat <<EOF

==> Manual microphone checks
Run these on each human-test machine and speak real audio when prompted:

  uv run python -m dictate --once --stt-backend parakeet --model parakeet-tdt-0.6b-v2 --device cpu --language en

Expected:
  - The transcript reflects what was spoken.
  - It does not repeat stale fixture text.
  - Plain Record and push-to-talk use the same Parakeet ASR behavior.
EOF
