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
- **Timestamps:** optional segment-boundary mean absolute error when a
  manifest provides reference segments.

Meeting speaker-labelling benchmarks (DER, speaker confusion) were removed with
Meeting capture on 2026-10-03 (#140).

Quality is the product invariant. Minimum-spec machines may run slower and may
disable heavy features, but they should not fall to a materially worse transcript
quality tier for ordinary dictation.

## Hardware Tiers

Use simple first-run detection. Default to `recommended` unless the machine is
clearly `minimum` or clearly `advanced`.

| Tier | Detection Shape | Default Config Intent |
| --- | --- | --- |
| `minimum` | x64 desktop OS, 4 CPU cores, 8 GB RAM, enough disk for the packaged app and normal local model cache | CPU-safe local dictation, conservative compute, heavy/experimental features disabled |
| `recommended` | x64 desktop OS, recent 6 CPU cores, 16 GB RAM, adequate disk | Default local dictation config for most users |
| `advanced` | Recommended baseline plus 8 or more recent CPU cores, 32 GB RAM preferred, large model disk headroom | Parakeet v3 multilingual on the CPU |

Windows must be included in tier proof before a tier is considered production
ready.

## Acceptance Targets

Initial benchmark gates are deliberately simple. Tighten them only after the
dataset and hardware matrix are stable.

| Tier | Quality Gate | Speed Gate | Feature Gate |
| --- | --- | --- | --- |
| `minimum` | Within 10% relative WER of the recommended tier on the core dictation set | Dictation RTF <= `1.50` for short-form local captures | Local dictation works |
| `recommended` | Baseline quality target for stable releases | Dictation RTF <= `1.00` for short-form local captures | Default stable experience |
| `advanced` | No worse than recommended on dictation | Dictation RTF <= `0.70` | Parakeet v3 multilingual |

## Canonical Model Plan

The canonical model lanes live in
[../docs/TRANSCRIPTION_PLAN.md](../docs/TRANSCRIPTION_PLAN.md). This benchmark
document defines dataset and measurement format only.

Dictate runs on the CPU only. Do not promote any lane to default from
marketing claims alone. Run the same manifest on representative hardware and
record WER, RTF/RTFx, RAM, install size, and package/runtime dependencies.

The first curated dataset should include:

- clean close-mic dictation,
- laptop-mic dictation with room noise,
- names/product terms without relying on default hotwords,
- punctuation-heavy prose,
- short command-like phrases,
- at least one longer recording for note-length timing.

Do not use built-in default hotwords in benchmark runs. Hotword-specific tests
should be separate and should seed their terms explicitly.

## Manifest Schema

Required columns:

- `audio`: path to a WAV file (absolute path or relative to `--audio-root`)
- `text`: reference transcript

Optional columns:

- `id`: stable sample identifier used in output
- `segments_json` or `segments`: JSON array or path to a JSON file containing
  reference segments. Each segment can include `text` and `start`/`end` or
  `t_start`/`t_end`. A `speaker` key from an older Meeting fixture is ignored.

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

For CPU speed measurements with less startup-overhead distortion,
generate the longer repeated synthetic fixture:

```bash
scripts/generate-long-benchmark-fixtures.sh
```

This writes a longer WAV plus `manifest.csv` and `manifest-3x.csv` under
`benchmark-fixtures/flite-long/`. Use `manifest-3x.csv` for quick repeatable
CPU speed runs. It is still synthetic speech, so it is promotion
evidence for runtime plumbing and relative speed only; curated human recordings
remain the product-quality gate.

Promotion artifacts must be generated from curated human fixtures and marked
with `--fixture-class curated-human`. The canonical lane runner exposes human
lanes for this:

```bash
scripts/generate-curated-human-asr-fixture.sh

DICTATE_HUMAN_MANIFEST=/path/to/asr-human-manifest.csv \
DICTATE_HUMAN_AUDIO_ROOT=/path/to/audio \
scripts/run-transcription-lane-benchmarks.sh --lane cpu-human
```

Use `cpu-human-v3` for the multilingual promotion artifact.
`scripts/generate-curated-human-asr-fixture.sh` prepares a small Open Speech
Repository Harvard-sentence ASR fixture for CPU smoke promotion.

After a tester returns an evidence bundle, import its benchmark JSON
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
scripts/run-human-test-readiness.sh
```

On Windows source installs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\run-human-test-readiness.ps1
```

These wrappers run the readiness report, perform a quick local Parakeet doctor
unless skipped, and print the exact `dictate --once` checks a human tester must
perform with real spoken audio.

Validate curated manifests before loading models:

```bash
dictate benchmark \
  --manifest /path/to/asr-human-manifest.csv \
  --audio-root /path/to/audio \
  --stt-backend parakeet \
  --model parakeet-tdt-0.6b-v2 \
  --device cpu \
  --fixture-class curated-human \
  --require-timestamp-metrics \
  --validate-manifest-only
```

For `fixture_class=curated-human`, validation rejects generated
`benchmark-fixtures/` paths, `flite` sample IDs or filenames, missing audio
files, and missing timestamp references.

## Run

```bash
dictate benchmark \
  --manifest benchmarks/example_manifest.csv \
  --audio-root benchmarks \
  --stt-backend parakeet \
  --model parakeet-tdt-0.6b-v2 \
  --device cpu \
  --language en \
  --fixture-class curated-human \
  --json-output benchmark-results/parakeet-v2-cpu.json \
  --run-label workstation-cpu
```

Local generated-fixture CPU smoke with timestamp gates:

```bash
dictate benchmark \
  --manifest benchmark-fixtures/flite-smoke/manifest.csv \
  --audio-root benchmark-fixtures/flite-smoke \
  --stt-backend parakeet \
  --model parakeet-tdt-0.6b-v2 \
  --device cpu \
  --language en \
  --require-timestamp-metrics \
  --max-mean-rtf 1.00 \
  --max-mean-segment-boundary-mae-s 0.50 \
  --json-output benchmark-results/parakeet-v2-cpu-flite-smoke-gated.json \
  --run-label local-cpu-flite-smoke-gated
```

Local generated-fixture CPU long run:

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
```

To run the canonical local lane matrix with consistent artifact names, use:

```bash
scripts/run-transcription-lane-benchmarks.sh --dry-run
scripts/run-transcription-lane-benchmarks.sh --lane cpu
scripts/run-transcription-lane-benchmarks.sh --lane cpu-multilingual
```

The lane runner writes the JSON artifact names consumed by
`docs/TRANSCRIPTION_PLAN.md` and `scripts/transcription_plan_audit.py`. Use
`--dry-run` on a target machine first to confirm the command sequence without
loading models. By default, each lane runs `dictate doctor --quick` first for
the exact backend/model on the CPU so a missing runtime fails before long
benchmark work starts. Use `--skip-preflight` only when deliberately collecting
a failed benchmark JSON artifact.

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
`lane-readiness.txt` doctor output for the CPU lanes, and basic machine/CPU
context. It intentionally does not collect environment variables or tokens.
`evidence-bundles/` is ignored by Git so local handoff archives do not
accidentally enter commits.

The JSON report is the promotion artifact. It records backend/model/device,
capabilities, Python/platform/CPU context, WER, RTF, RTFx, peak RSS when
available, timestamp boundary-pair counts, gates, and per-sample
hypotheses/segments.

Promotion gates can fail the command with exit code `2`:

- `--max-mean-wer`
- `--max-mean-rtf`
- `--max-mean-segment-boundary-mae-s`
- `--require-timestamp-metrics`

The timestamp gate fails when the manifest/backend combination does not produce
comparable timestamped reference and hypothesis segment boundaries.
