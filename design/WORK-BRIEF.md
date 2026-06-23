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
1. **Settings — ELIMINATED (direction locked 2026-06-24).** Decision: the GUI owes the
   *non-technical daily user* nothing but doing-it-for-them; all advanced config lives in the
   **`dictate config` CLI** (agents/power users). So the gear-menu-of-pages is removed entirely.
   - **Keep (the one survivor):** a quiet **"On-device · private" privacy pill** on the capture
     home (trust/consent, not config — tap to flip). **No gear.** Notes stays (it's content).
   - **Delete from the GUI:** Status view, Model/provider picker, Push-to-talk page, Hotwords
     page, App update page, Startup page, Advanced page. Theme **follows the system**; updates
     **auto-install**; the hotkey ships sensible (Ctrl+D). Advanced = `dictate config`.
   - **Cloud proposals built** (`2477ec`, /preview): `comp-settings.html` (faithful current),
     `comp-settings-simplified.html` (4-row interim), `comp-settings-minimal.html` (eliminated),
     `comp-capture-home.html` (the no-gear home with the privacy pill), `comp-notes-list.html`.
   - **Implementation (port to `ui/src` after markup):** remove `GearMenu` + the `VIEWS` settings
     pages from `App.jsx`/`views.jsx`, drop the home-top gear, add the privacy pill; keep the
     Notes button. Verify `dictate config` covers every deleted control before removing it.
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
