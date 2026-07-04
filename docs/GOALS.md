# Dictate Goals

This is the canonical goal document for Dictate. `INTENT.md` owns the durable
product intent; this file owns the current operating goals, release blockers,
and future target queue.

## Current Release Lane

The current public Windows lane is the Microsoft Store update draft for
`Arc Forge Dictate`.

Current state:

- Microsoft Store `Submission 2` is open in Partner Center.
- Store listing copy, screenshots, and square Store assets are staged.
- Package upload is intentionally held until the next app version is bundled
  and tested.
- Certification submission is intentionally held.

Release gates:

1. Bundle the next Windows Store MSIX.
2. Test the bundled version before upload.
3. Upload the package to the existing Store draft.
4. Run a real Windows 11 install/runtime smoke after package download or Store
   availability.
5. Review the Partner Center draft.
6. Submit for Microsoft certification only after explicit approval.

## To Be Implemented / Proven Before Stable

These are product requirements that must be either implemented or explicitly
closed as already done before the next stable public push.

1. **Production cloud API account path:** The hosted API/control-plane system must
   be live in production, not only sketched locally. Acceptance requires an
   owner-linked production account with real entitlement, usage, and hosted
   transcription API access; that account must be the account used by the
   maintainer's day-to-day Dictate installs. This must be proven on Windows as
   well as the current development platform.
2. **Audio visualizer proof:** The visualizer must be confirmed responsive to
   real microphone audio, not only synthetic animation. Acceptance requires a
   runtime smoke showing live input changes the visualizer, plus a graceful
   denied/no-device fallback.
3. **Hardware-tiered install defaults:** First-run setup should classify the
   machine into `minimum`, `recommended`, or `advanced` from simple local facts
   such as OS, CPU cores, RAM, GPU/CUDA availability, and disk headroom. Default
   to English Parakeet on CPU when available. On NVIDIA CUDA, provide an
   English-only performance lane and a multilingual quality lane; the current
   integrated CUDA-capable backend remains faster-whisper until Parakeet CUDA is
   implemented and benchmarked. AMD GPUs need separate MIGraphX/ROCm and
   Windows DirectML/MIGraphX paths rather than assuming the CUDA stack applies.
   Minimum-spec must remain a
   good experience with consistent transcription quality; it may trade speed and
   disable heavier features. Advanced-spec is reserved for GPU and future local
   WhisperX/diarization work until those paths pass packaging, legal, and
   benchmark gates.
4. **Benchmarked quality and speed tiers:** Define simple benchmark targets for
   quality and speed before changing model defaults. Quality should vary little
   across tiers; speed and optional features may vary. Benchmark details live in
   [../benchmarks/README.md](../benchmarks/README.md).
5. **No default hotwords:** Public builds must not ship user-visible default
   hotwords. The default config is empty, and UI placeholders must not seed
   sample words into real or perceived state. Future hotword UX should let a user
   click an incorrect dictated word, correct it, update the copyable transcript,
   and add the correction to hotwords automatically. Manual training is an
   acceptable early-access feature before automated correction.
6. **Early-access feature releases:** Some working features should be gated from
   stable releases because customers pay for early access. Decide the release
   model before shipping paid early access: either keep the repository open
   source with gated release channels/artifacts, or move to an open-core model
   where selected features are gated while the core remains open.

## Production P0: Dictate Pro Purchase And Entitlements

**Status:** Architecture documented; public marketing is live; purchase path is
not wired end-to-end.

The **Upgrade to Pro** button on <https://arcforge.au/download/dictate> currently
links to `/login` as a portal sign-in placeholder. Dictate Pro cannot be sold or
unlocked end-to-end until Stripe, the account system, and this app agree on
entitlement state.

Before treating Dictate Pro as shippable:

1. **Stripe:** Create Dictate Pro product/price(s) and checkout, separate from
   Arc Forge Agents Go/Plus/Ultra. Likely through gateway billing API +
   webhooks; see the checkout sketch in
   [dictate-pro-subscription-architecture.md](dictate-pro-subscription-architecture.md).
2. **Account / entitlement service:** Map active subscription state to a
   `Dictate Pro` entitlement on the customer account, including grace, expired,
   and quota states.
3. **Website:** Point **Upgrade to Pro** at the real checkout entry.
4. **Desktop app:** Expose entitlement in `GET /api/state`; gate hosted meeting
   mode, quota UI, and Pro affordances on subscription state.
5. **Verification:** End-to-end flow: marketing CTA -> pay -> portal shows Pro
   -> app unlocks meeting transcripts and early-access features.

Cross-repo surfaces:

- `arc-forge-website`: marketing CTA and download page.
- gateway/deck: checkout and webhooks.
- customer portal: `console.arcforge.au`.
- `dictate`: entitlement consumption and UI gating.

## Product Surface Goal

Dictate's current production surface is desktop. The desktop version should keep
a local-first posture for normal dictation wherever that gives the best user
experience, privacy, and reliability.

The product direction is broader than desktop:

1. Keep the desktop app as the primary daily-driver implementation target for
   now.
2. Do not design product concepts or architecture in a way that prevents a
   future mobile/on-the-run capture surface.
3. Treat mobile as a future product surface for quick capture, transcript review,
   and sending text onward, not as a replacement for desktop push-to-talk.
4. Keep shared concepts portable across surfaces: captures become transcripts or
   notes, transcripts can be accepted, copied, inserted, exported, or expanded,
   and hosted-model use is explicit.

## Transcription Notes Goal

Dictate should move toward a transcript-first note capture model. The canonical
local transcription, recording, meeting, model-lane, timestamping, speaker
attribution, and GPU plan is [TRANSCRIPTION_PLAN.md](TRANSCRIPTION_PLAN.md).
That document owns the current model direction.

Immediate direction:

1. Treat every capture as a `Note`: short dictation and long meetings are the
   same record type with different duration, provider, speaker, and processing
   state.
2. Preserve two user intents through mode/defaults, not separate heavy screens:
   dictation/plain recording and meeting.
3. Meeting mode always requires speaker attribution. The UI should expose this
   as "Meeting" rather than engine terminology such as "diarization".
4. Local recording and push-to-talk dictation should use the same ASR behavior;
   only Meeting changes the pipeline by adding speaker attribution.
5. Hide or de-emphasize hosted providers that cannot satisfy the meeting
   contract. Provider selection should be capability-based, not a flat model
   list.
6. Store transcripts as the durable artifact. Do not retain live-recording audio
   by default.
7. Long recordings must be streamed/chunked. The app must not hold hours of raw
   audio in memory, upload one giant file, or block on one final transcription
   request.
8. Persist note metadata and transcript segments incrementally: note id, mode,
   provider/model, start/end timestamps, duration, processing status, chunk
   sequence, speaker ids/labels, transcript text, and errors if any.
9. The UI should support in-app acceptance of dictation: after capture, the user
   can read, edit, accept, copy, insert, export, or expand the transcript without
   requiring another focused text field.

Local meeting diarization:

1. Follow [TRANSCRIPTION_PLAN.md](TRANSCRIPTION_PLAN.md) for ASR, diarization,
   timestamping, AMD/NVIDIA GPU, and benchmark decisions.
2. Before release, benchmark accuracy, RAM/VRAM use, runtime, installation
   weight, and long-meeting stability on representative recordings.
3. If local meeting speaker attribution is exposed before it is broadly proven,
   label it as experimental or high-performance-machine-only.

### Silence auto-pause (note recording)

**Status:** Partial. Auto-pause after 120s sustained silence, shared pause click,
and UI copy for silence-triggered pause are implemented. Manual pause/finish and
chunked local transcription are in place.

Long note sessions should not hold the mic open indefinitely during silence.
Quiet meetings must not fail silently — the user should get a clear, gentle
signal before capture stops waiting.

Direction:

1. **Auto-pause on sustained silence** — after **120 seconds** below a speech
   threshold, pause the note recording (same session as manual pause; do not
   auto-finish).
2. **Paused + silence** — do not count silence while already paused. The idle
   timer resets on resume.
3. **Remote cost** — auto-pause saves mic battery/CPU during long waits;
   VAD-at-transcribe only helps after the user stops and only affects decode,
   not live capture or remote upload size.
4. **Audible feedback** — play a short system or shipped sound (gentle click)
   when pause happens, for both auto-pause and manual pause. Reuse one asset so
   pause always feels the same.
5. **UI** — surface paused state clearly (existing cradle + finish flow); optional
   copy such as “Paused — no speech detected” for auto-pause only.

Non-goals for the first slice:

1. Do not auto-finish on silence; finishing stays explicit.
2. Do not use a shorter threshold that would interrupt legitimate quiet
   meeting stretches without the audible pause cue.

## Future Target: Media Notes

**Status:** Future product target selected. Implementation not started.

Media Notes extend the transcript-first note model to imported audio/video. This
is not the current release blocker, but it is the next coherent product expansion
after the live transcription and Dictate Pro entitlement path is stable.

The feature is not just file transcription. It is the foundation for video
digestion, where transcript segments, timestamps, playback, frames, visual
context, and extracted work can be joined into one useful note.

First production slice:

1. Add **Import audio/video** to the Notes or notebook surface.
2. Accept common phone and web media formats: `.m4a`, `.mp3`, `.wav`, `.mov`,
   `.mp4`, and `.webm`.
3. Imported media becomes a durable note immediately, with visible processing
   state: `queued`, `processing`, `ready`, or `failed`.
4. Keep recorded dictation and imported media in one Notes experience, but do
   not force imported media into the current rolling text-only history store.
5. Preserve the original imported file and derived assets until the media note
   is deleted. This is different from live dictation, where audio should still
   be discarded by default after transcription.
6. Make hosted-model use explicit when a step leaves the device.

### Media Notes Phase 1: Transcription

Ship this first.

1. Create a durable media-note store separate from `recent-history.json`.
2. Add a local async job runner for media processing.
3. Copy the original imported file into Dictate app data.
4. Probe metadata with `ffprobe`.
5. Extract normalized audio with `ffmpeg`.
6. Generate a timestamped transcript.
7. Write `transcript.json`.
8. Write `captions.vtt` for in-app playback subtitles.
9. Optionally write `captions.srt` for export compatibility.
10. Show the media note in Notes with processing state.
11. In expanded note view, show a player and clickable transcript segments that
    seek playback to the matching timestamp.

### Media Notes Phase 2: Visual Grounding

After Phase 1 is stable:

1. Generate a proxy video if needed for reliable playback.
2. Sample frames around transcript segments.
3. Add scene-change frame extraction.
4. Store selected frame thumbnails as derived assets.
5. Link transcript segments to relevant frames.
6. Show frame evidence in the expanded media note.

### Media Notes Phase 3: Digestion

After transcript and frame evidence are reliable:

1. OCR selected frames.
2. Run targeted multimodal analysis over transcript windows plus selected
   frames.
3. Extract meeting action items, decisions, open questions, mentioned tools, and
   referenced files or people.
4. Extract how-to procedures with step text, timestamps, and screenshots.
5. Keep every generated item linked back to exact media timestamps and evidence
   frames.

### Media Note Shape

```json
{
  "id": "media_...",
  "kind": "audio|video",
  "title": "Uploaded file name",
  "createdAt": "...",
  "status": "queued|processing|ready|failed",
  "source": {
    "originalPath": "...",
    "mime": "video/mp4",
    "duration": 612.4
  },
  "assets": {
    "original": "...",
    "audio": "...",
    "proxyVideo": "...",
    "captionsVtt": "...",
    "captionsSrt": "...",
    "transcriptJson": "...",
    "framesDir": "..."
  },
  "summary": null,
  "tasks": []
}
```

Media ingestion needs a richer transcript contract than
`SpeechToText.transcribe(...) -> str`:

```python
@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker: str | None = None


@dataclass
class MediaTranscript:
    text: str
    segments: list[TranscriptSegment]
    words: list[dict] | None = None
```

The initial implementation can use an in-process worker thread with persisted
job state. Avoid Redis, Celery, or a service dependency until Dictate has a
server-hosted ingestion path that truly needs it.

Media Notes first-slice non-goals:

1. Do not send the entire video to a multimodal model as the only pipeline.
2. Do not build summaries, task extraction, OCR, or frame reasoning before
   timestamped playback and transcript navigation work.
3. Do not store imported media in the existing capped recent-history file.
4. Do not make this a separate video app. It belongs inside Notes.

## Future Target: Local STT Quality Backlog

**Status:** Queued. Follows the local dictation streaming + hardware-aware
default-model work merged in the `forge/local-stt-streaming` review (dictation
now decodes overlapping, silence-aligned, prompt-threaded chunks that are merged
instead of a blind join of 2s context-free windows; one hardware-aware resolver
picks turbo on capable machines and small on weak CPUs, consistently across
startup, tray, doctor, UI, and installers).

These are the deliberately-deferred follow-ups from that review, roughly in
priority order.

**TOP PRIORITY — Input audio level management (AGC / normalization / clipping
guard).** Real-world finding: on a machine whose microphone works fine in
Telegram, Zoom, and normal voice calls, Dictate produced hallucinated/garbled
transcripts because it captures the **raw** `sounddevice` stream with no gain
management. On a hot mic the raw capture **clips** (peak > 0 dBFS) and Whisper
emits coherent nonsense ("thanks for watching", "Kayla and I are happy to fund
it"); at low gain the RMS is too quiet and it hallucinates from the language
prior. Voice apps avoid this with WebRTC-style **automatic gain control + noise
suppression**; Dictate has none. Lowering the OS mic gain is only a fragile
manual workaround. Implement, in the capture/pre-decode path:
   - Peak/RMS **input normalization** toward a target (e.g. ~ −20 dBFS RMS) with
     headroom, applied before the model sees the audio.
   - **Clipping / too-hot detection** with a clear user warning (and, ideally,
     soft limiting) — a clipping mic currently fails silently, which is exactly
     the "unusable" symptom.
   - Lower / adaptive **Silero VAD threshold** for quiet capture, and revisit the
     hardcoded `SILENCE_RMS` gate in `note_chunker.py` so soft speech is not
     dropped as silence.
   - Consider optional lightweight **noise suppression / AGC** so Dictate "just
     works" on the same mics every other voice app handles.
   This is the second half of making local dictation genuinely usable — the
   streaming fix removed the boundary "confetti"; this removes the
   garbage-in/garbage-out from unmanaged input levels.

1. **Dynamic runtime backpressure / auto-tier-down.** Static hardware gating
   (RAM + core count) currently decides turbo-vs-small at startup. Add a runtime
   guard that measures streaming decode real-time-factor and degrades gracefully
   when the streamer falls behind: drop turbo->small mid-session, and when even
   small cannot keep real-time (weak 2-4 core / no-AVX2 CPUs, Pi-class hardware),
   disable local streaming and surface a "recommend a hosted key" notice via the
   existing `result.notice`/supervisor path rather than silently backing up the
   partial-audio queue and dropping words.
2. **Quiet-microphone robustness.** Add peak/RMS input normalization before
   decode and lower the Silero VAD threshold for quiet capture; revisit the
   hardcoded `SILENCE_RMS` gate in `note_chunker.py` so soft-spoken speech on
   built-in laptop mics is not misclassified as silence.
3. **Language pinning.** Persist a `language` setting in config (and expose it via
   `dictate config`) and thread it through, so short accented utterances stop
   flipping language per chunk under auto-detect.
4. **Hardware guidance docs.** Publish a spec sheet in the README/install docs
   from [TRANSCRIPTION_PLAN.md](TRANSCRIPTION_PLAN.md), including CPU minimums,
   NVIDIA CUDA, and first-class AMD GPU support.
5. **GPU local model lanes.** Implement and benchmark the model lanes defined in
   [TRANSCRIPTION_PLAN.md](TRANSCRIPTION_PLAN.md). Do not make any GPU or CPU
   multilingual lane the default until it passes the benchmark matrix and
   packaging checks.
6. **Dead-code cleanup.** Remove the unwired `whisper_cpp_backend.py` (plus its
   test, the `WhisperCppModel` literal, and the stale NeMo `__pycache__`
   remnant), or wire it up deliberately — it is currently unreachable.
7. **CLI flag rename (breaking).** The installer prepare-step flag is still named
   `--no-prepare-turbo` / `-NoPrepareTurbo` although it now prepares the
   hardware-aware default. Rename to `--no-prepare-model` in a batch with other
   CLI-contract changes so existing install scripts are not broken piecemeal.

Accepted limitation (documented, not a bug): when an utterance ends exactly on a
silence boundary, the final decoded chunk keeps `long_form` off-guard behavior
from the previous chunk; fixing it would require a re-decode that reintroduces
end-of-clip latency, which the streaming design explicitly avoids. Trailing
silence is already trimmed, so hallucination risk is negligible.

## Current Operating Posture

- Microsoft Store is the primary public Windows distribution target.
- Signed website/GitHub downloads remain a secondary fallback path.
- Hosted PowerShell bootstrap instructions are developer/source install guidance,
  not the normal public Windows install path.
- New npm package and install paths use `@arcforgelabs/dictate`.
- The deprecated personal npm package path should remain published only as a
  compatibility landing point unless there is a specific security or legal
  reason to remove it.
- Dictate is a public open-source repository.
- Arc Forge ClawSweeper and its durable state repository remain private.
- ClawSweeper is currently review/comment only for Dictate.
- Partner Center state changes over time; check Partner Center or
  `.github/workflows/msstore-publish-msix.yml` in `mode=status` for live Store
  status rather than relying on historical run IDs in this public doc.

## References

- [INTENT.md](../INTENT.md)
- [CHANGELOG.md](../CHANGELOG.md)
- [dictate-pro-subscription-architecture.md](dictate-pro-subscription-architecture.md)
- [frontend-wiring.md](frontend-wiring.md)
- [release-versioning.md](release-versioning.md)
- [deployment-security.md](deployment-security.md)
- [msstore-automation.md](msstore-automation.md)
- [msstore-listing.md](msstore-listing.md)
