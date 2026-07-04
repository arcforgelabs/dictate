# Design Sync-Back Queue

Local UI/UX changes made **directly in code** on the live or dev build that still
need reflecting back into cloud Claude Design.

- The build/dev lane that makes a directly-requested change **appends a row** to
  the Open list below.
- The orchestrator working with Claude Design **drains** the queue: for each row
  it first compares the local change against the intended cloud design, then
  either pushes the change to cloud (genuine divergence) or closes it as a no-op
  (the local edit merely realigned a drifted local/prod build to what cloud
  already specifies — no cloud change needed). Then it checks the row off.
- This is **temporary coordination state**, not a durable record. Prune Done rows
  periodically. Never let this become a second copy of the change itself.

Row format (keep it to a few lines):

```
- [ ] <date> — <short change summary>
      code: <file(s)/route> → cloud: <project-id> / <file path>  (or "needs mapping")
      by: <agent/lane> · branch/commit: <branch> @ <sha>
      why: <one line>
      notes: <fixture/state caveats, asset needs, blockers>
```

## Open

- [ ] 2026-07-03 — Local engine toggle (Private mode only): "English" ⇄ "Multilingual" segmented control beside the privacy pill
      code: ui/src/App.jsx (LocalEngineToggle, added to HomeBar left next to PrivacyPill), ui/src/store.jsx (MODELS + modelById), ui/src/styles.css (.engine-seg/.engine-opt) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / comp-capture-home.html (needs mapping)
      by: forge build lane (Opus) · branch/commit: master (uncommitted)
      why: on-device now has two engines — English (Parakeet, fast+accurate) default vs Multilingual (Whisper); user asked for a simple speed/quality-style switch, reframed to English/Multilingual since Parakeet wins both on CPU
      notes: NO brand names surfaced (design rule); only visible in Private mode; minimal segmented pill matching .privpill/.updpill aesthetic; writes stt_backend=parakeet / faster-whisper via existing config PATCH

- [ ] 2026-06-24 — Capture home idle copy: "Ready to dictate" (was "Ready to capture")
      code: ui/src/App.jsx (CaptureHome) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / comp-capture-home.html
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: clearer everyday language for the idle mic state
      notes: subline still "Press the mic and speak." + shortcut hint in t-mono

- [ ] 2026-06-24 — Privacy control: text pill → toggle + mode icon (shield private / cloud online)
      code: ui/src/App.jsx (PrivacyPill), ui/src/primitives.jsx (Toggle), ui/src/styles.css (.privpill) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / comp-capture-home.html
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: one quiet control for on-device vs cloud; icon reflects active mode
      notes: degraded state keeps shield + amber `.privpill.degraded`; tooltip/aria flip between "Private mode" and "Cloud mode"

- [ ] 2026-06-24 — Missing-key toast: "Requires Dictate Pro or API key." (+ copy action)
      code: ui/src/App.jsx (PrivacyPill onToggle), ui/src/store.jsx (XAI_API_KEY_AGENT_INSTRUCTIONS) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / comp-capture-home.html (toast fixture)
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: explain why cloud mode cannot be enabled without Pro or a key
      notes: bad toast, 12 s, copy button ships agent/CLI instructions

- [ ] 2026-06-24 — Toast width: max-width 330px → 480px (single-line long copy)
      code: ui/src/styles.css (.toast) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / needs mapping (DS toast spec)
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: Pro/API-key toast was wrapping to two lines
      notes: applies to all toasts globally

- [ ] 2026-06-24 — Shared home/notes top bar: HomeBar + NotebookToggle (dictations ↔ capture)
      code: ui/src/views.jsx (HomeBar, NotebookToggle), ui/src/App.jsx (CaptureHome) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / comp-capture-home.html + comp-notes-list.html
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: same `.notes-search` row geometry on capture home and dictations list
      notes: replaces old `.home-top` (privacy pill + history ibtn); notebook icon toggles view; active state uses `.view-toggle.on`

- [ ] 2026-06-24 — Pause / resume / finish recording on Breath Cradle
      code: ui/src/App.jsx (CaptureHome), ui/src/visualizers.jsx (BreathCradle), ui/src/styles.css (.recbtn.paused, .note-finish-btn) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / comp-capture-home.html (recording + paused states)
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: hover-to-pause/resume session; explicit "Finish note" when paused
      notes: paused UI shows timer + "Hover the mic to resume, or finish the note."; degraded strip hidden while paused

- [ ] 2026-06-24 — Note flow: drop NoteReady; transcribe → ExpandedNote directly
      code: ui/src/App.jsx (remove NoteReady, noteView state machine) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / needs mapping (expanded-note prototype)
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: fewer intermediate surfaces; read/copy/export immediately after transcribe
      notes: Insert/Open-note/overflow stage retired from production

- [ ] 2026-06-24 — Expanded note chrome: remove Back; notes-search top bar + Close (×)
      code: ui/src/App.jsx (ExpandedNote), ui/src/views.jsx (NotebookToggle inExpanded) → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / needs mapping (expanded-note prototype)
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: back chevron redundant; close returns via expandedFrom routing (history or capture home)
      notes: top row = title · grow · Copy · Export as Markdown · Close; uses `.notes-search.note-exp-top`

- [ ] 2026-06-24 — Export as Markdown via native save dialog (Tauri)
      code: ui/src/App.jsx, ui/src/views.jsx, ui/src/ipc.js (saveTextFile), ui-shell/src-tauri/ → cloud: 2477ec21-a493-41a0-b400-2a65c5bc3bf6 / needs mapping (expanded + notes list row actions)
      by: Cursor build lane · branch/commit: master @ 8411a3d (uncommitted)
      why: real file save instead of clipboard-only export
      notes: download icon; toast "Saved as Markdown" on success

## Done

<!-- Closed rows (synced OR no-op realignment). Prune these periodically. -->
