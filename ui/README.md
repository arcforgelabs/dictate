# Dictate UI — the Quiet Console

The React frontend: a capture home where the centred microphone *is* the record
button, the notes / recent-history list, the ⌘K command palette, the
getting-started empty state, the listening HUD, and the toast stack — full
light/dark parity and per-OS window chrome (Linux GNOME/KDE focus). There is no
settings menu: the one on-screen control is the privacy pill, and advanced
config lives in the `dictate config` CLI.

It runs two ways:

- **Standalone (browser / dev / tests)** — a self-contained mock with the canned
  dictation demo, so the whole UI is explorable and testable with no backend.
  Mock recording is enabled only in Vite dev/test mode or with
  `VITE_DICTATE_ENABLE_MOCK=1`.
- **Live (inside the Tauri shell)** — the shell injects
  `window.__DICTATE__ = { baseUrl, token, platform }` and the UI reflects and
  drives the real Python engine over the `ui_server` HTTP API. A packaged shell
  with no live engine must show an engine-connection error; it must not return
  canned demo transcripts.

## Develop — the fast UI loop

For UI work, run the frontend in a plain browser. With no Tauri shell and no
engine present, `ipc.js` falls back to the built-in mock, so the *whole* app is
interactive with zero backend — no STT, no system calls, all state in memory.
This is the "simulated app in a browser" loop; it's the fast path for any visual
or interaction work.

```bash
npm install
npm run dev      # http://localhost:5173 — mock mode, gnome chrome by default
```

In the browser you can drive every everyday flow: press the mic (or hold **Right
Ctrl** while the page is focused) to fire the simulated dictation, toggle the
privacy pill, open Notes / search / copy / expand, ⌘K the palette, and see the
getting-started keyboard when history is empty. HMR is live — edit `src/` and it
updates instantly.

Reach for the Tauri shell (`cd ../ui-shell && npm run dev`) only for genuinely
native behaviour the browser can't simulate: OS-wide Right-Ctrl capture, the real
window chrome, or live data from the Python engine (run the engine too for that).

```bash
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
| run doctor | `POST /api/doctor` |
| live recording / status | `GET /api/events` (SSE) |
| window min/max/close | Tauri window API (`withGlobalTauri`) |

Every request carries `Authorization: Bearer <token>`; the server is loopback
only. With no bridge injected, `ipc.isLive()` is `false`. Local mock mutations
are allowed only when `ipc.isMockMode()` is true; `ipc.isShell()` disables mock
recording even if the engine bridge is temporarily unavailable.

## Layout

| Path | Role |
|---|---|
| `src/styles.css` | Design tokens, components, `@font-face`, per-OS chrome |
| `src/icons.jsx` | Lucide-style line glyphs and the Dictate brand mark |
| `src/primitives.jsx` | Kbd/Combo/Chip/Dot/Toggle/Seg/Row/Wave |
| `src/store.jsx` | Model catalog, demo phrases, context |
| `src/ipc.js` | Engine bridge (live + mock fallback) |
| `src/views.jsx` | The notes / recent-history view |
| `src/overlays.jsx` | Listening HUD, ⌘K palette, toasts |
| `src/platform/TitleBar.jsx` | Per-OS window-control cluster |
| `src/App.jsx` | Shell, state, hydration, dictation demo |
