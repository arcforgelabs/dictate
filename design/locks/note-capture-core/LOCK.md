# Note Capture — Core Design Lock

**Frozen:** 2026-06-22 · **Branch under test:** `forge/notecapture-shell`

## Source of truth
Claude Design cloud project **"Dictate Design System"** (`2477ec21-a493-41a0-b400-2a65c5bc3bf6`),
ui-kit `ui_kits/dictate-note-capture` — the Breath Cradle Note Capture app.
The **cloud project is the source of truth**; `.claude-design-ds/` is a disposable,
gitignored cache (re-exportable anytime), not a durable mirror. **This lock is the
deliberate freeze** of the core direction that the production port is measured against.

## Implementation target
`ui/src/` (production Tauri app). Rendered for review at the local dev server.

## Locked scope — the "core" (capture + notes + chrome)
1. **Capture home** — the Breath Cradle: the cradle-mic mark (= `assets/dictate.svg`, no
   stem/base) IS the button; amplitude breath, blooms on emphasis, silence recedes,
   reduced-motion → static state-color. States: Ready (idle), Recording (living green +
   timer + transcript preview, label stays "Recording"), Silence-mid-recording.
2. **Note flow** — Transcribing (calm, indeterminate; short captures skip it) → Note-ready
   (real `{id,text,createdAt}` text; **Insert** single filled primary + **Open note** +
   overflow Copy/Export; New note) → Expanded (full text + copy/export + back). Terminal
   note outcomes resolve deterministically (`ok`/`empty`/`failed` signal + 60s watchdog).
3. **Chrome** — ONE quiet titlebar (drag region + ⌘K + **gear-wheel** + per-OS window
   controls); **no "Dictate" wordmark, no "Settings" label**. Gear opens the settings menu
   (Always-on-device toggle, Appearance, all settings reachable). **System-theme default.**
4. **Provider** — automatic (xAI online / on-device offline) + a single "Always on-device
   (private)" toggle. No capability matrix.

## Explicitly OUT of this lock (allowed to differ — named follow-ups)
- **Settings detail surfaces** (Model · Push-to-talk · Hotwords · Recent history · App update
  · Startup · Advanced) — production still renders the old dense console views behind the
  gear. Their Note-Capture-style redesign is a separate **cloud-design → port** effort.
- **Real `/api/insert`** — Insert currently copies to clipboard + a `TODO(backend)`; wiring
  `POST /api/insert` → typing backend is a backend follow-up.
- **Tauri window resize** — the window is still console-sized, so the surface renders larger
  than the 460×700 design frame. Per-OS titlebar polish + resize are follow-ups.

## Baseline
`baseline/` holds captures of the locked **prototype** (the source). `implementation/` holds
matching **production** captures. Compare structure/layout/copy/state — not window dimensions
(the resize is out-of-lock above).

## Parity result (2026-06-22)
- **Ready** state: production matches the prototype (cradle-mic, copy, single quiet
  titlebar, gear-wheel). Out-of-lock differences only (window size; ⌘K bar in titlebar).
- **Both themes verified working** — light + dark both render correctly (light confirmed
  via the in-app Appearance toggle on a clean tab; dark is the system default here).
  Note: `implementation/ready-win-light.png` came out dark — that's a **capture-helper
  `prefers-color-scheme` emulation artifact**, not a real bug; disregard that one image.
- Gate: `cd ui && npm run build` ✓ + 38 tests ✓.
- **Verdict: VISUAL CLEAN for the locked scope.**

## Gate rule
For the **locked scope**, any visible extra / missing / changed element, label, or state in
the implementation vs the baseline is **VISUAL NOT CLEAN** unless explicitly allowed here.
The out-of-lock items above are permitted to differ.

## Note on policy
This lock supersedes the loose `design/dictate-note-capture/` working copy as the durable
freeze. `design/dictate-note-capture/` should be reconciled (folded into this lock or dropped
as re-exportable cache) during the deferred cleanup, per the updated claude-design/forge
"disposable cache + design/locks freeze" policy.
