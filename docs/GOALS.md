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

Dictate should move toward a transcript-first note capture model. The first
production implementation is word-for-word transcription only: no summaries,
action items, cleanup, or note intelligence in the first slice.

Immediate direction:

1. Treat every capture as a `Note`: short dictation and long meetings are the
   same record type with different duration, provider, speaker, and processing
   state.
2. Preserve two user intents through mode/defaults, not separate heavy screens:
   - **Dictation:** plain verbatim transcription, no speaker labels by default,
     suitable for prompts, email, and text insertion.
   - **Meeting:** verbatim transcript with diarization/speaker labels enabled by
     default.
3. Make hosted xAI the first production meeting path because it supports the
   required meeting contract: streaming/chunked speech-to-text plus speaker
   labels/diarization.
4. Keep proven local models available for direct dictation and offline fallback.
   Do not present local models as production-ready meeting diarization until
   separately benchmarked.
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

Deferred local meeting diarization:

1. Local meeting diarization is experimental, not part of the first production
   meeting path.
2. Candidate local paths include WhisperX + pyannote, pyannote paired with
   existing local STT, and NVIDIA NeMo diarization.
3. Before release, benchmark accuracy, RAM/VRAM use, runtime, installation
   weight, and long-meeting stability on representative recordings.
4. If local meeting diarization is exposed before it is broadly proven, label it
   as experimental or high-performance-machine-only.

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
