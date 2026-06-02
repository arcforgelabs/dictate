# Dictate UI — Cross-Platform Framework Plan

> **Status:** In progress · 2026-06-02 — **Linux vertical slice built.**
> **Scope:** Ship the Quiet Console design system on Linux, Windows 11, and macOS while keeping the Python dictation engine.

## Built so far (Linux + Tauri shell + backend UI)

The recommended stack below is now scaffolded end-to-end for Linux:

- **`src/dictate/ui_server.py`** — loopback, token-authenticated JSON control
  server (the IPC contract sketched below), with `tests/test_ui_server.py`.
- **`ui/`** — the React/Vite port of the Quiet Console (all seven views, ⌘K,
  HUD, toasts, light/dark, GNOME/KDE chrome), Vitest-tested, `vite build` clean.
- **`ui-shell/`** — the Tauri 2 shell (DE detection, handshake discovery/spawn,
  bridge injection). Authored + `#[cfg(test)]`-tested; **needs Rust + webkit2gtk
  to compile** (see `ui-shell/README.md`).
- **`src/dictate/ui_launcher.py`** + tray **“Open Settings…”** — launches the
  shell, falls back to the native GTK dialogs when the binary is absent.
- **`scripts/ui-server-smoke.sh`** — end-to-end handshake + auth smoke.

Remaining: compile/package the shell on a provisioned Linux box, live SSE
recording events from the daemon, then the Windows + macOS streams.

---

## Executive summary

**Primary recommendation:** **Python daemon + Tauri 2 shell (React frontend)**

Keep the existing Python process as the single source of truth for STT, audio, hotkeys, config, history, and typing. Add a **Tauri 2** app that hosts the React/CSS design system for the Settings window, command palette, listening HUD, and toasts. Tray menus stay **native per platform** in phase 1 (GTK on Linux, Win32 shell tray on Windows, `rumps`/`pyobjc` on macOS) and launch the Tauri UI over a local IPC bridge.

**Fallback:** **Electron + Python child** if Tauri WebView variance on Linux or Python bundling friction blocks release velocity within one milestone.

**Explicitly not recommended:** Rewriting the UI in Qt/GTK/tkinter to match the design system, or adopting Wails (Go shell adds a third runtime with no payoff given a Python core).

---

## Codex consultation note

Codex CLI (`codex exec`) was invoked twice for an independent framework scorecard; both runs hung without output (likely `TERM=dumb` / sandbox interaction in this environment). Codex MCP is not wired into the Cursor session (`codex mcp-server` exposes Codex *as* a server, not a client). This plan synthesizes the design assets, current codebase, and cross-platform constraints directly. Re-run locally:

```bash
codex exec --sandbox read-only -o design/codex-framework-advice.md \
  "Review design/PLAN.md constraints and validate Tauri+Python vs Electron+Python for Dictate."
```

---

## Current state

| Layer | Linux | Windows | macOS |
|---|---|---|---|
| Engine | Python (`daemon`, `engine`, STT backends) | Same | Stub (`outputs.py` platform tag only) |
| Tray | GTK3 + AyatanaAppIndicator | Win32 `Shell_NotifyIcon` ctypes | Not implemented |
| Settings UI | GTK3 dialogs (`*_dialog.py`) | tkinter `windows_control.py` | Not implemented |
| Design target | `design/ui_kits/dictate-app/` — React + CSS prototype | Same | Same |

The design system is **web-native** (CSS custom properties, backdrop blur, breathing pulse animation, inline SVG icons). The shipping UI is **platform-native widgets** that cannot reach design fidelity without a full rewrite.

---

## Decision: why Tauri + Python (not all-in-one Electron)

| Factor | Tauri 2 + Python | Electron + Python |
|---|---|---|
| Design fidelity | System WebView renders React/CSS 1:1 | Same |
| Shell size | ~5–15 MB (no bundled Chromium) | ~150 MB+ Chromium |
| Python fit | Sidecar or external daemon (both work) | Child process (well-trodden) |
| Tray maturity | Good; Linux still less battle-tested than GTK/Win32 | Excellent cross-platform |
| macOS | WKWebView, notarizable Tauri bundle | Mature but heavy |
| Team assets | Direct port of `ui_kits/dictate-app` | Same |
| Risk | WebView differences across Linux distros | Binary bloat; duplicate Node runtime |

Dictate already ships large STT model artifacts; avoiding a bundled Chromium is worthwhile. Tray and global hotkeys are the hardest platform surfaces — **keep proven native tray code** rather than betting the farm on Tauri tray on day one.

---

## Scorecard (1 = poor, 5 = excellent)

| Candidate | Linux | Windows | macOS | Design fidelity | Dev velocity | Packaging | Tray | Binary size | Risk |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Tauri 2 + Python daemon** ★ | 4 | 5 | 5 | 5 | 4 | 3 | 3* | 5 | 3 |
| Electron + Python child | 5 | 5 | 5 | 5 | 5 | 4 | 4 | 2 | 2 |
| PyWebView + Python | 3 | 4 | 4 | 4 | 4 | 4 | 2 | 5 | 3 |
| PySide6 / Qt QML | 4 | 4 | 4 | 2 | 1 | 3 | 4 | 3 | 4 |
| Native-only (GTK/tkinter) | 3 | 2 | 1 | 1 | 2 | 5 | 5 | 5 | 2 |
| Wails + Python | 3 | 4 | 4 | 5 | 2 | 3 | 3 | 4 | 5 |

\*Tray score assumes **native tray in phase 1**; rises to 4 if/when tray moves into Tauri.

**Primary:** Tauri 2 + Python daemon  
**Fallback:** Electron + Python child  
**Fastest spike (optional):** PyWebView proof for Settings-only before committing Rust toolchain

---

## Target architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         User session (per OS)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────────┐         localhost IPC          ┌────────────┐ │
│  │  Native system tray   │  open settings / HUD / state  │ Tauri 2    │ │
│  │  (GTK / Win32 / macOS)│◄────────────────────────────►│ React UI   │ │
│  └──────────┬───────────┘   JSON over HTTP or Unix sock  │ (Quiet     │ │
│             │ spawn / owns                                │  Console)  │ │
│             ▼                                             └─────┬──────┘ │
│  ┌──────────────────────┐                                       │       │
│  │  Python daemon        │◄──────────────────────────────────────┘       │
│  │  • push-to-talk       │   invoke: config, model, keys, history,       │
│  │  • audio capture      │          doctor, shortcut capture            │
│  │  • STT backends       │   events: recording, status, toasts,         │
│  │  • text output        │          transcription previews              │
│  │  • history / config   │                                              │
│  └──────────┬───────────┘                                              │
│             │ types into focused app                                     │
│             ▼                                                            │
│       [ Any foreground app ]                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Process model

1. **`dictate` (Python)** — always running after login; owns tray, hotkeys, mic, STT, typing.
2. **`dictate-ui` (Tauri)** — launched on demand or kept alive as a lightweight helper; frameless Settings window + optional always-on-top Listening HUD.
3. **IPC** — prefer **Unix domain socket / named pipe** with a small JSON schema; HTTP on `127.0.0.1:<port>` is acceptable for v1. No remote binding.

### Repo layout (proposed)

```
dictate/
├── src/dictate/              # Python engine (unchanged ownership)
├── ui/                       # NEW — production React app
│   ├── src/                  # Ported from design/ui_kits/dictate-app/
│   ├── public/fonts/         # Symlink or copy from design/fonts/
│   └── package.json          # Vite + React 18
├── ui-shell/                 # NEW — Tauri 2 project
│   ├── src-tauri/
│   └── tauri.conf.json
└── design/                   # Design system source of truth (this folder)
```

---

## What to reuse from `design/ui_kits/dictate-app`

| Asset | Reuse |
|---|---|
| `colors_and_type.css` | Copy into `ui/src/styles/tokens.css`; keep in sync with `design/` |
| `styles.css` | Split into component CSS modules or keep global; drop CDN-only assumptions |
| `icons.jsx` | Port to `.tsx`; keep inline SVG paths |
| `primitives.jsx` | Port 1:1 (`Kbd`, `Combo`, `Chip`, `Toggle`, `Seg`, `Row`, `Wave`, `Dot`) |
| `views.jsx` | Port seven views; replace mock store with IPC hooks |
| `overlays.jsx` | Command palette, HUD, toasts — wire to daemon events |
| `store.jsx` | Replace with `useDictateStore()` backed by IPC + optimistic UI |
| `fonts/` | Bundle in Tauri resources |
| `assets/arc-mark.svg` | Window chrome + tray where vector is supported |

**Build pipeline change:** replace Babel-in-browser with **Vite + React + TypeScript**. Keep JSX structure; add types incrementally.

**Do not ship:** CDN React/Babel from `index.html`, mock keychain, canned dictation demo strings.

---

## Migration phases

### Phase 0 — Spike (1 week)

- [ ] Vite port of one view (Status) using design tokens
- [ ] Tauri window loads built assets; Python serves mock IPC endpoints
- [ ] Validate: `backdrop-filter`, `@font-face`, breathing animation, `prefers-reduced-motion`
- [ ] Test on Ubuntu (WebKitGTK), Windows 11 (WebView2), macOS (WKWebView) if hardware available

**Exit criteria:** Visual parity with `design/ui_kits/dictate-app/index.html` on all three platforms.

### Phase 1 — Settings window (MVP)

- [ ] Define IPC schema (`GET /state`, `PATCH /config`, `POST /api-keys`, `GET /history`, …)
- [ ] Implement Python `ui_server` module in daemon (or companion thread)
- [ ] Port all seven Settings views + ⌘K palette
- [ ] Linux: tray menu item opens Tauri instead of GTK dialogs
- [ ] Windows: tray opens Tauri instead of tkinter `ControlPanel`
- [ ] Deprecate but keep GTK/tkinter behind feature flag until parity proven

### Phase 2 — Listening HUD + live state

- [ ] Tauri transparent always-on-top HUD window
- [ ] Python pushes `recording`, `level`, `timer` events over IPC
- [ ] Toast stack for copy/history/undo actions
- [ ] Single-instance guard (one Settings window, one HUD)

### Phase 3 — macOS platform stream

See [macOS plan](#macos-plan) below.

### Phase 4 — Packaging & polish

- [ ] Bundle `dictate-ui` binary in existing install scripts
- [ ] CI matrix: build Tauri artifacts per OS
- [ ] Code signing (Windows Authenticode, Apple notarization)
- [ ] Remove deprecated GTK/tkinter settings code

### Phase 5 — Optional consolidation

- [ ] Evaluate moving tray into Tauri (`tray-icon` plugin) once macOS is stable
- [ ] Or design native tray menus that match design tokens (compact, not full Quiet Console)

---

## Platform plans

### Linux

| Concern | Approach |
|---|---|
| Tray | Keep **AyatanaAppIndicator + GTK** (`tray.py`) until Tauri tray validated on major distros |
| Settings | Launch `dictate-ui` via `subprocess` or D-Bus activation |
| IPC socket | `$XDG_RUNTIME_DIR/dictate/ipc.sock` |
| WebView | WebKitGTK via Tauri; test Fedora, Ubuntu LTS, Arch |
| Hotkeys | No change — X11/Wayland backends in Python |
| Typing | No change — `xdotool` / `wtype` / `ydotool` |
| Packaging | Extend `install.sh` / `install-ubuntu.sh` to install UI binary + desktop entry update |
| Autostart | Existing XDG autostart; ensure UI helper starts with daemon if HUD enabled |

### Windows 11

| Concern | Approach |
|---|---|
| Tray | Keep **Win32 `Shell_NotifyIcon`** (`windows_tray.py`) — already native and lightweight |
| Settings | Replace `dictate-controls` tkinter entry with Tauri launch from tray |
| IPC | Named pipe `\\.\pipe\dictate` or loopback HTTP |
| WebView | WebView2 (Evergreen runtime; document dependency in installer) |
| Hotkeys | No change — `pynput` |
| Packaging | Extend `install-windows-wizard.ps1`; ship `dictate-ui.exe` beside Python venv |
| Installer | Future signed MSI/NSIS includes WebView2 bootstrapper if needed |

### macOS

| Concern | Approach |
|---|---|
| Tray | **`rumps`** or **`pyobjc` + NSStatusItem** — mirror Linux/Windows pattern (Python owns tray) |
| Settings | Tauri app bundle `Dictate.app` or embedded helper in `.app/Contents/MacOS/` |
| IPC | Unix socket in `~/Library/Application Support/Dictate/ipc.sock` |
| WebView | WKWebView via Tauri |
| Hotkeys | **`pynput`** or **`Quartz` CGEvent tap** — requires **Accessibility** permission prompt on first run |
| Typing | **`pyobjc` + `CGEventKeyboardSetUnicodeString`** or `cliclick`-style helper; implement `TextOutput` for darwin (stub exists in `outputs.py`) |
| API keys | **Keychain** via `keyring` or `pyobjc` Security framework — extend `api_keys.py` |
| Microphone | `Info.plist` **`NSMicrophoneUsageDescription`** |
| Accessibility | **`NSAccessibilityUsageDescription`** for global hotkey + typing |
| Autostart | `SMAppService` login item (macOS 13+) or `LaunchAgents` plist |
| Distribution | **Developer ID Application** cert, **Hardened Runtime**, **notarization**, staple ticket |
| Universal binary | `aarch64-apple-darwin` + `x86_64-apple-darwin` for Tauri; Python env matches arch |

**macOS milestone order:** typing output → hotkeys + permissions → tray → keychain → Tauri settings → notarized `.dmg`.

---

## IPC contract (sketch)

```typescript
// Events (server → UI, SSE or WebSocket)
type DictateEvent =
  | { type: "status"; message: string | null }
  | { type: "recording"; active: boolean; elapsedMs: number }
  | { type: "toast"; id: string; message: string; undo?: string }
  | { type: "history-changed" };

// Commands (UI → server, REST POST/PATCH)
interface DictateState {
  version: string;
  active: boolean;
  model: { backend: string; model: string; runtime?: string };
  pushToTalk: { combo: string; activation: "hold" | "toggle" };
  hotwords: string[];
  history: { page: number; entries: HistoryEntry[] };
  startup: { enabled: boolean; trayOnly: boolean };
  theme: "light" | "dark" | "system";
  overlay: { hud: boolean; sound: boolean; ambient: boolean };
  providers: Record<string, { configured: boolean; status: string }>;
}
```

Python remains authoritative; UI is a reflective control surface, not a second daemon.

---

## Toolchain additions

| Tool | Purpose |
|---|---|
| Node 20+ | UI build only (CI + dev); not required at runtime except WebView2 bootstrap on Windows |
| Rust stable | Tauri 2 build |
| `pnpm` or `npm` | `ui/` and `ui-shell/` workspaces |
| GitHub Actions | `tauri-apps/tauri-action` matrix `ubuntu-latest`, `windows-latest`, `macos-latest` |

Pin Tauri 2.x and document minimum OS versions: Ubuntu 22.04+, Windows 11 22H2+, macOS 13+.

---

## Anti-patterns (do not do)

1. **Rewrite Quiet Console in GTK/tkinter** — duplicates effort, will never match CSS design system.
2. **Embed React in PyWebView without a build step** — reproduces the prototype's CDN/Babel hack; no production path.
3. **Move STT/hotkeys into Tauri/Rust** — splits brain; Python backends are the product moat.
4. **Two settings UIs long-term** — migrate Linux and Windows together; feature-flag, don't maintain both.
5. **Remote IPC** — never bind UI server beyond localhost.
6. **Electron by default** — acceptable fallback, not first choice; STT artifacts already dominate disk.
7. **Invent tray/onboarding UI in code** — design README omits these; spec in `design/` before implementing.
8. **Blue-black dark theme** — use design tokens only (`data-theme="dark"` warm near-black).

---

## Open questions

1. **Single `.app` vs helper binary** on macOS — Tauri bundling vs Python-as-main with embedded UI?
2. **HUD process model** — separate Tauri window vs second lightweight webview instance?
3. **Offline doctor checks** — run in Python, stream progress events to Advanced view (match prototype animation)?
4. **Linux WebView fallback** — if WebKitGTK too old, open system browser to localhost (degraded mode) or require distro package?

---

## Success metrics

- Settings UI pixel-consistent with `design/ui_kits/dictate-app` at 1060×728 (scaled responsively)
- One IPC schema shared across Linux, Windows, macOS
- No regression to push-to-talk latency or tray reliability
- macOS notarized build installable without Gatekeeper warnings
- GTK/tkinter settings code removed within one release cycle after Tauri GA

---

## Next actions

1. Approve primary stack (Tauri + Python) or escalate to Electron fallback criteria.
2. Create `ui/` Vite scaffold; port Status view from design kit.
3. Add `ui-shell/` Tauri 2 project wired to Vite `dist/`.
4. Spec Python `ui_server` module and wire tray "Settings" to launch UI.
5. Open `platform:macos` stream with typing + keychain tasks parallel to UI work.
