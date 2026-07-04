# STT Benchmark Dataset Format

Use `dictate benchmark` or `scripts/benchmark_stt.py` with a CSV manifest to
compare models/backends.

## Benchmark Purpose

Dictate should choose install/runtime defaults from evidence, not guesswork. The
benchmark suite should produce headline numbers for each backend/model/config on
each hardware tier:

- **Quality:** normalized word error rate (`WER`) against curated reference
  transcripts. Lower is better.
- **Speed:** real-time factor (`RTF`), calculated as processing seconds divided
  by audio seconds. Lower is faster; `1.0` means exactly real time.
- **Speed multiple:** real-time factor multiple (`RTFx`), calculated as audio
  seconds divided by processing seconds. Higher is faster; `10.0` means ten
  times real time.
- **Meeting quality:** optional diarization error rate (`DER`),
  speaker-confusion rate, and segment-boundary mean absolute error when a
  manifest provides reference segments.

Quality is the product invariant. Minimum-spec machines may run slower and may
disable heavy features, but they should not fall to a materially worse transcript
quality tier for ordinary dictation.

## Hardware Tiers

Use simple first-run detection. Default to `recommended` unless the machine is
clearly `minimum` or clearly `advanced`.

| Tier | Detection Shape | Default Config Intent |
| --- | --- | --- |
| `minimum` | x64 desktop OS, 4 CPU cores, 8 GB RAM, no proven CUDA/GPU acceleration, enough disk for the packaged app and normal local model cache | CPU-safe local dictation, conservative compute, heavy/experimental features disabled |
| `recommended` | x64 desktop OS, recent 6 CPU cores, 16 GB RAM, adequate disk, optional but not required GPU acceleration | Default local dictation config for most users |
| `advanced` | Recommended baseline plus a proven NVIDIA CUDA path or a separately proven AMD GPU path, 32 GB RAM preferred, large model disk headroom | Parakeet GPU English/multilingual lanes plus local meeting speaker-attribution experiments |

Windows must be included in tier proof before a tier is considered production
ready.

## Acceptance Targets

Initial benchmark gates are deliberately simple. Tighten them only after the
dataset and hardware matrix are stable.

| Tier | Quality Gate | Speed Gate | Feature Gate |
| --- | --- | --- | --- |
| `minimum` | Within 10% relative WER of the recommended tier on the core dictation set | Dictation RTF <= `1.50` for short-form local captures | Local dictation works; hosted Pro can be used when entitled; local meeting speaker attribution is hidden unless a CPU wrapper passes benchmarks |
| `recommended` | Baseline quality target for stable releases | Dictation RTF <= `1.00` for short-form local captures | Default stable experience |
| `advanced` | No worse than recommended on dictation; speaker-attribution quality separately measured for Meeting mode | Dictation RTF <= `0.70`; meeting RTF targets set per DiariZen / Sortformer / pyannote benchmark | Optional early-access/experimental local meetings only after packaging and legal gates |

## Canonical Model Plan

The canonical model lanes live in
[../docs/TRANSCRIPTION_PLAN.md](../docs/TRANSCRIPTION_PLAN.md). This benchmark
document defines dataset and measurement format only.

Do not promote any CPU, NVIDIA GPU, AMD GPU, meeting, or hosted lane to default
from marketing claims alone. Run the same manifest on representative hardware
and record WER, DER where applicable, RTF/RTFx, RAM/VRAM, install size, and
package/runtime dependencies.

The first curated dataset should include:

- clean close-mic dictation,
- laptop-mic dictation with room noise,
- names/product terms without relying on default hotwords,
- punctuation-heavy prose,
- short command-like phrases,
- at least one longer meeting-style recording for future diarization timing.

Do not use built-in default hotwords in benchmark runs. Hotword-specific tests
should be separate and should seed their terms explicitly.

## Manifest Schema

Required columns:

- `audio`: path to a WAV file (absolute path or relative to `--audio-root`)
- `text`: reference transcript

Optional columns:

- `id`: stable sample identifier used in output
- `segments_json` or `segments`: JSON array or path to a JSON file containing
  reference segments. Each segment can include `text`, `start`/`end` or
  `t_start`/`t_end`, and `speaker` or `speaker_label`.

## Example

See `benchmarks/example_manifest.csv`.

For a repeatable local smoke dataset, generate synthetic speech fixtures with
ffmpeg/flite:

```bash
scripts/generate-benchmark-fixtures.sh
```

This writes WAVs and a manifest under `benchmark-fixtures/flite-smoke/`. Those
files are local artifacts and are ignored by git. Use them for speed, JSON
shape, timestamp, and smoke gates. Do not use flite WER as the final product
quality benchmark; curated human recordings are still required before promotion.

For a same-fixture CPU/CUDA comparison with less startup-overhead distortion,
generate the longer repeated synthetic fixture:

```bash
scripts/generate-long-benchmark-fixtures.sh
```

This writes a longer WAV plus `manifest.csv` and `manifest-3x.csv` under
`benchmark-fixtures/flite-long/`. Use `manifest-3x.csv` for quick paired
CPU/GPU speed comparisons. It is still synthetic speech, so it is promotion
evidence for runtime plumbing and relative speed only; curated human recordings
remain the product-quality gate.

For a repeatable local meeting smoke dataset, generate a two-speaker synthetic
fixture:

```bash
scripts/generate-meeting-benchmark-fixtures.sh
```

This writes a speaker-labelled WAV and manifest under
`benchmark-fixtures/flite-meeting-smoke/`. Use it to validate meeting benchmark
JSON shape, DER/speaker/timestamp gates, and backend integration before running
curated human meeting recordings. Do not use flite DER/WER as final promotion
evidence.

Promotion artifacts must be generated from curated human fixtures and marked
with `--fixture-class curated-human`. The canonical lane runner exposes human
lanes for this:

```bash
scripts/generate-curated-human-asr-fixture.sh

DICTATE_HUMAN_MANIFEST=/path/to/asr-human-manifest.csv \
DICTATE_HUMAN_AUDIO_ROOT=/path/to/audio \
scripts/run-transcription-lane-benchmarks.sh --lane cuda-human

DICTATE_HUMAN_MANIFEST=/path/to/asr-human-manifest.csv \
DICTATE_HUMAN_AUDIO_ROOT=/path/to/audio \
scripts/run-transcription-lane-benchmarks.sh --lane amd-human

scripts/generate-curated-human-meeting-fixture.sh

DICTATE_MEETING_HUMAN_MANIFEST=/path/to/meeting-human-manifest.csv \
DICTATE_MEETING_HUMAN_AUDIO_ROOT=/path/to/audio \
scripts/run-transcription-lane-benchmarks.sh --lane meeting-human
```

Use `cuda-human-v3`, `amd-human-v3`, `meeting-diarizen-human`, and
`meeting-sortformer-human` for the multilingual and alternate Meeting
promotion artifacts. `scripts/generate-curated-human-asr-fixture.sh` prepares a
small Open Speech Repository Harvard-sentence ASR fixture for CUDA smoke
promotion. `scripts/generate-curated-human-meeting-fixture.sh` prepares a
two-speaker Open Speech Repository Harvard-sentence fixture with timestamped
speaker turns for Meeting runtime validation; it is not a natural meeting
recording and does not substitute for AMD hardware evidence.

On a Radeon test machine, use the AMD promotion wrapper to generate both
required AMD human artifacts with the canonical names and then run the plan
audit:

```bash
scripts/run-amd-promotion-benchmarks.sh --collect-evidence
```

On Windows Radeon/DirectML machines, use the native PowerShell wrapper:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\run-amd-promotion-benchmarks.ps1 -CollectEvidence
```

Run `scripts/run-amd-promotion-benchmarks.sh --dry-run` first to inspect the
commands, or `scripts\run-amd-promotion-benchmarks.ps1 -DryRun` on Windows. The
wrapper prepares the curated ASR fixture when `DICTATE_HUMAN_MANIFEST` is unset,
runs the English and multilingual AMD human lanes, then collects the normal
evidence bundle when requested. The PowerShell wrapper installs `.[amd]` by
default so Windows Radeon testers get `onnxruntime-directml`; pass
`-NoInstallAmdExtra` only for a pre-prepared venv. It still requires a real
AMD-capable ONNX Runtime provider; synthetic DirectML readiness or an
NVIDIA-only workstation will not pass the AMD promotion audit.

After a Radeon tester returns an evidence bundle, import its benchmark JSON
artifacts and rerun the plan audit:

```bash
python3 scripts/import-transcription-evidence.py /path/to/transcription-evidence.zip --audit
```

Use `--dry-run` first to inspect the artifacts, and `--overwrite` only when
intentionally replacing existing local benchmark JSON. The importer accepts
evidence directories, `.zip`, `.tar.gz`, and `.tgz` bundles, safely ignores
archive members with absolute or parent-directory paths, and rejects malformed
benchmark JSON before copying it into `benchmark-results/`.

For a source-install human-test handoff, run the readiness wrapper before the
manual microphone checks:

```bash
scripts/run-human-test-readiness.sh --device auto
```

On Windows source installs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\run-human-test-readiness.ps1 -Device auto
```

These wrappers run the readiness report, perform a quick local Parakeet doctor
unless skipped, and print the exact `dictate --once` and Meeting checks a human
tester must perform with real spoken audio.

Validate curated manifests before loading models:

```bash
dictate benchmark \
  --manifest /path/to/asr-human-manifest.csv \
  --audio-root /path/to/audio \
  --stt-backend parakeet \
  --model parakeet-tdt-0.6b-v2 \
  --device cuda \
  --fixture-class curated-human \
  --require-timestamp-metrics \
  --validate-manifest-only

dictate benchmark \
  --manifest /path/to/meeting-human-manifest.csv \
  --audio-root /path/to/audio \
  --stt-backend parakeet-pyannote \
  --model parakeet-tdt-0.6b-v2 \
  --device cuda \
  --fixture-class curated-human \
  --diarize \
  --require-speaker-attribution \
  --require-timestamp-metrics \
  --require-der-metrics \
  --validate-manifest-only
```

For `fixture_class=curated-human`, validation rejects generated
`benchmark-fixtures/` paths, `flite` sample IDs or filenames, missing audio
files, missing timestamp references, and missing timestamped speaker references
for Meeting/DER lanes.

## Run

```bash
dictate benchmark \
  --manifest benchmarks/example_manifest.csv \
  --audio-root benchmarks \
  --stt-backend parakeet \
  --model parakeet-tdt-0.6b-v2 \
  --device cuda \
  --language en \
  --fixture-class curated-human \
  --json-output benchmark-results/parakeet-v2-cuda.json \
  --run-label workstation-cuda
```

Local generated-fixture CUDA smoke with timestamp gates:

```bash
dictate benchmark \
  --manifest benchmark-fixtures/flite-smoke/manifest.csv \
  --audio-root benchmark-fixtures/flite-smoke \
  --stt-backend parakeet \
  --model parakeet-tdt-0.6b-v2 \
  --device cuda \
  --language en \
  --require-timestamp-metrics \
  --max-mean-rtf 0.70 \
  --max-mean-segment-boundary-mae-s 0.50 \
  --json-output benchmark-results/parakeet-v2-cuda-flite-smoke-gated.json \
  --run-label local-cuda-flite-smoke-gated
```

Local generated-fixture CPU/CUDA comparison:

```bash
dictate benchmark \
  --manifest benchmark-fixtures/flite-long/manifest-3x.csv \
  --audio-root benchmark-fixtures/flite-long \
  --stt-backend parakeet \
  --model parakeet-tdt-0.6b-v2 \
  --device cpu \
  --language en \
  --require-timestamp-metrics \
  --max-mean-rtf 1.00 \
  --max-mean-segment-boundary-mae-s 1.00 \
  --json-output benchmark-results/parakeet-v2-cpu-flite-long-3x-gated.json \
  --run-label local-cpu-flite-long-3x-gated

dictate benchmark \
  --manifest benchmark-fixtures/flite-long/manifest-3x.csv \
  --audio-root benchmark-fixtures/flite-long \
  --stt-backend parakeet \
  --model parakeet-tdt-0.6b-v2 \
  --device cuda \
  --language en \
  --require-timestamp-metrics \
  --max-mean-rtf 1.00 \
  --max-mean-segment-boundary-mae-s 1.00 \
  --json-output benchmark-results/parakeet-v2-cuda-flite-long-3x-gated.json \
  --run-label local-cuda-flite-long-3x-gated
```

To run the canonical local lane matrix with consistent artifact names, use:

```bash
scripts/run-transcription-lane-benchmarks.sh --dry-run
scripts/run-transcription-lane-benchmarks.sh --lane cpu
scripts/run-transcription-lane-benchmarks.sh --lane cuda
scripts/run-transcription-lane-benchmarks.sh --lane cuda-multilingual
scripts/run-transcription-lane-benchmarks.sh --lane amd
scripts/run-transcription-lane-benchmarks.sh --lane amd-multilingual
scripts/run-transcription-lane-benchmarks.sh --lane meeting
scripts/run-transcription-lane-benchmarks.sh --lane meeting-diarizen
scripts/run-transcription-lane-benchmarks.sh --lane meeting-sortformer
```

The lane runner writes the JSON artifact names consumed by
`docs/TRANSCRIPTION_PLAN.md` and `scripts/transcription_plan_audit.py`. Use
`--dry-run` on a target machine first to confirm the command sequence without
loading models. By default, each lane runs `dictate doctor --quick` first for
the exact backend/model/device so CUDA, AMD provider, or gated Meeting model
problems fail before long benchmark work starts. Use `--skip-preflight` only
when deliberately collecting a failed benchmark JSON artifact. AMD lanes still
require a machine with an AMD-capable ONNX Runtime provider; the Windows VM
DirectML smoke proves packaging/readiness only, not representative Radeon
performance.

For source installs, `./install.sh --meeting` or
`.\install-windows.ps1 -Meeting` installs the pyannote/torch dependencies for
the `parakeet-pyannote` Meeting lane. DiariZen and Sortformer are separate
experimental runtime lanes; install/configure their upstream runtimes before
selecting `parakeet-diarizen` or `parakeet-sortformer`.

After running lanes on a target machine, collect a handoff bundle:

```bash
scripts/collect-transcription-evidence.sh
```

On Windows source installs, use the PowerShell collector:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\collect-transcription-evidence.ps1
```

The collector writes a timestamped archive under `evidence-bundles/` containing
the plan, benchmark JSON reports, audit output, lane dry-run output,
`lane-readiness.txt` doctor output for CPU/CUDA/AMD/Meeting lanes, and basic
machine/provider context. It intentionally does not collect environment
variables or tokens. `evidence-bundles/` is ignored by Git so local handoff
archives do not accidentally enter commits.

Meeting/speaker-attribution lanes should run with the same audio fixtures and
`--diarize --require-speaker-attribution`:

```bash
dictate benchmark \
  --manifest benchmark-fixtures/flite-meeting-smoke/manifest.csv \
  --audio-root benchmark-fixtures/flite-meeting-smoke \
  --stt-backend parakeet-pyannote \
  --model parakeet-tdt-0.6b-v2 \
  --device cuda \
  --language en \
  --diarize \
  --require-speaker-attribution \
  --require-timestamp-metrics \
  --require-der-metrics \
  --max-mean-der 0.20 \
  --max-mean-segment-boundary-mae-s 0.50 \
  --max-mean-speaker-confusion-rate 0.15 \
  --json-output benchmark-results/parakeet-pyannote-cuda-flite-meeting.json \
  --run-label workstation-cuda-flite-meeting
```

The JSON report is the promotion artifact. It records backend/model/device,
capabilities, ONNX Runtime providers, detected GPU summary lines where
available, WER, RTF, RTFx, peak RSS when available, optional DER and speaker
metrics, timestamp boundary-pair counts, gates, and per-sample
hypotheses/segments. AMD promotion artifacts must include AMD/Radeon
provider/hardware provenance in this environment block; a generic DirectML run
without AMD/Radeon hardware is not accepted as representative Radeon evidence.

Promotion gates can fail the command with exit code `2`:

- `--max-mean-wer`
- `--max-mean-rtf`
- `--max-mean-der`
- `--max-mean-speaker-confusion-rate`
- `--max-mean-segment-boundary-mae-s`
- `--require-timestamp-metrics`
- `--require-der-metrics`

Use `--require-timestamp-metrics` and `--require-der-metrics` for Meeting lanes
before promotion. The timestamp gate fails when the manifest/backend combination
does not produce comparable timestamped reference and hypothesis segment
boundaries. The DER gate fails when there is no comparable timestamped speaker
assignment evidence. Together they prevent a meeting lane from being promoted on
plain text, speaker labels alone, or non-diarized timestamp segments.
