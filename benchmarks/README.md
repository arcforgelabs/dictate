# STT Benchmark Dataset Format

Use `scripts/benchmark_stt.py` with a CSV manifest to compare models/backends.

## Benchmark Purpose

Dictate should choose install/runtime defaults from evidence, not guesswork. The
benchmark suite should produce two headline numbers for each backend/model/config
on each hardware tier:

- **Quality:** normalized word error rate (`WER`) against curated reference
  transcripts. Lower is better.
- **Speed:** real-time factor (`RTF`), calculated as processing seconds divided
  by audio seconds. Lower is faster; `1.0` means exactly real time.

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
| `advanced` | Recommended baseline plus a proven NVIDIA CUDA path or a separately proven AMD GPU path, 32 GB RAM preferred, large model disk headroom | GPU English performance and multilingual quality lanes; future local WhisperX/diarization experiments after separate proof |

Windows must be included in tier proof before a tier is considered production
ready.

## Acceptance Targets

Initial benchmark gates are deliberately simple. Tighten them only after the
dataset and hardware matrix are stable.

| Tier | Quality Gate | Speed Gate | Feature Gate |
| --- | --- | --- | --- |
| `minimum` | Within 10% relative WER of the recommended tier on the core dictation set | Dictation RTF <= `1.50` for short-form local captures | Local dictation works; hosted Pro can be used when entitled; local WhisperX hidden/disabled |
| `recommended` | Baseline quality target for stable releases | Dictation RTF <= `1.00` for short-form local captures | Default stable experience |
| `advanced` | No worse than recommended on dictation; diarization quality separately measured when WhisperX is enabled | Dictation RTF <= `0.70`; future local WhisperX meeting RTF target to be set after first matrix run | Optional early-access/experimental local diarization only after packaging and legal gates |

## Local Model Lanes

Fresh installs leave `stt_backend` and `stt_model` unset so runtime detection can
choose the installed local default. The current supported default matrix is:

| Lane | Intended Default | Status |
| --- | --- | --- |
| CPU English | `parakeet/parakeet-tdt-0.6b-v2` | Default when Parakeet runtime is installed |
| CPU fallback / multilingual | `faster-whisper` hardware-aware model | Supported fallback |
| NVIDIA CUDA English performance | Parakeet English-only GPU runtime | Required, not yet wired |
| NVIDIA CUDA multilingual quality | Parakeet multilingual v3 and/or `faster-whisper/large-v3` | Required benchmark lane; faster-whisper is wired today |
| AMD GPU | ROCm/MIGraphX/Vulkan-backed runtime | Required, not yet wired |

Do not promote a GPU lane to default from marketing claims alone; run the same
manifest on representative hardware and record WER, RTF, RAM/VRAM, install size,
and package/runtime dependencies.

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

## Example

See `benchmarks/example_manifest.csv`.

## Run

```bash
dictate benchmark \
  --manifest benchmarks/example_manifest.csv \
  --audio-root benchmarks \
  --stt-backend nemo-canary \
  --model nvidia/canary-1b-flash \
  --device cuda \
  --language en
```
