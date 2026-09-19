# Note Capture — Core Design Lock

**Frozen:** 2026-09-20 · **Branch under test:** `stt-model-refresh-2026-09` · supersedes the
2026-06-22 freeze (prototype baseline + gear-wheel chrome + xAI provider toggle).

## Source of truth
Tokens and brand-book rules: the **Dictate design system artifact**
<https://claude.ai/artifact/2kMgmfMmYfH5xDuBxKye7D> (`project/README.md`, `project/tokens.json`).
Implementation: `ui/src/` (`styles.css` + `App.jsx` / `views.jsx` / `overlays.jsx` /
`platform/TitleBar.jsx`). This lock is the deliberate freeze of the shipped views after the
design-system alignment (PR #50); `captures/` are the reference renders the next change is
measured against. There is no separate prototype baseline any more — the shipped app *is* the
baseline, and the artifact is the spec it must keep satisfying.

## Locked scope — capture + notes + chrome
1. **Capture home** — the Breath Cradle: the cradle-mic mark (`assets/dictate-mark-ink.svg`
   geometry, `currentColor`) IS the button. Under it: `Click to dictate` (UI face, muted),
   then on a fresh launch the hint `or hold` + the shortcut as `kbd` caps (`Right Ctrl`) and
   the keyboard graphic pointing at that key. Once capture has begun this session, the
   `Copy last dictation` pill (fg label, muted preview) replaces the hint. Home bar: update
   pill (amber when an update is ready / restart pending; danger only on failure), About,
   `Meeting` and the Dictations toggle. **No gear, no settings menu, no provider names.**
2. **Recording** — `Recording` / `Meeting` in `live`, mono timer, wave timeline or the live
   transcript preview. Reduced-motion: halo static at 50 %, never invisible.
3. **Paused** — `Paused` / `Paused — no speech detected` in muted, timer, `Finish note`
   (or `Finish meeting`) + a danger-on-hover discard button → alertdialog (`Discard note?`,
   `Cancel` + danger `Confirm`).
4. **Transcribing** — indeterminate ink bar, prose sub in the UI face.
5. **Dictations** — search row (`Search dictations`, All / Meetings / Quick segment, toggle),
   rows with fg text + mono meta line, archive / copy / export on hover; empty and
   no-results states in fg title + muted sub.
6. **Expanded note** — `Note · time · ago` title, copy + export, back column. Meeting notes
   render the **segment grid**: speaker label full-width (12.5px, 700), then a
   `minmax(96px,120px)` gutter holding the mono `t-mono` timestamp on a 26px line box so it
   sits on the first prose line, then the 15px/1.75 text. Quick notes render one prose
   block at the 65ch measure.
7. **About** — mark + `Dictate` + version/channel, Model / Updates rows, `Check for update`
   secondary + **one** primary `Update` (ink on paper), privacy note in muted 12.5px.
8. **Command palette** — `Esc` cap, `Go to` / `Actions` groups at t-label metrics.
9. **Chrome** — one title bar: mark at 16px, drag region, per-OS window controls. Nothing
   else in it. System-theme default; light and dark both locked.

## Rules that gate this lock (from the brand book)
- One `primary` per view; never primary for cancel / dismiss.
- `live` = listening only; `amber` = attention that can wait; `danger` = destructive /
  failed, always with a word or icon.
- `muted` never below 12.5px and never for instructions; anything actionable is `fg`.
- JetBrains Mono only for counted things (timers, timestamps, key caps, counts).
- Every shortcut mention is a `kbd`. No emoji, no vendor names, sentence case except
  `t-label` / `chip`.

## Captures
`captures/<state>-win-<theme>.png` at 1200×820, both themes, states: `ready`, `recording`,
`paused`, `dictations`, `meeting-note`, `quick-note`, `about`, `palette`. `manifest.json`
lists them. Rendered from the mock-mode dev server (`XDG_DATA_HOME` pointed at an empty
dir so the bridge plugin does not attach to a running engine) with
`design/tools/capture-lock.mjs`:

    XDG_DATA_HOME=/tmp/empty ui/node_modules/.bin/vite ui --port 5179 &
    PLAYWRIGHT=<path>/node_modules/playwright/index.mjs CHROME=/usr/bin/google-chrome \
      node design/tools/capture-lock.mjs design/locks/note-capture-core/captures

## Explicitly OUT of this lock
- Window size / per-OS title-bar polish (the Tauri window is larger than the design frame).
- `Microsoft Store · Stable` in About on Store installs — a distribution channel, allowed.
- The 11px compact chrome pills (`engine-opt`, `upd-main`, `upd-mini`, `about-channel`).

## Gate rule
For the locked scope, any visible extra / missing / changed element, label, state or colour
role in the implementation vs `captures/` is **VISUAL NOT CLEAN** unless a design-system
change (artifact republished) explains it and this lock is re-frozen alongside.
