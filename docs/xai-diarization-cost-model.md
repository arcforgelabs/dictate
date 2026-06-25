# xAI diarized transcription cost model

This note estimates the provider cost of using xAI Speech to Text with
diarization for the first paid Dictate subscription, `Dictate Pro`.

Research date: 2026-06-25. Prices are USD and should be rechecked before launch.

Currency assumption for AUD planning: `1 USD ~= 1.45 AUD`, based on current
USD/AUD rates around 2026-06-25. Recheck before pricing is finalized.

## Sources

- xAI pricing docs:
  https://docs.x.ai/developers/pricing
- xAI Speech to Text docs:
  https://docs.x.ai/developers/model-capabilities/audio/speech-to-text
- xAI STT/TTS launch post:
  https://x.ai/news/grok-stt-and-tts-apis
- Baruch College Tools for Clear Speech speaking-rate reference:
  https://tfcs.baruch.cuny.edu/speaking-rate/

## Current xAI pricing

xAI lists Speech to Text pricing as:

- REST/batch Speech to Text: `$0.10 / audio hour`
- Streaming Speech to Text: `$0.20 / audio hour`

xAI's Speech to Text docs expose diarization as a `diarize=true` request
parameter. The public pricing page does not list a separate diarization add-on
or surcharge. For planning, treat diarization as included in the STT audio-hour
rate, but verify this in the xAI console before paid rollout.

The same endpoint also supports word-level timestamps, multichannel
transcription, and text formatting. These are useful for meeting processing and
speaker-attributed transcripts.

## How batch works for meetings

For xAI Speech to Text, "batch" means file-based REST transcription:

1. Dictate records or receives an audio file.
2. The backend sends the file to `POST https://api.x.ai/v1/stt`.
3. The request can include options such as `diarize=true`, `format=true`, and
   `language=en`.
4. xAI returns a transcript response with text, duration, and optional word-level
   metadata. With diarization enabled, each word includes a speaker identifier.

This is different from xAI's separate Batch API for text/chat models. The text
Batch API can discount token-priced LLM calls, but the public STT pricing already
has separate REST and streaming audio-hour prices. Do not assume the text Batch
API discount applies to Speech to Text.

Batch/file STT is the right default for long meetings and recordings because the
user does not need sub-second transcript updates after the meeting is already
recorded. xAI's public STT docs list a `500 MB` maximum file size. A normal
one-hour compressed meeting recording should fit well under that limit; very
long or high-bitrate recordings should be compressed or split into chunks before
upload.

For long meetings, use this processing path:

- record locally,
- normalize/compress to an accepted format such as MP3, M4A, WAV, FLAC, or Opus,
- upload through REST STT with `diarize=true`,
- run summary/action-item post-processing after the transcript is returned,
- keep chunk metadata if the file had to be split.

Use streaming only when the user wants live dictation, live captions, or live
meeting notes while the meeting is still happening.

## Usage assumptions

Dictate Pro should cover a normal user's regular dictation plus
meeting and recording processing.

Baseline meeting/recording assumption:

- `3-4` one-hour conversations per week
- Monthly equivalent: `13.0-17.3` audio hours
- Best processing mode: REST/batch STT at `$0.10 / hour`, because recordings do
  not need live streaming latency

Everyday dictation assumption:

- Light: `15 min/day` live dictation
- Typical: `30 min/day` live dictation
- Heavy but still ordinary: `60 min/day` live dictation
- Best processing mode: streaming STT at `$0.20 / hour`, if the user expects
  live transcript feedback

Speaking-rate assumption:

- Average English speech is roughly `150 words/minute`.
- One hour of speech is roughly `9,000 words`.
- That is enough text that meeting summaries/action items should be modeled as
  token-billed LLM post-processing, separate from audio transcription.

## Direct STT cost

Meeting and recording processing only:

| Usage | Hours/month | xAI REST STT cost |
| --- | ---: | ---: |
| 3 one-hour conversations/week | 13.0 | $1.30 |
| 4 one-hour conversations/week | 17.3 | $1.73 |

Everyday live dictation only:

| Usage | Hours/month | xAI streaming STT cost |
| --- | ---: | ---: |
| 15 min/day | 7.6 | $1.52 |
| 30 min/day | 15.2 | $3.04 |
| 60 min/day | 30.4 | $6.08 |

Combined target-user scenarios:

| Scenario | Meeting mode | Dictation mode | Hours/month | STT cost |
| --- | --- | --- | ---: | ---: |
| Light target: 3 meetings/week + 15 min/day | REST | Streaming | 20.6 | $2.82 |
| Expected target: 4 meetings/week + 30 min/day | REST | Streaming | 32.5 | $4.78 |
| Heavy target: 4 meetings/week + 60 min/day | REST | Streaming | 47.8 | $7.82 |

If all audio is sent through streaming instead of REST where possible, the
expected target scenario rises to about `$6.51/month` before post-processing
and overhead.

## Meeting post-processing cost

Meeting processing usually means more than transcription:

- clean transcript formatting,
- speaker labels,
- summary,
- decisions,
- action items,
- follow-up email or notes.

At `150 words/minute`, a one-hour transcript is about `9,000 words`. Depending
on tokenizer and meeting style, plan around `10k-14k input tokens` per meeting
plus `1k-3k output tokens` for summaries and action items.

Using xAI's current general chat pricing shown for Grok 4.3
(`$1.25 / 1M input tokens`, `$2.50 / 1M output tokens`), a one-hour meeting
summary is roughly:

- Input: `12k tokens * $1.25 / 1M = $0.015`
- Output: `2k tokens * $2.50 / 1M = $0.005`
- Total: about `$0.02` per one-hour meeting

For `13-17` one-hour meetings/month, this is only about `$0.26-$0.35/month`.
Even after allowing for retries, richer prompts, and multiple output formats,
budgeting `$0.50-$1.00/month` for meeting post-processing is conservative.

## Recommended allowance

For a paid subscription, a practical allowance is:

- include `35 audio hours/month` for target users, or
- include `40 audio hours/month` if the product promise should clearly cover
  `3-4` one-hour meetings per week plus `30 min/day` of live dictation.

Estimated provider COGS for a `40 audio hours/month` allowance:

- all REST/batch: `$4.00`
- all streaming: `$8.00`
- realistic mixed mode, meetings REST and dictation streaming: about
  `$4.50-$6.00`
- with meeting post-processing and retry overhead: about `$5.50-$8.50`

The paid plan can cover the target workload if meeting/recording uploads are
processed with REST/batch STT and live streaming is reserved for actual live
dictation. A soft cap at `40 hours/month`, with warnings near `30` and `38`
hours, should protect margin without surprising normal users.

If the market price is around `$7/month`, a `40 audio hours/month` plan
is possible but margin is thin. The expected target-user STT cost is about
`$4.78/month` before payment fees, Store fees if applicable, backend costs,
support, taxes, failed jobs, and heavy-user skew. At `$7/month`, prefer one of
these safer shapes:

- `25-30 audio hours/month` on the paid plan, with the `3-4` meetings/week target
  covered only when everyday live dictation is modest.
- `40 audio hours/month` on annual billing or a higher monthly tier.
- A fair-use paid plan with warnings and throttling after `30` hours, plus
  paid hour packs for heavy users.

## Dictate Pro at AUD 7 and 30% API markup

Pricing target:

- Customer price: `$7 AUD/month`
- Markup rule: `customer price = API cost * 1.3`
- Maximum API cost budget: `$7 / 1.3 = $5.38 AUD/month`
- At `1 USD ~= 1.45 AUD`: `$5.38 AUD ~= $3.71 USD`

At current xAI STT prices, that API budget buys:

| Mode | xAI rate | Monthly hours inside $3.71 USD API budget |
| --- | ---: | ---: |
| REST/batch meetings and recordings | $0.10/hr | 37.1 hours |
| Streaming live dictation | $0.20/hr | 18.6 hours |

If the plan is primarily a diarized meeting-processing plan, then `A` can be:

- `30` one-hour diarized meeting recordings per month,
- REST/batch processing only for those meetings,
- transcript with speaker labels, word timestamps where available, and formatted
  text,
- meeting summary/action-item processing included,
- live xAI dictation not included in the same allowance, or limited separately.

Cost of that `A` package:

- STT: `30 hours * $0.10 = $3.00 USD`
- Meeting summaries/action items: roughly `$0.60-$1.00 USD` at this usage level
- Total estimated API cost: `$3.60-$4.00 USD`
- AUD equivalent at `1.45`: `$5.22-$5.80 AUD`

The upper end is slightly above the strict `$5.38 AUD` budget, so the cleaner
strict-margin package is:

- `25` one-hour diarized meeting recordings per month,
- meeting summaries/action items included,
- fair-use cap or paid packs above that.

Cost of the stricter `25` meeting package:

- STT: `25 hours * $0.10 = $2.50 USD`
- Meeting summaries/action items: roughly `$0.50-$0.85 USD`
- Total estimated API cost: `$3.00-$3.35 USD`
- AUD equivalent at `1.45`: `$4.35-$4.86 AUD`
- Charged at 30% markup: `$5.66-$6.32 AUD`

Recommended `A` for a `$7 AUD/month` Dictate Pro plan:

- `25` diarized one-hour meeting recordings per month included.
- This comfortably covers a target buyer with `1-2` important team meetings per
  week, which equals about `4-9` one-hour meetings/month.
- Keep an internal soft budget of `30` batch audio hours/month, but market the
  plan as `25` included meeting hours to leave margin for summaries, retries,
  exchange-rate movement, and unusually long files.
- Offer extra meeting packs at a clean marginal price, for example `10 extra
  meeting hours`.

## Qualification and positioning

A useful pre-qualification question is:

> How many important meetings do you have per week with your team?

The best-fit Dictate Pro buyer answers `1-2`. That user has enough recurring
meeting pain to value diarized transcripts and summaries, but does not create
heavy transcription cost. At `1-2` one-hour meetings/week, expected monthly
meeting usage is only `4-9` hours:

| Answer | Approx. meetings/month | Batch STT cost | Fit |
| --- | ---: | ---: | --- |
| 0 | 0 | $0.00 | Poor fit unless they need dictation |
| 1/week | 4.3 | $0.43 | Strong fit |
| 2/week | 8.7 | $0.87 | Strong fit |
| 3-4/week | 13.0-17.3 | $1.30-$1.73 | Still covered, but watch usage |
| 5+/week | 21.7+ | $2.17+ | Better fit for Pro or add-on packs |

This means the included allowance can be generous without being the headline.
Market the outcome instead:

- "Turn your important meetings into speaker-labelled notes."
- "Covers your weekly team meetings."
- "Includes 25 meeting hours/month."

Avoid leading with "25 hours" alone; high-volume users will anchor on the raw
allowance and consume the margin. The qualification question should identify
whether the buyer values the outcome, not whether they are shopping for bulk
transcription minutes.

Do not include `30 min/day` of live xAI streaming dictation in the same `$7 AUD`
Dictate Pro package under the strict 30% API-markup rule. That alone costs about
`15.2 hours * $0.20 = $3.04 USD/month`, leaving only about `$0.67 USD` for batch
meetings, or roughly `6` one-hour meetings before summaries. For this price
point, everyday dictation should use local/on-device transcription by default,
with xAI live dictation sold as a higher tier or add-on.

## Future higher tier shape

The first subscription is `Dictate Pro`, so this is not part of the initial
launch. If a later higher tier is added, reserve it for users who answer `3-5`
important meetings/week, or who want hosted live dictation in addition to
meeting processing.

A future higher tier could include:

- `50` diarized meeting/recording hours per month through REST/batch STT,
- `10` live xAI dictation hours per month through streaming STT,
- meeting summaries, decisions, action items, and follow-up drafts,
- priority processing queue for uploaded meetings,
- professional exports,
- paid extra hour packs above the included allowance.

## Diarization alternatives

xAI is already close to the lower end of hosted diarized transcription pricing
for one-hour meetings. Keep it as the default until a benchmark proves another
provider is cheaper at equivalent accuracy, diarization quality, latency, and
operational complexity.

Hosted alternatives to evaluate:

| Provider | Diarization support | Public price signal | Planning view |
| --- | --- | ---: | --- |
| xAI STT | `diarize=true` on STT requests | `$0.10/hr` REST, `$0.20/hr` streaming | Current default; cheapest clean fit found so far. |
| Google Cloud STT v2 | Speaker diarization via `diarization_config` | `$0.016/min` standard (`$0.96/hr`); dynamic batch `$0.003/min` (`$0.18/hr`) | Dynamic batch may be viable for low-urgency jobs, but still above xAI and needs a diarization quality check. |
| AssemblyAI | Speaker diarization add-on | base `$0.15/hr` + diarization `$0.02/hr` = `$0.17/hr` batch | More expensive than xAI, but worth benchmarking for accuracy and API ergonomics. |
| Rev AI | Diarization on async STT by default | Reverb Turbo `$0.10/hr`, English only | Price-competitive with xAI; test accuracy, diarization output shape, and commercial terms. |
| Deepgram | Diarization available | commonly around `$0.39-$0.46/hr` batch depending plan/model | Likely too expensive for `$7 AUD` Dictate Pro economics. |
| AWS Transcribe | Speaker diarization available | batch examples around `$0.006/min` (`$0.36/hr`) to higher regional/standard rates | Operationally heavier and likely more expensive than xAI. |
| Azure Speech | Diarization available; batch may include enhanced features | pricing varies by region/API; common standard batch references around `$0.36/hr` | Check only if Microsoft ecosystem integration becomes strategically important. |
| Soniox | Diarization supported | vendor comparisons claim roughly `$0.10-$0.12/hr` all-in | Potentially competitive; verify official account pricing and benchmark on real meetings. |

Local/open-source alternatives:

| Option | What it does | Fit for Dictate |
| --- | --- | --- |
| pyannote.audio Community-1 | Local speaker diarization pipeline; outputs speaker turns; PyTorch; Hugging Face gated model download, then offline use is supported. | Best first local diarization experiment. Pair with existing faster-whisper transcripts. |
| WhisperX | Combines Whisper/faster-whisper transcription, word alignment, and pyannote diarization. | Best integrated open-source meeting pipeline, but adds GPU/dependency weight. |
| NVIDIA NeMo diarization | Research/production toolkit with cascaded and end-to-end diarization models such as Sortformer. | Powerful but heavy; best for GPU-equipped users or server-side self-hosting experiments. |
| 3D-Speaker | Open-source speaker verification/recognition/diarization toolkit with pretrained models. | Candidate benchmark, but more research-grade than product-ready for Dictate. |
| WeSpeaker | Speaker embedding/verification toolkit with diarization recipes. | Useful building block, not a turnkey meeting-transcription feature. |
| SpeechBrain / Kaldi-style stacks | General speech toolkits with diarization components or recipes. | Too much integration work for the first paid release. |

Local diarization has no per-minute API cost, but it is not free operationally.
Expect higher support burden, model downloads, GPU/CPU variability, packaging
weight, and lower reliability on noisy/overlapping meeting audio. It should be
an experimental/private-mode feature until benchmarked.

Recommended benchmark order:

1. Keep xAI as hosted baseline.
2. Test Rev AI Reverb Turbo because it is price-competitive at `$0.10/hr`.
3. Test Google dynamic batch only if latency can be low priority.
4. Test Soniox if official pricing confirms `$0.10-$0.12/hr` all-in.
5. Prototype local `faster-whisper + pyannote.audio Community-1`.
6. Compare WhisperX as the heavier integrated local path.

Benchmark criteria:

- word error rate on real Dictate meeting samples,
- speaker diarization error and speaker-confusion rate,
- handling of overlap/crosstalk,
- processing time for a one-hour meeting on common laptops,
- install size and packaging risk,
- memory/VRAM usage,
- whether the output maps cleanly into Dictate transcript segments,
- total provider cost per successful one-hour meeting.

## Product guidance

- Use REST/batch STT for uploaded meetings and recordings by default.
- Use streaming STT only for live dictation or live meeting capture where the
  user needs immediate text.
- Track billable audio seconds server-side by subscription account.
- Store per-job provider mode (`rest` or `streaming`) so cost reporting is
  auditable.
- Expose subscription language as an allowance, not as "unlimited", unless there
  is a fair-use policy.
- Treat failed uploads/retries as part of gross margin planning. A `15-25%`
  overhead buffer is reasonable before there is real telemetry.

## Open checks before launch

- Confirm in the xAI console or account terms that `diarize=true` has no
  separate surcharge.
- Confirm rate limits for expected upload sizes and concurrency.
- Confirm whether streaming billing rounds by second, minute, or session.
- Decide whether Dictate absorbs overage, hard-limits after the included hours,
  or sells additional hour packs.
- Reprice the model if xAI changes STT pricing before Store submission.
