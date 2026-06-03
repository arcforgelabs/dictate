# Dictate — engineering work brief

The single "what to do next" doc for the `arcforgelabs/dictate` team. Each item links to
the detailed spec. Severity: 🔴 high · 🟠 medium · 🔵 low.

---

## 1. Bugs to fix — Recent History (web Settings window)

**Full diagnosis + copy-paste patches:** [`dictate-app/Recent History — Backend Fix Handoff.md`](dictate-app/Recent%20History%20—%20Backend%20Fix%20Handoff.md)
**Target UX reference (working):** `dictate-app/Dictate Settings.html` → *Recent history*

> ⚠️ Reassurance for support: **no dictations are actually lost.** The daemon writes every
> success to `recent-history.json`, and the tray's native *Recent History* dialog shows the
> full list. The bugs are all in the web Settings window's *display*.

| # | Bug | Severity | Impact | Recommended fix |
|---|---|---|---|---|
| 1 | Settings window never refreshes history after open | 🔴 | New dictations don't appear → reads as "lost chats"; list looks stuck (e.g. 3 items) | Publish `history-changed` from the daemon after `history_store.append()`, and wire the daemon to the UI server's `EventBroker` (handoff §1–4) |
| 2 | UI server started detached from the daemon | 🔴 | Root cause of #1 and #3 — `serve()` builds its own broker/store with no link to the live engine | `ensure_server_started(daemon)` → shared `EventBroker` + `daemon.history_store`; chain callbacks (handoff §2–4) |
| 3 | Relative timestamps are frozen strings | 🟠 | "just now" stays "just now" hours later | Compute the label client-side from `createdAt`, re-render on a timer (handoff §5–7) |
| 4 | Live "Listening" state in web UI is stale | 🟠 | Recording start/stop isn't reflected in the Settings hero | Same wiring as #2 — `recording` events flow once the broker is connected (handoff §2) |

All four are addressed by the one patch set in the handoff. **Verification checklist** is at the
bottom of that doc.

---

## 2. Design updates to port into `ui/src/`

The prototype `dictate-app/` is ahead of the shipped `ui/src/` on the **Status** screen.
Mirror these into `ui/src/views.jsx` (`StatusView`) + `ui/src/styles.css`. Reference is the
prototype's `StatusView` — lift the structure directly.

| Change | Why | Severity |
|---|---|---|
| Status screen → two-column dashboard (hero full-width; "Try it" demo left; model + quick settings right) | Old single 680px column overflowed the window and forced a scroll on the default screen | 🟠 |
| Show the push-to-talk keys in **one** place (the hero "Hold […]" hint) | They were repeated 3× on one screen | 🔵 |
| Richer "Transcription model" card (brand glyph + name + LOCAL/provider chip + the "nothing leaves your device" line) | Reinforces local-first; replaces a terse repeated stat | 🔵 |
| Default window 1060×728 → 1100×768 | Breathing room so the default view never scrolls | 🔵 |

These are visual/structural only — no engine or API changes.

---

## 3. Ship it — cross-platform packaging

**Full spec:** [`platforms/BUILD-DIRECTIONS.md`](platforms/BUILD-DIRECTIONS.md)
**Visual reference:** `platforms/Dictate Across Platforms.html`

- Runtime: **Tauri 2** (system WebView, ~6 MB; ships the existing HTML/CSS unchanged).
- Chrome: **hybrid** — custom title bar on Windows + Linux (`decorations:false`); native traffic
  lights on macOS. One platform-detected control component covers all five frames.
- The body never forks — same tokens, same components; only frame/corners/controls change.
- Capabilities map (global shortcut, type-at-cursor, tray, keychain, HUD window) is in §4 of the spec.

---

## 4. Open product questions (need a decision)

- **GNOME window controls:** ship close-only (Adwaita default) or follow the user's
  `button-layout` setting? *Recommendation: follow the setting, default to close-only.*
- **Live platform toggle:** fold the per-OS chrome into the real Settings app as a runtime
  preview toggle, so it's testable in one window?
- **Status design updates (§2):** port now, or hold until the cross-platform work lands?

---

## Priority order (suggested)

1. **§1 bugs** — single patch set, high user-trust impact, no design dependency.
2. **§3 packaging** — the biggest body of work; unblocks real distribution.
3. **§2 design port** — fold in alongside §3 so the UI ships current.
