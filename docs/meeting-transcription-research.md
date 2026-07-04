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

Plain recordings may remain available without speaker attribution. Meeting mode
does not.

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

Parakeet is the default strategic ASR family for local Dictate work:

| Lane | ASR target | Status | Rationale |
| --- | --- | --- | --- |
| English dictation, CPU | `nvidia/parakeet-tdt-0.6b-v2` | Wired today through ONNX/onnx-asr CPU path | English-only, fast, accurate, low hallucination risk. |
| English dictation, NVIDIA GPU | `nvidia/parakeet-tdt-0.6b-v2` through a CUDA-capable runtime | Target, not wired | Keep the English-only Parakeet quality profile; use GPU for speed once runtime is proven. |
| Multilingual dictation, NVIDIA GPU | `nvidia/parakeet-tdt-0.6b-v3` | Target, not wired | v3 extends Parakeet from English to 25 European languages. |
| Current GPU fallback | `faster-whisper/large-v3` | Wired and verified on RTX 4090 | Useful broad multilingual fallback, but not the strategic meeting/default stack. |
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

## Local Diarization Direction

Meeting mode must select a diarization path internally. WhisperX is not the main
stack: its quality/speed profile is not the desired product baseline. We can
reuse ideas from WhisperX, especially timestamp reconciliation and alignment
patterns, but the strategic local stack should pair Parakeet ASR with a
dedicated diarization model.

Primary local candidates:

| Candidate | Local/Hosted | GPU/CPU | DER / Accuracy Evidence | Speed Evidence | Planning View |
| --- | --- | --- | --- | --- | --- |
| NVIDIA Streaming Sortformer v2 | Local/open | GPU-oriented | Benchmarking paper reports language DER: Mandarin `9.4`, English `14.1`, German `9.6`, Japanese `12.7`, Spanish `21.1`; 4-speaker DER `13.2`. | `209.5x` RTF streaming / `214.3x` chunked in the same benchmark. | Target for local GPU live meetings. Fast enough to align with live capture. Watch 4-speaker design limits and high-speaker degradation. |
| DiariZen | Local/open | GPU benchmarked | Benchmarking paper reports overall `13.3` DER; language DER: English `7.0`, German `11.6`, Japanese `15.6`, Spanish `19.1`, Mandarin `10.1`. | `20.2x` RTF. | Strong local offline quality candidate, especially English meetings. |
| pyannote Community-1 | Local/open | CPU by default, CUDA optional | Model card DER examples: AMI IHM `17.0`, AMI SDM `19.9`, VoxConverse `11.2`, DIHARD 3 `20.2`, CALLHOME `26.7`. | No model-card RTF; pyannote 3.1 benchmark paper reports around `45x` RTF. | Practical local baseline and fallback; offline-capable after gated download. |
| pyannote Precision-2 | Hosted | Hosted | Model card comparison: AMI IHM `12.9`, AMI SDM `15.6`, VoxConverse `8.5`, DIHARD 3 `14.7`, CALLHOME `16.6`. | Hosted; local RTF unavailable. | Best pyannote quality numbers, but it is hosted. Use only for hosted/premium comparison. |
| WhisperX | Local pipeline | GPU strongly preferred | Depends on pyannote and alignment setup; not a separate diarization model. | Depends on faster-whisper + alignment + pyannote. | Do not use as main stack. Mine timestamp/alignment design where useful. |

Recommended local meeting lanes:

| User-facing mode | Internal ASR | Internal speaker attribution | Notes |
| --- | --- | --- | --- |
| Meeting, local GPU, live | Parakeet v3 for multilingual or Parakeet v2 for English | NVIDIA Streaming Sortformer v2 | Main target for responsive local meetings. |
| Meeting, local GPU, offline quality | Parakeet v2/v3 | DiariZen | Benchmark as quality lane for uploaded/finished recordings. |
| Meeting, local CPU/offline fallback | Parakeet v2 | pyannote Community-1 | Not ideal for live UX until measured, but keeps meeting semantics intact. |
| General recording | Parakeet v2/v3 or configured ASR | None unless user later converts to meeting | Recordings can be plain transcripts; meetings cannot. |

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
to select heavier models and settings:

| Setting / Choice | Accuracy Effect | Speed/Memory Effect | Dictate View |
| --- | --- | --- | --- |
| Larger ASR model | Usually improves WER until model-family limits. | More VRAM/RAM, slower. | For Whisper fallback, `large-v3` is quality; `turbo` is speed. For Parakeet, v2/v3 are both 0.6B, so GPU capacity mainly affects runtime/headroom, not a larger Parakeet model. |
| Beam size | Can improve accuracy, especially for ambiguous audio, but may have diminishing returns. | Slower decode. | Dictate faster-whisper currently uses beam size 5 in quality mode. Benchmark Parakeet runtime options separately if exposed by chosen runtime. |
| Precision: `float16` vs `int8` | `float16` can avoid quantization loss; `int8` may be close enough. | `float16` uses more VRAM; `int8` is faster/smaller. | On RTX 4090, `faster-whisper/large-v3` `float16` is viable. For production defaults, benchmark `float16`, `int8_float16`, and `int8`. |
| Batch size | Usually improves throughput, not single-stream latency. | Higher VRAM, better GPU utilization. | Useful for uploaded recordings; not a reason to batch live dictation. |
| Word/timestamp alignment pass | Improves word-level timing, not ASR text accuracy. | Extra model/pass. | Explore WhisperX-style forced alignment concepts without adopting WhisperX as the main stack. |
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
   - v3 for multilingual GPU.
4. Target NVIDIA Streaming Sortformer v2 for local GPU live meetings.
5. Target DiariZen as the local offline quality comparison, especially for
   English meetings.
6. Keep Cohere Labs Transcribe on the hosted high-quality ASR table.
7. Benchmark xAI, OpenAI diarize, and Google Chirp 3 against local Parakeet +
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
