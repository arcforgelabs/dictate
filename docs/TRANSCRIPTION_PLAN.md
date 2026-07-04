# Dictate Transcription Plan

Date: 2026-07-05

This is the canonical planning document for Dictate local transcription,
recordings, meetings, model lanes, timestamping, speaker attribution, and GPU
support. Older research/cost notes are archived under `docs/archive/`.

## Goal

Ship a clean local-first transcription stack where:

1. Push-to-talk dictation and plain recordings use the same verbatim ASR path.
2. Meeting mode always produces a speaker-attributed transcript.
3. Parakeet is the local ASR foundation across CPU, NVIDIA GPU, and AMD GPU
   lanes.
4. Whisper/faster-whisper are treated as temporary migration scaffolding and are
   removed from product lanes once Parakeet coverage is complete.
5. AMD GPU support is first-class, not a fallback footnote.

## Product Rules

| User Action | Internal Behavior |
| --- | --- |
| Push-to-talk dictation | Verbatim ASR, no speaker attribution. |
| Plain recording | Same ASR behavior as push-to-talk, no speaker attribution. |
| Meeting | ASR plus speaker attribution. No exceptions. |

The UI should expose product language such as `Meeting` and `Record`. It should
not expose primary controls named `diarization`, `ASR backend`, `CUDA`, `MIGraphX`,
or similar engine terms.

## Local ASR Lanes

| Lane | Target | Status | Decision |
| --- | --- | --- | --- |
| English CPU | Parakeet v2, `nvidia/parakeet-tdt-0.6b-v2` | Wired today through ONNX/onnx-asr CPU path | Default English local lane. |
| English NVIDIA GPU | Parakeet v2 through CUDA-capable runtime | Required, not wired | Same English model, GPU runtime for speed. |
| Multilingual NVIDIA GPU | Parakeet v3, `nvidia/parakeet-tdt-0.6b-v3` | Required, not wired | Strategic multilingual local lane. |
| Multilingual CPU | Parakeet v3 | Feasibility benchmark | Use only if CPU latency is acceptable. |
| English AMD GPU | Parakeet v2 through AMD runtime | Required, not wired | First-class AMD lane. |
| Multilingual AMD GPU | Parakeet v3 through AMD runtime | Required, not wired | First-class AMD lane. |
| Hosted high-quality ASR | Cohere Labs Transcribe | Benchmark candidate | Keep on table for high-quality hosted comparison. |

Current `faster-whisper/large-v3` support is a bridge for this workstation, not
the product direction.

## AMD GPU Path

AMD GPU support is essential. If CUDA is unavailable but an AMD GPU is present,
Dictate should still provide a high-performance local Parakeet path.

| Runtime Path | Platform | Plan |
| --- | --- | --- |
| ONNX Runtime `MIGraphXExecutionProvider` | Linux / ROCm | Primary Linux AMD target. |
| MIGraphX native API | Linux / ROCm | Fallback if ONNX Runtime packaging or operator coverage blocks Parakeet. |
| ONNX Runtime DirectML EP | Windows | Windows AMD evaluation path. |
| CPU Parakeet | All desktop OSes | Required fallback, not the desired high-performance AMD outcome. |

AMD acceptance gates:

1. Parakeet v2 and v3 load on the selected AMD runtime.
2. Unsupported operator fallback does not erase GPU benefit.
3. WER matches CPU/CUDA Parakeet within benchmark tolerance.
4. RTFx is materially better than CPU on representative AMD GPUs.
5. Packaging does not require non-technical users to compile ONNX Runtime.
6. Doctor/logs clearly report the AMD lane while the UI remains product-level.

## Meeting Stack

Meeting mode is ASR plus speaker attribution over the same audio timeline.

The target architecture:

1. Parakeet produces transcript text and timestamps.
2. A speaker-attribution model assigns speaker turns.
3. Dictate reconciles ASR segments, word/segment timestamps, and speaker turns
   into one transcript stream.

## Speaker Attribution Lanes

| Lane | ASR | Speaker Attribution | Decision |
| --- | --- | --- | --- |
| Local GPU quality default | Parakeet v2/v3 | DiariZen | Preferred if processing time is bearable. |
| Local GPU live/speed | Parakeet v2/v3 | NVIDIA Streaming Sortformer v2 | Use where responsiveness matters or DiariZen is too slow. |
| Local AMD GPU | Parakeet v2/v3 on AMD runtime | DiariZen / Sortformer if supported, otherwise pyannote fallback | Required benchmark lane. |
| Local CPU/offline fallback | Parakeet v2, or v3 if CPU benchmark passes | pyannote Community-1 | Ship if packaging/licensing gates pass. |
| Hosted meeting comparison | Provider ASR | Provider speaker attribution or separate diarization | Benchmark xAI, OpenAI diarize, Google Chirp 3, and Cohere plus separate speaker attribution. |

WhisperX is not the main meeting stack. Reuse timestamp/alignment ideas where
useful, but do not build the product dependency around WhisperX.

## Timestamping

All local systems should produce integrated timestamps. Parakeet v3 documents
word and segment timestamp support. The implementation should also study
WhisperX-style alignment/reconciliation patterns, but timestamping must be
owned by Dictate rather than depending on WhisperX as the product stack.

Benchmark timestamp quality separately from WER and DER:

1. Segment start/end error.
2. Word-level timing error where available.
3. Speaker-turn boundary error.
4. Stability on long recordings.

## Benchmark Requirements

Before promoting a lane to default, benchmark:

1. WER for transcript quality.
2. DER for speaker attribution where Meeting mode is involved.
3. Speaker-confusion rate separately from DER.
4. RTFx and live latency.
5. RAM/VRAM use.
6. First-run download size and install/package weight.
7. Runtime failure rate and fallback behavior.
8. Windows and Linux coverage where that lane is intended to ship.

AMD GPU benchmark coverage is mandatory for the advanced local GPU tier. Test at
least one Linux ROCm/MIGraphX Radeon machine and one Windows AMD GPU path if
Windows packaging is in scope for that release.

## Implementation Phases

1. **Consolidate defaults**
   - Keep fresh CPU English installs on Parakeet v2.
   - Keep recordings and push-to-talk on the same ASR path.
   - Keep Meeting as the only path that requires speaker attribution.

2. **Parakeet runtime coverage**
   - Wire Parakeet v2 CUDA.
   - Wire Parakeet v3 CUDA.
   - Benchmark Parakeet v3 CPU feasibility.
   - Build AMD GPU runtime probe and prototype with MIGraphX/ROCm.
   - Evaluate Windows AMD DirectML/MIGraphX packaging.

3. **Meeting speaker attribution**
   - Prototype DiariZen.
   - Prototype NVIDIA Streaming Sortformer v2.
   - Prototype pyannote Community-1 CPU/offline wrapper.
   - Build Dictate timestamp/speaker-turn reconciliation.

4. **Remove Whisper product dependency**
   - Keep current faster-whisper code only while Parakeet coverage is incomplete.
   - Remove Whisper/faster-whisper from product lanes after Parakeet CPU, CUDA,
     AMD, multilingual, timestamp, and packaging gates pass.
   - Keep benchmark comparison rows as historical evidence only.

5. **Hosted comparison**
   - Benchmark xAI, OpenAI diarize, Google Chirp 3, and Cohere Labs Transcribe.
   - Only use a hosted meeting provider if it returns structured
     speaker-attributed transcript data, not just prose labels.

## Archived Notes

Archived notes are reference material only. They do not override this plan.

| Archived Note | Reason |
| --- | --- |
| `docs/archive/meeting-transcription-research-2026-07-05.md` | Superseded by this consolidated plan. |
| `docs/archive/xai-diarization-cost-model-2026-07-05.md` | Cost-focused provider note; no longer the canonical model direction. |

## Sources

- Open ASR Leaderboard paper/table: https://arxiv.org/html/2510.06961v4
- Parakeet v2 model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2
- Parakeet v3 model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Canary/Parakeet v3 technical report: https://arxiv.org/abs/2509.14128
- pyannote Community-1 model card: https://huggingface.co/pyannote/speaker-diarization-community-1
- Diarization benchmark paper: https://arxiv.org/html/2509.26177v1
- NVIDIA Streaming Sortformer blog: https://developer.nvidia.com/blog/identify-speakers-in-meetings-calls-and-voice-apps-in-real-time-with-nvidia-streaming-sortformer/
- ONNX Runtime MIGraphX Execution Provider: https://onnxruntime.ai/docs/execution-providers/MIGraphX-ExecutionProvider.html
- ONNX Runtime ROCm Execution Provider note: https://onnxruntime.ai/docs/execution-providers/ROCm-ExecutionProvider.html
- AMD ROCm ONNX Runtime install notes: https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/native_linux/install-onnx.html
- AMD GPUOpen DirectML/ONNX Runtime guide: https://gpuopen.com/learn/onnx-directlml-execution-provider-guide-part1/
