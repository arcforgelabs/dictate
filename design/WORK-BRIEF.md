# Dictate — design work brief

The single "what to do next" doc for the `arcforgelabs/dictate` design → engineering
handover. Severity: 🔴 high · 🟠 medium · 🔵 low.

> **State as of this handover (June 2026):** the previous brief's three big items have all
> **shipped** to `arcforgelabs/dictate@master` (verified against the repo — see *Shipped*
> below). What remains is propagating the design changes **we** just made, plus keeping
> design ↔ code in parity. The two old handoff specs have been retired (their work is done).
>
> **Process rule:** prototype UI changes in Claude Design first where practical, sync/export the
> actual prototype files into `design/`, then port from those files into `ui/src/` with minimal
> translation. See [`../docs/claude-design-workflow.md`](../docs/claude-design-workflow.md).

---

## Shipped since the last brief — verified in the repo ✅

| Was | Now in `master` |
|---|---|
| §1 Recent-history live-update bugs | **Fixed.** `daemon.py` fires `history_callback` → `_notify_history_changed()` right after `history_store.append()`, and `recording_callback` for live state; `ui_server.py` wires the shared `EventBroker`/store; relative timestamps are computed client-side in `ui/src/views.jsx`. |
| §2 Status two-column dashboard port | **Shipped.** The real UI lives in `ui/src/` (`App.jsx`, `views.jsx`, `styles.css`) and mirrors the prototype's `StatusView`. |
| §3 Cross-platform packaging | **Shipped.** Tauri shell (`ui-shell/`), per-OS chrome (`ui/src/platform/TitleBar.jsx`), `packaging/`, and the canonical runbook `docs/desktop-packaging.md` + `LESSONS.md`. |
| Recording workflow refinement | **Shipped.** Status now separates Quick dictation from Record conversation, Record discloses `xAI · speaker labels`, and push-to-talk activation stays in the Push-to-talk view. Mirror files live in `design/dictate-app/`; production files live in `ui/src/`. |

The prior handoff docs (`Recent History — Backend Fix Handoff.md`, `platforms/BUILD-DIRECTIONS.md`)
were **deleted** — the work is done and the canonical engineering references now live in the
repo's `docs/` and `LESSONS.md`.

---

## 1. Brand mark refresh → propagate into the product 🟠

We replaced the forge-"A" mark with a new **"cradle mic"** mark (logo direction *02·c*,
tuned to arc-radius 32 · arm 0 · slot 16). It's explored in [`logos.html`](logos.html) and is
already live in the prototype title bar via `dictate-app/icons.jsx` → `ArcMark`.

**Drop-in SVG (currentColor, scales to any size):**
```html
<svg viewBox="18 8 84 84" fill="none">
  <rect x="47" y="16" width="26" height="48" rx="13" fill="currentColor"></rect>
  <path d="M28 48 A32 32 0 0 0 92 48" fill="none" stroke="currentColor" stroke-width="8" stroke-linecap="round"></path>
</svg>
```

**To ship it:**
- Replace `ArcMark` in **`ui/src/icons.jsx`** with the markup above.
- **Regenerate every packaged icon** from the new mark: Tauri app/window icon, tray icon,
  Windows `.ico`, macOS `.icns`, AppImage/`.desktop`, plus any MS Store listing art.
  - ⚠️ **Gotcha (LESSONS.md):** Tauri icons **must be RGBA PNG** — an `LA`/grayscale PNG makes
    `generate_context!` panic. Export the mark to RGBA, not grayscale.
- **Decision needed:** `assets/arc-mark.svg` and `platforms/arc-mark.svg` still hold the *old*
  forge-"A". Update them to the new mark, or keep the forge-"A" as a separate sub-brand?

---

## 2. Status model card — drop the description line 🔵

Per review, the Status-screen **"Transcription model"** mini-card no longer shows the model
description (the *"Runs on this machine…"* line) — it's now just the brand glyph, name, and
LOCAL/provider chip. Done in the prototype (`dictate-app/views.jsx` → `StatusView`).

**Port:** remove the same `<span className="t-meta">{m.desc}</span>` from `ui/src/views.jsx`
`StatusView`. Keep the description in the full **Model** view (it still belongs there).

---

## 3. Claude Design ↔ GitHub parity 🔵

Process lives in `forge` design mode (**Prototype Source Parity**) and the `claude-design`
skill. Dictate's project mapping is intentionally small:

- Claude Design project: `https://claude.ai/design/p/2309408a-2350-4da0-bb4c-c03c7cfee48a`
- Main prototype: `dictate-app/Dictate Settings.html`
- Repo mirror: `design/dictate-app/`
- Production app: `ui/src/`

Keep those surfaces in lockstep, or record the intentional divergence in
[`../docs/claude-design-workflow.md`](../docs/claude-design-workflow.md).

## 4. Design ↔ shipped parity notes (synced — FYI, no action) 🔵

The design files were brought in line with the shipped engine defaults. No work — just don't
regress these when editing the prototypes:

- Push-to-talk default: **Right Ctrl** (was `Ctrl + R`)
- Mic default: **Default device** (was `Built-in microphone`)
- Version string: **v2026.6.2** (was `v2026.2.25`)
- Installer copy: dropped the **"48 MB"** size label for **"local-first"**; install path is
  **`%LOCALAPPDATA%\Dictate\source`**

⚠️ **Gotcha (LESSONS.md):** a version bump touches **~13 files + tests** across the repo — and
in *this* design folder it appears in `Dictate Settings.html`, `views.jsx`, `Dictate Design
System.html`, `platforms/window.jsx`, and the installer/wireframe explorations. Bump them in
lockstep.

---

## Open product questions

- **GNOME window controls:** appears handled by `ui/src/platform/TitleBar.jsx` — confirm it
  follows the user's `button-layout` (default close-only) as recommended.
- **Live platform-preview toggle:** still worth folding the per-OS chrome into the real
  Settings app as a runtime toggle, so it's testable in one window?

---

## Priority order

1. **§1 Brand mark propagation** — visible everywhere and gates any release art (icons).
2. **§2 Model-card description removal** — one-line port.
