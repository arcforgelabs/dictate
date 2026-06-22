# Dictate — design work brief

**State (2026-06-22):** the **Note Capture core is merged to production** (`../ui/src/`) and
frozen in [`locks/note-capture-core/`](locks/note-capture-core/). What remains are the
follow-ups below.

## Done
- Note Capture direction locked; the prototype built in the cloud (`2477ec` "Dictate Design System").
- Brand mark finalized: the **cradle-mic** (`../assets/dictate.svg`) — shipped (Tauri/tray, npm,
  MSIX) and used in the app.
- Production port (forge): Stage 1 shell + capture · Stage 2 note surfaces (+ deadlock fix) ·
  Stage 3 receded chrome. Merged to `master` (gates green; merge-gate review found no P0–P2).
- Cleanup: legacy `2309408a` cloud project flagged **`[LEGACY]`**; superseded repo prototypes
  retired (`dictate-app/`, `dictate-ds/`, `explorations/`, loose `dictate-note-capture/`).

## Follow-ups (rough priority)
1. **Settings detail surfaces** 🟠 — production still renders the old dense views behind the
   gear (Model · Push-to-talk · Hotwords · Recent history · App update · Startup · Advanced).
   Design them in the Note Capture style **in the cloud (`2477ec`) first → sync → port** — do
   NOT restyle directly in `ui/src` (cloud-first).
2. **Real `/api/insert`** 🟠 — Insert currently copies to clipboard + a `TODO(backend)`. Add
   `POST /api/insert` (ui_server) → `UiBackend.insert_text` → the typing backend so Insert
   types the note into the focused app.
3. **Tauri window resize / per-OS titlebar polish** 🔵 — the window is still console-sized;
   Note Capture is designed at ~460×700.
4. **Finish cleanup** 🔵 — delete the `[LEGACY] dictate` cloud project (`2309408a`) when ready
   (owner action — I won't delete cloud projects); decide on `platforms/` + `logos.*` retention.

## Lock / gate
The convergence target is [`locks/note-capture-core/LOCK.md`](locks/note-capture-core/LOCK.md);
new port work is measured against it. Cloud is the source of truth; `.claude-design*` is a
disposable gitignored cache; freezes go in `locks/`.
