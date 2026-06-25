# Claude Design — Dictate mapping

The design **process** lives in skills, not here: `forge` design mode
(**Prototype Source Parity**) and the `claude-design` skill (channels,
`/design-sync`, image sharing, landing). This file is only Dictate's
project-specific mapping.

| What | Where |
| --- | --- |
| Claude Design project | **"Dictate Design System" (`2477ec…`)** — the canonical Note Capture ui-kit + design system. (The old `2309408a…` "[LEGACY] dictate" project is superseded and flagged for deletion — do not use it.) |
| Design deliverables | the **`design/`** folder — organised by the design agent, mapped in [`../design/README.md`](../design/README.md). Keep it clear and discoverable; internal structure is the agent's call. |
| Production | `ui/src/` (Vite app) |
| Build / test | from `ui/`: `npm run dev` · `npm run build` · `npm test` |

**Channels (see the `claude-design` skill):** Claude Code → `/design-sync`;
Codex / Cursor / Antigravity → Claude Design → Send to Claude Code Web → GitHub
branch. Work lands on `master` (this repo's default branch); the local agent
lands it — no PR gate.

Note any deliberate prototype↔production divergences here.

## Next order of business — 1:1 reconstruction + markup loop

**Goal:** a fast, low-friction loop where the maintainer can look at the real UI,
mark up specific items for improvement, and have those changes flow back into
production (`ui/src/`) — using Claude Design as the markup surface rather than
prose bug reports.

Today the Claude Design project holds only `dictate-app/Dictate Settings.html`,
while production has grown a full surface set. The prototype must catch up so
every screen the user sees exists in Claude Design to mark up.

**The loop:**
1. **Reconstruct** the current production UI 1:1 into the canonical Claude Design
   project (**`2477ec…` "Dictate Design System"**) — one prototype per surface,
   matching `ui/src/` exactly (layout, copy, states). Cloud-first: design here,
   then sync to `ui/src` — never restyle `ui/src` directly. Use the
   `claude-design` skill (`write_files` + `render_preview`), not hand-copied CDP.
   Note: `design/locks/note-capture-core/` already froze the *shipped core*, but
   it predates this session's release work. The cloud project still needs the
   current capture home, Notes view, update controls, and Store-ready screenshots
   reconciled against production.
2. **Mark up** — the maintainer annotates items for improvement on the rendered
   prototypes.
3. **Sync back** — changes land in `ui/src/` via `/design-sync` onto `master`
   (no PR gate; the local agent lands it). Re-render to confirm parity.

**Surfaces to reconstruct (production inventory, as of `v2026.6.23`):**
- Capture (mic) home — cradle; ready / recording / transcribing states;
  copy-last row; config-gap hint; degraded strip; the home-top bar (settings
  gear + Notes button).
- Notes list view — search, rows with per-row copy, empty + no-results states.
- Note ready (just-captured) — Insert · Open note · overflow (Copy / Copy as
  Markdown) · New note.
- Expanded note (read) — back, copy, copy-as-Markdown.
- Settings entry points and panels — model/device status, push-to-talk,
  hotwords, app update, startup, advanced, and health/status surfaces.
- Settings views: Model, Push-to-talk, Hotwords, App update, Startup, Advanced,
  Status.
- Command palette (⌘K) and overlays (ListeningHUD, Toasts).
- Light + dark themes; native vs. custom (`DICTATE_CUSTOM_CHROME=1`) chrome.

**First target — release parity.** Reconstruct the current desktop app state
needed for the upcoming Windows Store release: capture home, Notes, update
controls, and settings/status surfaces. Use that pass to produce any replacement
Store screenshots after the next version is bundled and tested.
