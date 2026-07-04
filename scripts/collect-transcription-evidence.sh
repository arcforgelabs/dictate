#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_root="$repo_root/evidence-bundles"
dry_run=0

usage() {
  cat <<'EOF'
Usage: scripts/collect-transcription-evidence.sh [--output DIR] [--dry-run]

Collect non-secret transcription readiness evidence into a timestamped archive.
The bundle is intended for human-test handoff from AMD, CUDA, or Meeting test
machines after running scripts/run-transcription-lane-benchmarks.sh.

Collected:
  docs/TRANSCRIPTION_PLAN.md
  benchmarks/README.md
  benchmark-results/*.json
  transcription plan audit text and JSON output
  canonical lane-runner dry-run output
  human promotion lane dry-run output
  lane doctor readiness output
  promotion artifact status
  basic machine/provider context without environment variables or secrets
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      output_root="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run=1
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

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
bundle_dir="$output_root/transcription-evidence-$timestamp"
archive_path="$bundle_dir.tar.gz"

if [[ "$dry_run" -eq 1 ]]; then
  cat <<EOF
Would create: $bundle_dir
Would archive: $archive_path
Would collect:
  docs/TRANSCRIPTION_PLAN.md
  benchmarks/README.md
  benchmark-results/*.json
  audit.txt
  audit.json
  lane-runner-dry-run.txt
  human-lane-dry-run.txt
  lane-readiness.txt
  promotion-status.txt
  machine.txt
  git-status.txt
EOF
  exit 0
fi

mkdir -p "$bundle_dir/benchmark-results"

copy_if_exists() {
  local source="$1"
  local destination="$2"
  if [[ -e "$source" ]]; then
    mkdir -p "$(dirname "$destination")"
    cp "$source" "$destination"
  fi
}

copy_if_exists "$repo_root/docs/TRANSCRIPTION_PLAN.md" "$bundle_dir/docs/TRANSCRIPTION_PLAN.md"
copy_if_exists "$repo_root/benchmarks/README.md" "$bundle_dir/benchmarks/README.md"

shopt -s nullglob
for artifact in "$repo_root"/benchmark-results/*.json; do
  cp "$artifact" "$bundle_dir/benchmark-results/$(basename "$artifact")"
done
shopt -u nullglob

(
  cd "$repo_root"
  python3 scripts/transcription_plan_audit.py
) >"$bundle_dir/audit.txt" 2>&1 || true

(
  cd "$repo_root"
  python3 scripts/transcription_plan_audit.py --json
) >"$bundle_dir/audit.json" 2>&1 || true

(
  cd "$repo_root"
  scripts/run-transcription-lane-benchmarks.sh --dry-run
) >"$bundle_dir/lane-runner-dry-run.txt" 2>&1 || true

{
  cd "$repo_root"
  for lane in cuda-human cuda-human-v3 amd-human amd-human-v3 meeting-human meeting-diarizen-human meeting-sortformer-human; do
    echo "## $lane"
    scripts/run-transcription-lane-benchmarks.sh --dry-run --lane "$lane"
    echo
  done
} >"$bundle_dir/human-lane-dry-run.txt" 2>&1 || true

{
  echo "Promotion artifact status"
  echo "Collected at UTC: $timestamp"
  echo
  expected=(
    benchmark-results/parakeet-v2-cuda-human-gated.json
    benchmark-results/parakeet-v3-cuda-human-gated.json
    benchmark-results/parakeet-v2-amd-human-gated.json
    benchmark-results/parakeet-v3-amd-human-gated.json
    benchmark-results/parakeet-pyannote-cuda-human-meeting.json
    benchmark-results/parakeet-diarizen-cuda-human-meeting.json
    benchmark-results/parakeet-sortformer-cuda-human-meeting.json
  )
  for relative in "${expected[@]}"; do
    if [[ -s "$repo_root/$relative" ]]; then
      echo "present  $relative"
    else
      echo "missing  $relative"
    fi
  done
  echo
  echo "Audit summary:"
  cd "$repo_root"
  python3 scripts/transcription_plan_audit.py || true
} >"$bundle_dir/promotion-status.txt" 2>&1 || true

{
  echo "Dictate transcription lane readiness"
  echo "Collected at UTC: $timestamp"
  echo
  run_readiness() {
    local label="$1"
    shift
    echo "## $label"
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    set +e
    "$@"
    local code=$?
    set -e
    echo "exit_code=$code"
    echo
  }
  cd "$repo_root"
  run_readiness "cpu-parakeet-v2" uv run dictate doctor --stt-backend parakeet --model parakeet-tdt-0.6b-v2 --device cpu --quick --type-backend pynput
  run_readiness "cuda-parakeet-v2" uv run dictate doctor --stt-backend parakeet --model parakeet-tdt-0.6b-v2 --device cuda --quick --type-backend pynput
  run_readiness "cuda-parakeet-v3" uv run dictate doctor --stt-backend parakeet --model parakeet-tdt-0.6b-v3 --device cuda --quick --type-backend pynput
  run_readiness "amd-parakeet-v2" uv run dictate doctor --stt-backend parakeet --model parakeet-tdt-0.6b-v2 --device amd --quick --type-backend pynput
  run_readiness "amd-parakeet-v3" uv run dictate doctor --stt-backend parakeet --model parakeet-tdt-0.6b-v3 --device amd --quick --type-backend pynput
  run_readiness "meeting-pyannote" uv run dictate doctor --stt-backend parakeet-pyannote --model parakeet-tdt-0.6b-v2 --device cuda --quick --type-backend pynput
  run_readiness "meeting-diarizen" uv run dictate doctor --stt-backend parakeet-diarizen --model parakeet-tdt-0.6b-v2 --device cuda --quick --type-backend pynput
  run_readiness "meeting-sortformer" uv run dictate doctor --stt-backend parakeet-sortformer --model parakeet-tdt-0.6b-v2 --device cuda --quick --type-backend pynput
} >"$bundle_dir/lane-readiness.txt" 2>&1 || true

{
  echo "Collected at UTC: $timestamp"
  echo "Repository: $repo_root"
  echo
  echo "System:"
  uname -a || true
  echo
  if command -v lscpu >/dev/null 2>&1; then
    echo "CPU:"
    lscpu | sed -n '1,25p'
    echo
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    echo "NVIDIA:"
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
    echo
  fi
  echo "ONNX Runtime providers:"
  (
    cd "$repo_root"
    uv run python - <<'PY'
try:
    import onnxruntime as ort
    print(",".join(ort.get_available_providers()))
except Exception as exc:  # noqa: BLE001
    print(f"unavailable: {exc}")
PY
  ) || true
} >"$bundle_dir/machine.txt" 2>&1

(
  cd "$repo_root"
  git status --short
) >"$bundle_dir/git-status.txt" 2>&1 || true

tar -C "$output_root" -czf "$archive_path" "$(basename "$bundle_dir")"
echo "$archive_path"
