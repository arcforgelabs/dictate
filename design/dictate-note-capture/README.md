# UI Kit — Dictate Note Capture (the locked direction)

A high-fidelity, interactive recreation of Dictate's **Note Capture** window — the
product's single locked direction. The centered **microphone is the record button**:
press to start, press again to stop. Every capture is a **Note** — a short dictation
and a long meeting are the same object with different duration and states.

Open **`index.html`** to use it. It's designed at 460×700, fits-to-viewport, and runs
client-side with React + Babel from CDN. **Fonts are local** (via the design system's
`@font-face`), so it renders offline.

## What works (interactive)
- **The mic toggles.** Click it (Ready → Recording); the mic — the **Breath Cradle** — fills
  green and breathes on the 3.8s loop, a timer runs, and a live partial transcript streams
  in. Click again → **Note ready** (short dictations skip Processing for felt speed; long
  recordings show a calm **Transcribing…** with indeterminate progress).
- **One capture gesture** — the **Breath Cradle**: the brand mark *is* the record button;
  rings bloom only on real emphasis and recede to stillness in silence. No visualizer picker.
- **Note ready** — **Insert** is the single filled primary; **Open note** is secondary;
  **Copy / Export** live in an overflow (⋯). Notes auto-save, so there is no Accept step.
- **Expanded note** — readable transcript, speaker labels, **search**, a **Times** toggle,
  copy / export.
- **Transcription is automatic** — xAI online, on-device offline. The gear offers one
  **Always on-device (private)** toggle (off = automatic); no provider picker, no matrix.
- **Every fault/blocker state** — first-run/empty, microphone blocked, no device, capture
  failed (Retry / Use on-device), on-device fallback active, connection hiccup, interrupted.
  All calm: reassurance first, amber for caveats, **no alarm-red** on recoverable states.
- **Light / dark** and a **reduce-motion** toggle — both first-class. Reduced motion
  degrades the breath + rings to a **static state-color**, never to nothing.
- **Tweaks panel** (review-only) jumps to any state, scenario (short/long), and visualizer.

## Files
| File | Role |
|---|---|
| `index.html` | Host: loads the design-system styles + React/Babel, mounts `<App>` |
| `styles.css` | `@import`s the design system tokens (`../../colors_and_type.css`), then the note-capture component layer (capture surface, note, expanded, provider sheet, notice, gear menu, toasts) |
| `note-app.jsx` | State machine + every screen + gear / provider sheets. Exports `App` |
| `visualizers.jsx` | `BreathCradle` — the ONE recording gesture: the cradle-mic mark is the button; it breathes on the 3.8s loop and blooms a ring only on emphasis (recedes in silence; static under reduced motion) |
| `icons.jsx` | `Mark` (the cradle-mic brand mark), `Icon` line set, `Keys`, speaker + sample-transcript data, helpers (`fmt`, `tokens`, `getPartial`) |
| `tweaks-panel.jsx` | The review-only Tweaks shell + `useTweaks` |

## How to reuse
- Components export to `window` (`Object.assign(window, {…})` at the bottom of each JSX).
  Load order: `tweaks-panel → icons → visualizers → note-app`, after React + Babel.
- All visual values come from CSS custom properties — theme via `data-theme="light|dark"`
  on `<html>`; gate the loops with `.reduce-motion` (class) or `prefers-reduced-motion`.

## Coverage notes
- This kit recreates the **Note Capture window only** — the locked direction. The old
  seven-view Settings app is retired and intentionally not included. Settings now live
  behind the **gear** — an "Always on-device (private)" toggle (off = automatic:
  xAI online, on-device offline) and appearance. No provider picker, no capability matrix.
- The brand/provider marks are simple line glyphs (cloud = hosted, lock = on-device), not
  full-color vendor logos — matching the source.
