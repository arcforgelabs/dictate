# Dictate Goal

## Status

The repository-side Windows release, Microsoft Store package, Store API smoke,
and Dictate/ClawSweeper integration work is complete. The current public
release lane is `v2026.6.20`.

Completed implementation details and verification IDs have been moved to the
root `CHANGELOG.md`. This file now tracks only the remaining goal work.

## Remaining Work

### Design Feedback Loop (next order of business)

Stand up a fast loop for marking up and adjusting the UI: reconstruct the current
production UI (`ui/src/`) 1:1 inside the Claude Design project so the maintainer
can annotate items for improvement, then sync changes back to `master`. First
target is refining the Settings/gear menu. Full plan and surface inventory:
[docs/claude-design-workflow.md](claude-design-workflow.md).

### Windows CI crash — FIXED (2026-06-23)

The Windows unit-test jobs crashed with exit `0xC0000142` (red on `master` since
the `2026.6.22` single-instance-guard work). Root cause: `process_lock._pid_is_running`
used `os.kill(pid, 0)`, but on Windows `signal 0 == CTRL_C_EVENT`, so the liveness
probe delivered a Ctrl+C to the console process group — including the test runner —
surfacing as a non-deterministic `KeyboardInterrupt`. Fixed by routing Windows to a
`ctypes` `OpenProcess` liveness check (never `os.kill` on win32); CI is green.

This was also a real **product** bug: the daemon single-instance guard's liveness
check would misbehave on Windows. `v2026.6.23` shipped Linux-only before the fix.

Note on Windows public distribution: the GitHub release workflow only attaches
**signed** Windows `.msi`/`.exe` artifacts, and no signing certificate is configured
(see signing items below), so a Windows-inclusive *public GitHub* release is not yet
possible — the public Windows channel is the Microsoft Store lane. Re-running
`release.yml` on a fixed tag would produce only unsigned internal artifacts.

### Product Surface Goal

Dictate's current production surface is desktop, and the desktop version should
keep a local-first model posture for normal dictation wherever that gives the
best user experience, privacy, and reliability.

The product direction is broader than desktop:

1. Keep the desktop app as the primary daily-driver implementation target for
   now.
2. Do not design product concepts or architecture in a way that prevents a
   future mobile/on-the-run capture surface.
3. Treat mobile as a future product surface for quick capture, transcript review,
   and sending text onward, not as a replacement for desktop push-to-talk.
4. Keep shared concepts portable across surfaces: captures become transcripts or
   notes, transcripts can be accepted/copied/inserted/exported, and hosted-model
   use is explicit.

### Transcription Notes Goal

Dictate should move toward a transcript-first note capture model. The first
implementation is **word-for-word transcription only**: no summaries, action
items, cleanup, or note intelligence.

Immediate production direction:

1. Treat every capture as a `Note`: short dictation and long meetings are the
   same record type with different duration, provider, speaker, and processing
   state.
2. Preserve two user intents through mode/defaults, not separate heavy screens:
   - **Dictation**: plain verbatim transcription, no speaker labels by default,
     suitable for prompts, email, and text insertion.
   - **Meeting**: verbatim transcript with diarization/speaker labels enabled by
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
6. Store transcripts as the durable artifact. Do not retain audio by default.
   Audio chunks should be discarded as soon as they have been successfully
   transcribed/diarized and persisted as transcript segments.
7. Long recordings must be streamed/chunked. The app must not hold hours of raw
   audio in memory, upload one giant file, or block on one final transcription
   request.
8. Persist note metadata and transcript segments incrementally: note id, mode,
   provider/model, start/end timestamps, duration, processing status, chunk
   sequence, speaker ids/labels, transcript text, and errors if any.
9. The UI should support in-app acceptance of dictation: after capture, the user
   can read, edit, accept, copy, insert, export, or expand the transcript without
   requiring another focused text field.

Deferred / future work:

1. Local meeting diarization is a future experimental feature, not part of the
   first implementation.
2. Candidate local paths include WhisperX + pyannote, pyannote paired with
   existing local STT, and NVIDIA NeMo diarization. These require a separate
   benchmark pass for accuracy, RAM/VRAM use, runtime, installation weight, and
   long-meeting stability.
3. If local meeting diarization is later exposed, label it as experimental or
   high-performance-machine-only until it is proven on representative
   multi-speaker recordings.

1. For Store updates, run the guarded Microsoft Store MSIX workflow in
   `mode=draft`, review the draft in Partner Center, then run `mode=publish`
   only when ready for Microsoft certification.
2. Run a real Windows install/runtime smoke after package download or Store
   availability for each material release.
3. Configure a real Windows signing certificate in GitHub Actions before
   attaching `.msi` or `.exe` installers to public GitHub releases. The signing
   script and release workflow path exist, but no signing certificate secret is
   currently configured.
4. Keep the GitHub release lane and Microsoft Store publication lane separate:
   a GitHub release does not automatically make a Store update available.
5. Keep ClawSweeper scheduled/background runs disabled for Dictate until the
   maintainer decides scheduled fanout should begin. Manual smokes are passing;
   `CLAWSWEEPER_ENABLE_SCHEDULES` remains `0`.
6. Review and explicitly approve any future Dictate ClawSweeper auto-close
   policy before enabling it.

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
- Recent manual ClawSweeper smokes passed for Dictate and Arc Forge Console.
- Partner Center state changes over time; check Partner Center or
  `.github/workflows/msstore-publish-msix.yml` in `mode=status` for live Store
  status rather than relying on historical run IDs in this public doc.
- UI Dependabot alerts for `vitest`, `vite`, and `esbuild` were remediated by
  upgrading the UI development toolchain; `npm audit` now reports zero
  vulnerabilities in the UI package.

## References

- [CHANGELOG.md](../CHANGELOG.md)
- [docs/release-versioning.md](release-versioning.md)
- [docs/msstore-automation.md](msstore-automation.md)
- [docs/msstore-listing.md](msstore-listing.md)
