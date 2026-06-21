# Dictate — design work brief

The single "what to do next" doc for the `arcforgelabs/dictate` design → engineering
handover. Severity: 🔴 high · 🟠 medium · 🔵 low.

> **State as of this handover (June 2026):** the product direction is now **LOCKED — Note
> Capture** (see §0). The dense seven-view console shipped to `arcforgelabs/dictate@master` and
> still runs today, but it is **frozen and being superseded** — do not add features to it. The
> remaining work is the port to Note Capture, plus the small console-parity ports that are still
> worth doing during the transition.
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

## 0. Product direction — LOCKED: Note Capture 🔴

**Decision (2026-06-21, ratified via `/forge` design review + independent verification):** Dictate's
product is **Note Capture**, not the dense seven-view Settings console. One centered mic that
toggles (press to start / press to stop); every capture — a quick dictation or a long meeting — is
a **Note** you read, edit, and **Insert** into the focused app. Settings collapse behind a **gear**
and **⌘K**. This resolves the old console's structural problems at the root (competing primaries,
duplicated capture, dual navigation).

**Source of truth:** [`dictate-note-capture/`](dictate-note-capture/) — the self-contained, locked
prototype (promoted into the repo from the design-system ui-kit; runnable via its `index.html`).
The old A/B/C concepts in `explorations/simplified-ui/` are **retired** — do not port from them.

**Freeze rule:** the dense console (`dictate-app/`, `ui/src/`) is frozen. Ship no new console
views or states (the recent `UpdateView` work was the last). Console-parity items below (§1–§2)
are fine to finish during the transition because they also benefit the eventual port.

**Port plan (the real, scoped effort — not yet started):**
1. Stand up the Note Capture shell in `ui/src/` (the one-capture-object app + gear + provider sheet),
   replacing the rail + seven views. Port from the **files** in `dictate-note-capture/`, not screenshots.
2. Wire the prototype's toast-only actions to real IPC: **Insert** (type into focused app),
   Accept (save to history), Copy, Edit, Export, plus provider/visualizer/appearance in the gear.
3. Carry every state across — happy path *and* every fault: first-run/empty, mic-denied, no-device,
   capture-error (retry / on-device), on-device fallback, dropped-chunk, interrupted, processing-at-rest.
4. Keep settings reachable: gear menu + ⌘K. Recent history surfaces as the note list.

**Before it's a lockable production target, resolve (from the design review):**
- 🔵 **Light-theme rendered evidence** for every state (light is token-equal in code, but only dark
  has been rendered). Capture light + dark for the key states.
- 🔵 **Baseline packet** — create `design/locks/note-capture/baseline/` (key states × both themes) so
  the port has a strict visual target. (Prototype defaults to dark — `note-app.jsx` `DEFAULTS`.)
- 🔵 **Legibility floor** — several 10–10.5px muted/subtle captions sit below the comfortable read
  size; lift the caption tier to ~11–12px or strengthen its color before lock.
- 🔵 **Accessibility** — the Ring/Wave live-preview text isn't in an `aria-live` region (only the
  Transcript-Stream visualizer is); wrap the preview line so screen readers announce partial text.
- 🟠 **Brand mark** — still labelled *candidate* in the prototype; finalize the cradle-mic mark
  (see §1) before the port locks, so it's propagated once.

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

1. **§0 Note Capture port** — the locked direction; the real effort. Resolve its pre-lock list first.
2. **§1 Brand mark propagation** — visible everywhere, gates release art *and* the Note Capture mark.
3. **§2 Model-card description removal** — console-only; do only if still touching the frozen console.
