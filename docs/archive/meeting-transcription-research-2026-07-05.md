# Meeting Transcription Research

Date: 2026-07-05

This note is the current research baseline for Dictate meeting capture. It
supersedes provider-first assumptions in older cost notes where they conflict
with the product rule below.

## Product Rule

`Meeting` is a user intent, not a visible model feature. If the user starts a
meeting, Dictate must produce a speaker-attributed transcript. The UI should say
`Meeting`, `Record`, or similarly plain product language; it should not expose
engine terms such as "diarization" as primary controls.

Plain recordings and push-to-talk dictation are the same transcript intent:
verbatim speech-to-text without speaker attribution. The only user action that
switches on speaker attribution is `Meeting`.

## Terms

| Term | Meaning |
| --- | --- |
| WER | Word error rate. Lower is better. |
| DER | Diarization error rate: missed speech + false alarm + speaker confusion divided by total speech time. Lower is better. |
| RTFx | Inverse real-time factor: audio duration divided by processing time. Higher is faster. `100x` means one hour of audio processes in about 36 seconds. |
| ASR | Speech-to-text: "what was said". |
| Diarization | Speaker attribution: "who spoke when". |

Leaderboard RTFx is usually batch/offline throughput, not live UI latency.
Dictate must benchmark both throughput and interactive latency before promoting
a live lane.

## ASR Direction

Parakeet is the default strategic ASR family for local Dictate work. Whisper and
faster-whisper are migration scaffolding only; they should be removed from the
strategic product lanes once Parakeet CPU, CUDA, multilingual, timestamp, and
packaging coverage are implemented.

| Lane | ASR target | Status | Rationale |
| --- | --- | --- | --- |
| English dictation, CPU | `nvidia/parakeet-tdt-0.6b-v2` | Wired today through ONNX/onnx-asr CPU path | English-only, fast, accurate, low hallucination risk. |
| English dictation, NVIDIA GPU | `nvidia/parakeet-tdt-0.6b-v2` through a CUDA-capable runtime | Target, not wired | Keep the English-only Parakeet quality profile; use GPU for speed once runtime is proven. |
| Multilingual dictation, NVIDIA GPU | `nvidia/parakeet-tdt-0.6b-v3` | Target, not wired | v3 extends Parakeet from English to 25 European languages. |
| English/multilingual dictation, AMD GPU | Parakeet v2/v3 through an AMD ONNX/runtime path | Required target, not wired | AMD GPU support is a first-class product requirement. If CUDA is unavailable but an AMD GPU is available, Dictate should still offer a high-performance local Parakeet path. |
| Multilingual dictation, CPU | `nvidia/parakeet-tdt-0.6b-v3` | Feasibility benchmark | The model card supports CPU/GPU usage through Transformers, but NVIDIA positions it for GPU-accelerated systems. Use it on CPU only if Dictate benchmarks show tolerable latency. |
| Temporary GPU fallback | `faster-whisper/large-v3` | Wired and verified on RTX 4090 | Temporary bridge only. Remove from product lanes when Parakeet v3 GPU runtime is wired and benchmarked. |
| Hosted high-quality ASR candidate | Cohere Labs Transcribe | Benchmark candidate | Open ASR table reports the lowest WER among listed short-form English systems, with still-good RTFx. |

Published short-form English ASR comparison:

| Model | Open | Avg WER | RTFx | Languages | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| Cohere Labs Transcribe | Yes | `5.42` | `525` | 14 | Lowest WER result in the Open ASR table found. Keep on table for high-quality hosted mode. |
| IBM Granite Speech 4.0 1B | Yes | `5.52` | `280` | 6 | Better WER than Parakeet, slower. |
| NVIDIA Canary Qwen 2.5B | Yes | `5.63` | `418` | 1 | Strong English accuracy candidate. |
| Qwen3 ASR 1.7B | Yes | `5.76` | `148` | 52 | Broad language support, slower. |
| Microsoft Phi 4 Multimodal Instruct | Yes | `6.02` | `151` | 8 | Competitive WER but much slower than Parakeet. |
| NVIDIA Parakeet TDT 0.6B v2 | Yes | `6.05` | `3390` | 1 | Dictate English baseline. |
| NVIDIA Parakeet TDT 0.6B v3 | Yes | `6.32` | `3330` | 25 | Dictate multilingual Parakeet target. |
| NVIDIA Canary 1B | Yes | `6.50` | `235` | 4 | Accuracy/speed tradeoff is weaker for Dictate than Parakeet. |
| OpenAI Whisper Large v3 | Yes | `7.44` | `146` | 99 | Current local fallback through faster-whisper. |
| OpenAI Whisper Large v3 Turbo | Yes | `7.83` | `200` | 99 | Faster than large-v3 but worse WER. |
| NVIDIA FastConformer CTC Large | Yes | `8.96` | `6400` | 1 | Very fast, but quality drop is too large for default Dictate lanes. |

Multilingual table notes:

| Model | Avg WER | RTFx | Languages/Dataset Scope | Planning View |
| --- | ---: | ---: | --- | --- |
| NVIDIA Parakeet TDT 0.6B v3 | `4.81` | `1720` | DE/FR/IT/ES/PT table | Strong local multilingual target because speed is far ahead of most alternatives. |
| OpenAI Whisper Large v3 | `4.81` | `111` | DE/FR/IT/ES/PT table | Similar WER in that table, much slower. |
| NVIDIA Canary 1B v2 | `4.60` | `634` | DE/FR/IT/ES/PT table | Better WER than Parakeet v3, slower; benchmark as quality option. |
| Microsoft Phi 4 Multimodal Instruct | `4.41` | `78.2` | DE/FR/IT/ES/PT table | Better WER, substantially slower/heavier. |
| Cohere Labs Transcribe | `3.83` | `491` | DE/FR/IT/ES/PT table | Best listed open multilingual WER in this table; hosted/high-quality candidate. |

## AMD GPU Direction

AMD GPU support is essential, not a stretch goal. A customer with an AMD GPU
should not be pushed down to CPU-only quality/speed just because CUDA is absent.
The product target is:

1. Detect NVIDIA CUDA, AMD GPU, and CPU capability separately.
2. Select the Parakeet runtime that matches the best available local accelerator.
3. Keep the ASR model family stable across vendors: Parakeet v2 for English,
   Parakeet v3 for multilingual.
4. Benchmark AMD on real customer-class Radeon hardware before making the lane
   default.

Current AMD runtime candidates:

| Runtime path | Platform | Status | Planning View |
| --- | --- | --- | --- |
| ONNX Runtime `MIGraphXExecutionProvider` | Linux / ROCm | Primary Linux AMD target | ONNX Runtime's MIGraphX provider accelerates ONNX graphs on AMD GPUs. ONNX Runtime docs say the older ROCm EP has been removed since 1.23 and applications should migrate to MIGraphX. |
| MIGraphX native API | Linux / ROCm | Benchmark fallback | Use if ONNX Runtime provider packaging or operator coverage blocks Parakeet. Higher integration cost. |
| ONNX Runtime DirectML EP | Windows | Windows AMD evaluation path | AMD GPUOpen documents DirectML as an ONNX Runtime acceleration path for AMD hardware on Windows. Evaluate for Windows customers if ROCm/MIGraphX packaging is not viable there. |
| CPU Parakeet | Linux/Windows/macOS | Required fallback | Good enough for English dictation today, but not the intended high-performance path for AMD GPU customers. |

AMD acceptance gates:

1. Parakeet v2 and v3 load on the selected AMD runtime without unsupported
   operator fallbacks that erase GPU benefit.
2. WER matches CPU/CUDA Parakeet within benchmark tolerance.
3. RTFx is materially better than CPU on representative AMD GPUs.
4. Packaging works without asking non-technical users to compile ONNX Runtime.
5. Runtime detection reports a clear AMD lane in logs/doctor while keeping UI
   language product-level.

## Local Diarization Direction

Meeting mode must select a speaker-attribution path internally. WhisperX is not
the main stack: its quality/speed profile is not the desired product baseline.
We can reuse ideas from WhisperX, especially timestamp reconciliation and
alignment patterns, but the strategic local stack should pair Parakeet ASR with
a dedicated speaker-attribution model.

The mental model is:

1. Parakeet produces the transcript and timestamps.
2. A diarization model assigns speaker turns over the same audio timeline.
3. Dictate reconciles ASR segments, word/segment timestamps, and speaker turns
   into one transcript segment stream.

Primary local candidates:

| Candidate | Local/Hosted | GPU/CPU | DER / Accuracy Evidence | Speed Evidence | Planning View |
| --- | --- | --- | --- | --- | --- |
| DiariZen | Local/open | GPU benchmarked | Benchmarking paper reports overall `13.3` DER; language DER: English `7.0`, German `11.6`, Japanese `15.6`, Spanish `19.1`, Mandarin `10.1`. | `20.2x` RTF. | Quality-first local meeting candidate, especially English. Make this the likely default if processing time is acceptable in Dictate's meeting benchmark. |
| NVIDIA Streaming Sortformer v2 | Local/open | GPU-oriented | Benchmarking paper reports language DER: Mandarin `9.4`, English `14.1`, German `9.6`, Japanese `12.7`, Spanish `21.1`; 4-speaker DER `13.2`. | `209.5x` RTF streaming / `214.3x` chunked in the same benchmark. | Speed-first local GPU candidate. Hard to ignore for live meetings; test whether quality is acceptable enough to use by default or as live mode. |
| pyannote Community-1 | Local/open | CPU by default, CUDA optional | Model card DER examples: AMI IHM `17.0`, AMI SDM `19.9`, VoxConverse `11.2`, DIHARD 3 `20.2`, CALLHOME `26.7`. | No model-card RTF; pyannote 3.1 benchmark paper reports around `45x` RTF. | Ship as the CPU/offline speaker-attribution wrapper if packaging/licensing gates pass. |
| pyannote Precision-2 | Hosted | Hosted | Model card comparison: AMI IHM `12.9`, AMI SDM `15.6`, VoxConverse `8.5`, DIHARD 3 `14.7`, CALLHOME `16.6`. | Hosted; local RTF unavailable. | Best pyannote quality numbers, but it is hosted. Use only for hosted/premium comparison. |
| WhisperX | Local pipeline | GPU strongly preferred | Depends on pyannote and alignment setup; not a separate diarization model. | Depends on faster-whisper + alignment + pyannote. | Do not use as main stack. Mine timestamp/alignment design where useful. |

Recommended local meeting lanes:

| User-facing mode | Internal ASR | Internal speaker attribution | Notes |
| --- | --- | --- | --- |
| Meeting, local GPU, quality default | Parakeet v2/v3 | DiariZen | Preferred default if meeting processing time is bearable. |
| Meeting, local GPU, live/speed | Parakeet v2/v3 | NVIDIA Streaming Sortformer v2 | Use when responsiveness matters or DiariZen is too slow. |
| Meeting, local AMD GPU | Parakeet v2/v3 on AMD runtime | DiariZen / Sortformer if supported, otherwise pyannote fallback | Required benchmark lane. If diarization runtime support is weaker than ASR, keep meeting semantics by using the best available speaker-attribution path. |
| Meeting, local CPU/offline fallback | Parakeet v2, or v3 if CPU multilingual benchmark passes | pyannote Community-1 | Keeps meeting semantics intact on offline CPU machines. |
| General recording / push-to-talk | Parakeet v2/v3 | None | Same transcript intent: no speaker attribution unless the user chose Meeting. |

## Cloud ASR And Meeting Providers

The cloud comparison is weaker than the local/open model comparison because most
providers publish feature and price docs, not audited WER/DER with reproducible
datasets. Treat missing numbers as a benchmark requirement, not as "good enough".

| Provider / Model | ASR WER Evidence | Speed / Latency Evidence | Diarization Evidence | Price Signal | Planning View |
| --- | --- | --- | --- | --- | --- |
| xAI Grok STT | Official docs do not publish reproducible WER/DER. | Supports batch and WebSocket streaming; docs mention interim events around 500 ms when enabled. No public RTFx found. | Official docs support `diarize=true`; words include a `speaker` field. | xAI launch docs: `$0.10/hr` batch, `$0.20/hr` streaming. | Cheap and feature-complete. Keep as hosted baseline only after Dictate benchmark, not because of published DER. |
| OpenAI `gpt-4o-transcribe` | Official docs state higher-quality transcription models exist, but no reproducible WER table found. | Supports transcription endpoints; no public RTFx found. | Separate `gpt-4o-transcribe-diarize` model exists. | Pricing docs: `gpt-4o-transcribe` `$0.006/min`, mini `$0.003/min`; diarize model priced by audio tokens per model page. | Good hosted candidate, but must benchmark word-for-word meeting fidelity and diarization output shape. |
| Google Cloud Speech-to-Text Chirp 3 | Official docs say enhanced accuracy beyond previous Chirp models, but no WER/DER table found in docs. Open ASR table lists Google Chirp v2 at `6.42` WER without speed. | Official docs say enhanced speed; no RTFx found. | Chirp 3 docs list diarization and automatic language detection. | Google STT pricing page lists standard/chirp V2 pricing at `$0.016/min` with data logging or `$0.024/min` without data logging in the referenced tier. | Worth benchmarking if Google ecosystem matters; likely more expensive than xAI/OpenAI for batch meetings. |
| Gemini audio transcription | No comparable official WER/DER found for meeting transcription. | Token/model latency depends on Gemini model and prompt; no RTFx. | Speaker labels can be prompted, but output is not a clean timestamped diarization API contract. | Token priced, not clean per audio hour in the same way. | Not a first-choice meeting transcript backend; too prompt-shaped for structured meeting segments. |
| Cohere Labs Transcribe | Open ASR table: English WER `5.42`, multilingual table avg WER `3.83`. | Open ASR table: English RTFx `525`, multilingual RTFx `491`. | No diarization support confirmed in the searched sources. | Pricing not captured in this note. | Keep as high-quality hosted ASR candidate; pair with separate diarization if needed. |

Hosted meeting rule: a hosted provider is eligible for `Meeting` only if it can
return structured speaker-attributed transcript data, not just prose with
speaker labels in text.

## Heavier Local Settings

More GPU does not automatically improve transcription accuracy. It gives us room
to select heavier runtimes, precision, chunking, timestamping, and diarization
options:

| Setting / Choice | Accuracy Effect | Speed/Memory Effect | Dictate View |
| --- | --- | --- | --- |
| Larger ASR model | Usually improves WER until model-family limits. | More VRAM/RAM, slower. | For Parakeet, v2/v3 are both 0.6B, so GPU capacity mainly affects runtime/headroom, not a larger Parakeet model. Do not choose Whisper as the quality path unless a benchmark beats Parakeet for Dictate's real data. |
| Decode/runtime options | Runtime-specific settings can affect accuracy and timestamp quality. | Heavier settings can increase latency or VRAM/RAM. | Benchmark NeMo/Transformers/ONNX Parakeet runtimes before exposing settings. |
| Precision: `float16`/`bfloat16` vs quantized | Higher precision can avoid quantization loss; quantized models may be close enough. | Higher precision uses more VRAM/RAM; quantized models are smaller/faster. | For Parakeet, benchmark the chosen CPU and CUDA runtimes. `int8` ONNX is current CPU English path. |
| Batch size | Usually improves throughput, not single-stream latency. | Higher VRAM, better GPU utilization. | Useful for uploaded recordings; not a reason to batch live dictation. |
| Word/timestamp alignment pass | Improves word-level timing, not ASR text accuracy. | Extra model/pass. | Parakeet v3 has word and segment timestamp support in its model card. Still explore WhisperX-style alignment/reconciliation patterns without adopting WhisperX as the main stack. |
| Diarization model choice | Improves speaker attribution, not raw words. | Separate CPU/GPU cost. | Meetings must run diarization; recordings can skip it. |

For local meetings, the benchmark must measure combined output:

1. WER for the transcript.
2. DER for speaker attribution.
3. Speaker-confusion rate separately, because wrong speaker assignment is often
   worse than a small word error for meeting notes.
4. Timestamp quality: utterance start/end error and word-level timing if used.
5. RTFx and live latency.
6. VRAM/RAM, package size, first-run download size, and failure rate.

## Current Decisions

1. Meeting mode always requires diarization/speaker attribution.
2. Do not make WhisperX the primary local meeting stack.
3. Use Parakeet for local ASR strategy:
   - v2 for English CPU/GPU,
   - v3 for multilingual GPU,
   - v3 for multilingual CPU only if benchmarks prove it is usable.
4. Treat Whisper/faster-whisper as temporary migration scaffolding and remove
   it from product lanes once Parakeet replacements are wired.
5. Build AMD GPU support as a first-class lane using Parakeet v2/v3 through
   MIGraphX/ROCm on Linux and DirectML/MIGraphX evaluation on Windows.
6. Try both DiariZen and NVIDIA Streaming Sortformer v2 for local GPU meetings;
   choose quality by default if processing time is bearable.
7. Ship pyannote Community-1 as the CPU/offline meeting wrapper if packaging and
   licensing gates pass.
8. Keep Cohere Labs Transcribe on the hosted high-quality ASR table.
9. Benchmark xAI, OpenAI diarize, and Google Chirp 3 against local Parakeet +
   Sortformer/DiariZen before picking a hosted production meeting provider.

## Sources

- Open ASR Leaderboard paper/table: https://arxiv.org/html/2510.06961v4
- Parakeet v2 model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2
- Parakeet v3 model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Canary/Parakeet v3 technical report: https://arxiv.org/abs/2509.14128
- faster-whisper docs: https://github.com/SYSTRAN/faster-whisper
- pyannote Community-1 model card: https://huggingface.co/pyannote/speaker-diarization-community-1
- Diarization benchmark paper: https://arxiv.org/html/2509.26177v1
- NVIDIA Streaming Sortformer blog: https://developer.nvidia.com/blog/identify-speakers-in-meetings-calls-and-voice-apps-in-real-time-with-nvidia-streaming-sortformer/
- xAI STT docs: https://docs.x.ai/developers/model-capabilities/audio/speech-to-text
- xAI voice launch/pricing: https://x.ai/news/grok-stt-and-tts-apis
- OpenAI speech-to-text docs: https://developers.openai.com/api/docs/guides/speech-to-text
- OpenAI pricing: https://developers.openai.com/api/docs/pricing
- OpenAI diarize model page: https://developers.openai.com/api/docs/models/gpt-4o-transcribe-diarize
- Google Chirp 3 docs: https://docs.cloud.google.com/speech-to-text/docs/models/chirp-3
- Google Speech-to-Text pricing: https://cloud.google.com/speech-to-text/pricing
- ONNX Runtime MIGraphX Execution Provider: https://onnxruntime.ai/docs/execution-providers/MIGraphX-ExecutionProvider.html
- ONNX Runtime ROCm Execution Provider note: https://onnxruntime.ai/docs/execution-providers/ROCm-ExecutionProvider.html
- AMD ROCm ONNX Runtime install notes: https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/native_linux/install-onnx.html
- AMD GPUOpen DirectML/ONNX Runtime guide: https://gpuopen.com/learn/onnx-directlml-execution-provider-guide-part1/
