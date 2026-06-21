# Dictate — design project

Design work for **Dictate**, the "Quiet Console" desktop dictation app (hold a shortcut,
speak, release — text types into the focused app). Everything here follows the **Dictate
Design System** (warm paper greyscale, Hanken Grotesk + JetBrains Mono, one living green).

This README is the map. Open the file listed under each section to see the thing itself.

> **Claude Design workflow:** the process lives in the `forge` (design mode) and `claude-design`
> skills; Dictate's project mapping is in
> [`../docs/claude-design-workflow.md`](../docs/claude-design-workflow.md). This `design/` folder
> is the standard home for design deliverables — organised however the design agent prefers, as
> long as it stays clear and discoverable (this README is the map).

> **Engineers start here:** [`WORK-BRIEF.md`](WORK-BRIEF.md) — the consolidated "what to do
> next". **The product direction is now locked: [Note Capture](dictate-note-capture/) is the
> target.** The dense seven-view Settings console still ships today but is being superseded —
> do not add features to it. See the WORK-BRIEF for the port plan.

---

## Stable deliverables

These are the current, maintained artifacts. Start here.

| Path | What it is | Status |
|---|---|---|
| **`dictate-note-capture/index.html`** | **The locked product direction — the primary deliverable.** One mic that toggles; every capture is a Note you read / edit / insert. Self-contained: all states (happy + every fault), light/dark, reduced-motion, gear + provider sheet. | 🔒 Locked target |
| **`dictate-ds/Dictate Design System.html`** | The living design-system doc — tokens, type, color, components. The binding visual reference. | ✅ Current |
| **`dictate-app/Dictate Settings.html`** | The dense seven-view Settings console. **Ships today, but superseded by Note Capture — frozen, no new features.** Kept as the parity reference for the port. | 🧊 Shipping / frozen |
| **`platforms/Dictate Across Platforms.html`** | Cross-platform chrome study — the same window wearing macOS / Win11 / Win10 / GNOME / KDE frames, light + dark. | ✅ Current |
| **`logos.html`** | Brand-mark exploration — directions for a new, more distinctive logo and the chosen **"cradle mic"** mark (now in `dictate-app/icons.jsx`). | ✅ Current |

> The two engineering handoffs that used to live here (`platforms/BUILD-DIRECTIONS.md` and
> `dictate-app/Recent History — Backend Fix Handoff.md`) have been **retired** — their work
> shipped. The canonical engineering references now live in the repo's `docs/desktop-packaging.md`,
> `docs/recent-dictation-history-spec.md`, and `LESSONS.md`.

### The app's structure (`dictate-app/`)

A single HTML entry point that loads modular Babel/JSX. Edit the module, not the HTML, for
most changes.

| File | Role |
|---|---|
| `Dictate Settings.html` | Entry point — app shell, state, nav, fit-to-viewport scaler |
| `views.jsx` | The maintained setting surfaces (Status, Model, Push-to-talk, Hotwords, Recent history, Advanced) |
| `overlays.jsx` | Listening HUD, ⌘K command palette, toast stack |
| `primitives.jsx` | Shared atoms (Combo, Chip, Toggle, Seg, Row, Wave…) |
| `store.jsx` | Model catalog, demo phrases, live time-label helpers |
| `icons.jsx` | Line-icon set + brand glyphs + the brand mark (`ArcMark`, now the new "cradle mic") |
| `styles.css` | All styling, light + dark tokens |

---

## Explorations

Separate experiments — not part of the maintained app. Kept for reference.

| Path | What it is | Status |
|---|---|---|
| `explorations/installer/Dictate Installer.html` | Windows installer flow concept | 🧪 Exploration |
| `explorations/installer/Dictate Installer - A vs B canvas.html` | Two installer directions side by side | 🧪 Exploration |
| `explorations/wireframes/Dictate Wireframes.html` | Early low-fi wireframes of the settings surfaces | 🗄️ Legacy — superseded by `dictate-app/` |

Each exploration folder is self-contained (its HTML + JSX modules live together).

---

## Shared resources

| Path | What it is |
|---|---|
| `fonts/` | Local font hard-copies (Hanken Grotesk + JetBrains Mono variable TTFs) |
| `assets/arc-mark.svg` | The **legacy** forge-"A" mark (currentColor). The shipping mark is now the "cradle mic" in `dictate-app/icons.jsx` — see `WORK-BRIEF.md` §1 for propagation. |
| `logo-marks.jsx` | The logo direction marks rendered by `logos.html` |
| `uploads/` | User-provided files |

> The design system itself (tokens, fonts, full component recreations) lives in a separate
> linked project; this repo consumes it.

---

## Conventions

- **Modular JSX over CDN.** Pages load `react@18.3.1` + `@babel/standalone` from unpkg, then
  local `*.jsx` modules. Components are shared via `window` assignment at the bottom of each
  module (each Babel script is its own scope).
- **Fonts are local.** `installer.css` and `platforms/chrome.css` declare `@font-face` against
  the bundled TTFs so rendering never depends on system fonts. The app and wireframes use the
  Google Fonts CDN.
- **Light + dark are both first-class**, driven by `data-theme` and design-system tokens.
