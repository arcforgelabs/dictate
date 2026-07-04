# Frontend ↔ engine wiring status

What the shipped UI (`ui/src`) talks to, and what still needs backend work to be
fully real. The UI runs fully mocked with no backend (see `ui/README.md` — the
fast loop); this file tracks the gaps between that mock and the live engine.

Bridge: `ui/src/ipc.js` → `ui_server.py` HTTP (loopback, token-auth) for state,
plus Tauri commands in `ui-shell/src-tauri/src/lib.rs` for window/OS actions.

## Wired and working

| UI capability | Backend |
|---|---|
| Hydrate + live updates | `GET /api/state`, SSE `GET /api/events` |
| Model / shortcut / theme / startup / device | `PATCH /api/config` |
| Hotwords add/remove | `POST` / `DELETE /api/hotwords` |
| History list / clear | `GET` / `DELETE /api/history` |
| Note recording (start/stop/pause/resume/toggle) | `POST /api/notes/*` |
| Provider API keys | `POST` / `DELETE /api/api-keys` for advanced/BYO-key paths |
| Doctor | `POST /api/doctor` |
| Export note as Markdown | Tauri `save_text_file` (OS dialog) ← `ipc.saveTextFile`; browser-download fallback |
| Privacy pill (on-device ↔ online) | `PATCH /api/config` model swap for advanced/BYO-key paths; Dictate Pro should use entitlement-backed hosted access |
| Update check + run + restart | `GET /api/update-status`, `POST /api/update`, Tauri `restart_app` ← `ipc.restartApp` |

## Needs wiring (gaps against the new UI)

1. **Update background-prepare.** The Update pill has a
   `available → preparing → ready` progression, but live mode has no prepare
   step — clicking runs download+`pkexec`+install in one go via `POST /api/update`.
   To match the staged UX, add **`POST /api/update/prepare`** (download the `.deb`
   in the background, report progress), have `/api/update` install the prepared
   file, then the UI calls `restart_app`. Optionally push download progress over
   the SSE `/api/events` channel so the pill can show a real bar.
   - Frontend marker: `App.jsx` `useEffect` launch flow has a
     `TODO(backend): /api/update/prepare` note; mock simulates the staging.

2. **Skip persistence.** `App.jsx` stores `skippedVersion` in `localStorage`
   (per-webview, lost on cache clear). Move it to a server-side pref
   (`ui-prefs.json` via a config route) so "Skip this version" is authoritative
   and survives reinstalls. "Later" (dismiss) is correctly session-only.

3. **Update path E2E.** The download → `pkexec apt-get install` → `restart_app`
   flow is unit-tested with mocks only (`tests/test_update_status.py`). First real
   exercise needs a newer published release: verify the polkit prompt, the atomic
   file swap, and that the new shell + engine come up together.

4. **Local Meeting model lanes.** The capture home exposes a plain `Meeting`
   action and routes it to strict backend meeting endpoints. Live meeting mode
   now fails closed unless the selected backend supports speaker-attributed
   output. The remaining gap is implementing and benchmarking the local
   DiariZen, Sortformer, and pyannote speaker-attribution lanes from
   `docs/TRANSCRIPTION_PLAN.md`.

5. **WhisperX backend.** UI metadata exists for `whisperx`, but
   `docs/TRANSCRIPTION_PLAN.md` says not to make WhisperX the main meeting
   stack. Keep it advanced/experimental unless that plan changes.

6. **Dictate Pro / subscriptions.** Architecture exists in docs
   (`dictate-pro-subscription-architecture.md`, `msstore-in-app-subscriptions.md`,
   archived provider cost notes) but there is **no frontend surface yet**.
   **Production P0:** public **Upgrade to Pro** on
   https://arcforge.au/download/dictate is live but still links to `/login` until
   Stripe product + account entitlements are wired (see
   `docs/archive/goals-2026-07-05.md` for the historical goal note and
   `arc-forge-website/STATUS.md` for website state).
   To wire in this repo: entitlement/subscription state in `GET /api/state`, a Pro
   affordance in the UI, checkout/portal deep links from the app, MS Store IAP
   (Windows) where applicable, and service-side entitlement checks before hosted
   meeting upload. Do not expose Arc Forge's hosted provider key or a primary
   switchable-backend workflow in the Pro UI.
