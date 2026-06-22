# Claude Design — design-authority review of the Note Capture lock

Source: Dictate Design System cloud project `2477ec21-a493-41a0-b400-2a65c5bc3bf6`,
fresh chat, Opus 4.8, 2026-06-21. Critique-only (agent confirmed "No files touched").
Reviewed against actual files: `colors_and_type.css`, the kit (`note-app.jsx`,
`visualizers.jsx`, `icons.jsx`, `styles.css`), and DS spec card `comp-speaker-line.html`.

## 1 · Direction soundness — SHIP
Note Capture is the right lock. One object (a Note), one primary gesture (the mic
toggles), states instead of views — exactly what subtract-first and one-primary-per-
surface want. The seven-view console split attention across modes a capture utility
never needed; folding provider/mic/visualizer/appearance behind the gear and making
"the note the product" is a genuine reduction, not a reskin. The `note-app.jsx` state
machine covers the full happy path plus every fault calmly, and the model holds at both
extremes (5-second dictation and 90-minute meeting are one object). **No reason to
redirect. Ship the direction; the items below are pre-lock fixes, not reasons to reopen.**

## 2 · Pre-lock checklist
- **(a) Light-theme parity — ⚠️ CONFIRMED (partial).** Every state renders in light
  (theme/preview are independent), but parity fails on one pervasive element: speaker-
  name contrast (see b). Affects all states rendering `SpeakerLine` / `TranscriptStream`
  / the ring-wave preview.
- **(b) Legibility floor — ⚠️ CONFIRMED. Two problems:**
  - *Speaker names fail AA in light, every surface.* `icons.jsx` hardcodes
    `SPEAKERS.you.color = var(--live)`, `maya = var(--amber)`, `devin = #6f8fb3` — the
    raw tokens the README brands "not for text" (`--live` ≈3.2–3.7:1, `--amber` ≈3.8:1,
    `#6f8fb3` on white ≈3.4:1), applied to `.spk-name` (12px/700). *Fix:* per-theme text
    variants (e.g. darkened devin ~`#4f6f96`); dark keeps current values; update data in
    `icons.jsx` and swatches in `comp-speaker-line.html`.
  - *Sub-12px running meta.* `.longstrip` is 10.5px sentence-case meta (not a chip) in
    `--subtle`, below the stated 12px meta floor. `.po-tag` (9px) and `.t-label`/
    `.ts-toggle` (10px) are uppercase chips but 9px caps is hard. *Fix:* lift `.longstrip`
    to 12px; floor chip caps at 10px.
- **(c) Ring/Wave aria-live — ✅ CONFIRMED.** Only `TranscriptStream` carries
  `aria-live="polite"` (`visualizers.jsx`). Ring/wave partial transcript renders in
  `.preview-line` in `Capture` (`note-app.jsx`) with no live region — a screen-reader
  user on the default visualizer hears nothing while recording. Same gap on Processing's
  `.proc-lines`. *Fix:* wrap `.preview-line` and `.proc-lines` in `aria-live="polite"`.
- **(d) Brand mark candidate — ⚠️ CONFIRMED not finalized.** `aria-label="Dictate mark
  candidate"`, gear footer renders "Dictate mark — candidate", README calls it an
  exploration. *Fix:* ratify or replace the cradle-mic, then drop the "candidate" label
  in `GearMenu` and the aria-label.
- **(e) Note-ready hierarchy — ✅ NOT an issue.** Insert as the single filled primary is
  correct. (But see Accept/Insert ambiguity below.)

## 3 · What the forge review missed (design-authority view)
- **Status-copy fork.** Live status wording changes on a *cosmetic* choice: "Recording…"
  for stream vs "Recording" for ring/wave. Status shouldn't change wording based on the
  visualizer. Pick one (the ellipsis matches the calm-rhythm voice).
- **Accept/Insert model ambiguity** (P2) — the two actions' meanings overlap.
- **Edit / Read-full-note redundancy** (P3) — both route to the expanded note.
- **Gear "Microphone" is a dead row** (P3). `.menu-row.static` shows "MacBook Mic" with
  no picker yet sits among interactive rows; README lists microphone as a gear setting —
  it's display-only. *Fix:* make it open a device list, or visually de-emphasize as read-only.
- **Motion — clean, no finding.** Reduced motion degrades correctly to static state-color
  across `.ring-pulse`, `.recbtn.rec`, `.dot.live` (media query + `.reduce-motion` class).
  "Recording…" at 19px/800 in `--live` clears large-text AA (3:1).

## Severity roll-up
- **P1** — speaker-name AA failure in light (b), baked into the spec card.
- **P2** — aria-live gap on default visualizer (c); unratified brand mark (d); Accept/Insert ambiguity.
- **P3** — sub-12px longstrip; Edit/Read-full-note redundancy; status-copy fork; dead mic row.

## Verdict
**VISUAL NOT CLEAN** — one P1 (light-theme speaker contrast, propagated into the
documented card) plus the aria-live and brand-candidate loose ends must close before lock.
**Direction verdict: ship.**
