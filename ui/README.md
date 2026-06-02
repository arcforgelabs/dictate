# Dictate UI — the Quiet Console

A faithful React port of the design-system Settings window (`design/ui_kits/`):
seven views — Status, Model, Push-to-talk, Hotwords, Recent history, Startup,
Advanced — plus the ⌘K command palette, the listening HUD pill, the toast stack,
full light/dark parity, and per-OS window chrome (Linux GNOME/KDE focus).

It runs two ways:

- **Standalone (browser / dev / tests)** — a self-contained mock with the canned
  dictation demo, so the whole UI is explorable and testable with no backend.
- **Live (inside the Tauri shell)** — the shell injects
  `window.__DICTATE__ = { baseUrl, token, platform }` and the UI reflects and
  drives the real Python engine over the `ui_server` HTTP API.

## Develop

```bash
npm install
npm run dev      # http://localhost:5173 — mock mode, gnome chrome by default
npm run test     # vitest (jsdom)
npm run build    # -> dist/ (embedded by ../ui-shell)
```

Fonts (Hanken Grotesk + JetBrains Mono variable TTFs) are bundled in
`public/fonts/` so WebKitGTK never substitutes.

## How it talks to the engine (`src/ipc.js`)

| UI action | Request to `ui_server` |
|---|---|
| hydrate on mount | `GET /api/state` |
| set model / shortcut / theme / startup / device | `PATCH /api/config` |
| add / remove hotword | `POST` / `DELETE /api/hotwords` |
| clear history | `DELETE /api/history` |
| save / clear provider key | `POST` / `DELETE /api/api-keys` |
| run doctor | `POST /api/doctor` |
| live recording / status | `GET /api/events` (SSE) |
| window min/max/close | Tauri window API (`withGlobalTauri`) |

Every request carries `Authorization: Bearer <token>`; the server is loopback
only. With no bridge injected, `ipc.isLive()` is `false` and all mutations stay
local (mock mode) — which is exactly what the test suite exercises.

## Layout

| Path | Role |
|---|---|
| `src/styles.css` | Design tokens, components, `@font-face`, per-OS chrome |
| `src/icons.jsx` | Lucide-style line glyphs + authentic provider brand marks |
| `src/primitives.jsx` | Kbd/Combo/Chip/Dot/Toggle/Seg/Row/Wave |
| `src/store.jsx` | Model catalog, demo phrases, context |
| `src/ipc.js` | Engine bridge (live + mock fallback) |
| `src/views.jsx` | The seven settings views |
| `src/overlays.jsx` | Listening HUD, ⌘K palette, toasts |
| `src/platform/TitleBar.jsx` | Per-OS window-control cluster |
| `src/App.jsx` | Shell, state, hydration, dictation demo |
