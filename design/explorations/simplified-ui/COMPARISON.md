# Dictate — Simplified UI Concepts

Concept exploration for reducing visual/mental load on the Dictate Settings
window. Three directions, each shown light · dark · recording.

**Open:** `Dictate Simplified UI Concepts.html` (renders all three on a canvas).
**Maintained production prototype is untouched:** `dictate-app/Dictate Settings.html`.

---

## The three concepts

### A · Minimal Home
One calm screen. A single status line (`● Ready · model · mic`) over **two tiles**:
Quick dictation (primary, ink) and Record conversation (secondary, with the one
`xAI speaker labels` chip that informs the Record decision). Everything else —
model, mic, hotkeys, startup, update — collapses behind the **gear + ⌘K**.
Recording replaces the whole body with a single breathing orb, waveform, timer,
and release hint.

- **Load:** lowest. Two actions, one meta line, zero nav rail, zero settings rows.
- **Cost:** settings are a click away (gear/⌘K), so power-tuning is slightly slower.

### B · Mode Switcher
A centered segmented control — **Quick dictation | Record conversation** — that are
mutually exclusive. Only the active mode's context shows: Quick shows the hold
target + shortcut and nothing about recording; Record shows the record button plus
the *single* control that matters there (`Speaker labels · xAI`, saved-to-history).
Recording is just the Record mode mid-capture (stop, waveform, timer).

- **Load:** low, and conceptually cleanest — the modes can never bleed into each
  other, which directly fixes the "duplicated capture sections" problem.
- **Cost:** one action is always hidden behind the toggle; a two-second tax to switch
  intent. Capture is never one-glance-both.

### C · Compact Console
Power-user. No left rail — a **top icon-tab strip** replaces it. Quick + Record sit
as a compact two-button capture bar over one mono meta line, with the essential
settings as three quiet hairline rows (Model / Microphone / Shortcut), each a
disclosure into detail. Recording collapses the capture bar into a slim listening
strip and dims the rows.

- **Load:** medium but *calm* — denser than A/B yet far lighter than today's rail +
  cards + chips. Best information-per-pixel.
- **Cost:** icon-only tabs need tooltips/learning; densest of the three.

---

## Recommendation — lock **A · Minimal Home**, borrow C's settings pattern

For a **daily-driver dictation utility**, the job 95% of the time is "start talking."
A makes both capture modes one glance away with the least to read, which is exactly
the brief: quiet by default, recede until summoned. It keeps Quick and Record
**visually and conceptually separate** (two distinct tiles) without a mode tax, and
it pushes all configuration — the source of today's clutter — behind a single gear
and ⌘K.

B is the runner-up and the right call *if* recording is a co-equal daily action; its
mutual-exclusion is the strongest single fix for duplicated capture UI, but hiding
one mode behind a toggle is the wrong trade when Quick dictation dominates usage.

C is the right **settings/detail** surface, not the home. Adopt its hairline
disclosure rows for the screens behind A's gear, so the collapsed settings stay
calm and dense rather than reverting to today's card stack.

**Net target:** A as the home surface; C's row pattern for the settings screens it
reveals; B's mode discipline as the rule that Quick and Record never share a panel.

---

## Exact production removals / collapses

Apply to `dictate-app/Dictate Settings.html` when porting the locked target:

**Navigation**
- Remove the persistent 236px **left rail** as the primary surface. Home is capture,
  not navigation. Move destinations into ⌘K + the gear menu (C's top tabs are the
  fallback if a persistent nav is required).
- Keep **⌘K** as the real navigation; it already exists.

**Capture**
- Collapse to **exactly two capture affordances** — one Quick, one Record. Delete any
  second/duplicated capture section (the Status hero "Hold to try" + a separate
  try-it/Notes sandbox should become a single Quick tile).
- Show `xAI speaker labels` **only on the Record affordance** (the one place it informs
  a decision). Remove it everywhere else.

**Chips / badges / labels**
- Drop decorative chips and nav badges. Keep only: the live `●` dot, the Record
  `xAI` chip, and genuinely-actionable amber/danger states.
- Collapse repeated overline labels; the single mono status line carries model · mic.

**Update / status clutter**
- Keep Engine/App-window version detail, install-kind copy, and the update flow on the
  **App update screen only** (behind the gear). On the capture/home surface show
  **nothing** unless action is required — then a single slim banner (the existing
  `.updbar` stale-shell affordance), not a panel.
- No status panels, doctor cards, or version strings on the home screen.

**Settings visibility (progressive disclosure)**
- Default home shows **zero** settings rows. Reveal Model / Microphone / Shortcut /
  Startup / Advanced only via the gear, rendered as C's quiet hairline rows.
- Keep **launch-on-sign-in** as a single inline control inside settings — not a
  separate nav destination, and not duplicated across screens.

**Motion**
- Preserve the one 3.8s breath as the only loop (live dot / orb / rec light); honor
  `prefers-reduced-motion`. No new animation.
