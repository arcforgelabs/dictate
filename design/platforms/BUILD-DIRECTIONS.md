# Dictate — Windows & Linux build directions

A faithful cross-platform plan for the Quiet Console. The design system is the binding
visual reference; this doc covers the two things it doesn't: **what to build it with**, and
**how the window frame should adapt per OS** while the interior stays byte-for-byte the same.

Companion exploration: **`Dictate Across Platforms.html`** (this folder) — the same Dictate
window wearing each platform's chrome, in light + dark, plus these notes rendered in the
system's own type.

---

## TL;DR — the recommendations

1. **Runtime: Tauri 2.** System WebView, ~6 MB binary, low idle RAM. It matches the
   product ethos ("quiet, recessive utility") better than Electron, and ships the existing
   HTML/CSS unchanged.
2. **Chrome: hybrid.** Dictate paints **one custom title bar** on Windows + Linux
   (`decorations: false`); macOS keeps **native traffic lights**. A single
   platform-detected control component covers all five frames.
3. **One source of truth.** The body never forks. Same tokens, same `colors_and_type.css`,
   same components — only the frame, corner radius, and control cluster change.
4. **Bundle fonts locally** (already done) so WebKitGTK and WebView2 never substitute.
5. **Honor `prefers-color-scheme`** for light/dark and `prefers-reduced-motion` to kill the
   3.8 s breath — both already in the DS CSS.

---

## Why Tauri over the alternatives

| | Tauri 2 (recommended) | Electron | Native (Qt / GTK) |
|---|---|---|---|
| Binary size | **~6 MB** | ~85–150 MB | ~5–15 MB |
| Idle RAM | **low** (system WebView) | high (bundled Chromium) | lowest |
| Reuses our HTML/CSS | **yes, unchanged** | yes, unchanged | **no — rebuild twice** |
| Rendering engine | WebView2 (Win) · WebKitGTK (Linux) | Chromium everywhere | platform toolkit |
| Tray / global shortcut / keychain | first-class | first-class | manual |
| Risk | WebKitGTK CSS quirks (test) | none rendering-wise | high effort, design drift |

**Pick Tauri 2.** The one trade-off — Linux renders on WebKitGTK, not Chromium — is low risk
here because the DS is plain CSS (flexbox/grid, custom properties, `box-shadow`, no exotic
features). Test once on WebKitGTK and move on.

**Electron** is a fine fallback *only* if you later need Chromium-identical rendering or a
specific Electron-only dependency — accept the ~10× size/RAM cost. **Native Qt/GTK** would
fork the design into two more codebases and guarantee drift; not worth it for one window.

---

## Final design direction — window chrome per platform

The interior is fixed. Below is everything that changes, ready to implement.

| Platform | Corners | Window controls | Title | Material / notes |
|---|---|---|---|---|
| **macOS** | 11 px | **Native traffic lights** (OS-drawn) | centered | Transparent titlebar; inset the lights. No custom bar. |
| **Windows 11** | 8 px (DWM round) | Custom: min · max · close, `46×32` cells; close-hover `#c42b1c`, glyph white | left, after mark | Mica backdrop via window effects. |
| **Windows 10** | 0 px (square) | Custom: same cluster, flat & flush; close-hover `#e81123` | left, after mark | No rounding, minimal shadow. |
| **GNOME · Adwaita** | 13 px | Custom CSD: **round close only** (min/max hidden by default) | centered | Draw your own shadow (CSD). |
| **KDE · Breeze** | 6 px | Custom CSD: min · max · close, round-hover; close-hover `#c5402c` | centered | Compositor draws the drop shadow. |

Constants across all five: `--surface-2` headerbar, 1 px `--hairline` underline, the
arc-mark at 17 px inheriting `--fg` (ink on light, bone on dark — no second asset), and the
44 px bar height (52 px only on macOS to clear the traffic lights).

---

## Implementation handoff

### 1. Window config (`tauri.conf.json`)

```jsonc
{
  "app": {
    "windows": [{
      "label": "settings",
      "title": "Dictate",
      "width": 1060, "height": 728,
      "decorations": false,            // custom title bar on Win + Linux
      "titleBarStyle": "Overlay",      // macOS: keep native traffic lights
      "windowEffects": {               // Win11 Mica / macOS vibrancy
        "effects": ["mica"]
      }
    }]
  }
}
```

- `decorations: false` removes the OS frame so Dictate draws its headerbar. On macOS,
  `titleBarStyle: "Overlay"` *keeps* the native traffic lights over a transparent bar — that's
  the hybrid. Inset them with the window builder's `traffic_light_position`.
- Mark the headerbar element draggable with `data-tauri-drag-region`; exclude buttons.

### 2. Detect the frame to draw

```js
import { platform, version } from '@tauri-apps/plugin-os';

// 'macos' | 'windows' | 'linux'
const os = await platform();
// Win 11 vs 10: build number ≥ 22000 → 11
const isWin11 = os === 'windows' && Number(version().split('.').pop()) >= 22000;
// Linux DE comes from a tiny Rust command reading $XDG_CURRENT_DESKTOP → 'gnome' | 'kde'
```

Map to the chrome variants in `window.jsx` (`mac` · `win11` · `win10` · `gnome` ·
`kde`). One component, one switch — no forked UI.

### 3. Window controls

```js
import { getCurrentWindow } from '@tauri-apps/api/window';
const w = getCurrentWindow();
// min → w.minimize()  ·  max → w.toggleMaximize()  ·  close → w.close()
```

### 4. The capabilities behind the UI

| Need | Approach |
|---|---|
| Push-to-talk (hold key, system-wide) | `tauri-plugin-global-shortcut` |
| Type at cursor | `enigo` crate (Win `SendInput` / X11). **Wayland**: enigo can't inject — use `ydotool`/`wtype` or the XDG RemoteDesktop portal, with **clipboard-paste** as the universal fallback. |
| Tray icon + menu | built-in `TrayIconBuilder` (Tauri 2) |
| Listening HUD pill | a second window: small, `alwaysOnTop`, `transparent`, `decorations:false`, click-through |
| API keys | `keyring` crate → Credential Manager (Win) · Secret Service / libsecret (Linux) |
| Theme | `prefers-color-scheme` + `getCurrentWindow().theme()`; toggle `data-theme="dark"` |

### 5. Fonts & motion (already correct in the DS)

- Ship `HankenGrotesk-Variable.ttf` + `JetBrainsMono-Variable.ttf` as bundled assets and
  declare them with `@font-face` (see `chrome.css`). Never rely on system fonts —
  WebKitGTK will otherwise substitute and break the headings.
- Keep the single 3.8 s breath loop on live agents only; everything else settles. The
  `@media (prefers-reduced-motion: reduce)` block already disables it.

### 6. Platform gotchas to verify

- **WebKitGTK (Linux):** confirm `backdrop-filter` on the ⌘K scrim and the soft `box-shadow`
  stack render acceptably; both are fine in current WebKitGTK but worth a glance.
- **Wayland:** no global cursor-position or arbitrary keystroke injection without a portal —
  design the insert path around clipboard-paste fallback from day one.
- **Win10 vs Win11:** only corners + close-hover color + Mica differ; don't special-case more.
- **GNOME min/max:** hidden by default per Adwaita HIG. If you expose them, mirror the user's
  `org.gnome.desktop.wm.preferences button-layout` rather than forcing a cluster.

---

## What's in this folder

| File | Role |
|---|---|
| `Dictate Across Platforms.html` | The exploration canvas — five frames in light, three in dark, two spec cards |
| `chrome.css` | DS tokens (local fonts) + the faithful interior + every per-OS chrome rule |
| `window.jsx` | `DictateWindow` / `TitleBar` — one interior, the control cluster switches on `platform` |
| `fonts/`, `arc-mark.svg` | Local font hard-copies + brand mark, so it's offline-faithful |

`chrome.css` and `window.jsx` are the literal reference for steps 2–5 — the `.win.win11`,
`.adw`, `.breeze` rules are production-ready CSS; lift them straight in.

---

## Open questions

- **GNOME controls:** ship close-only (Adwaita default, shown here) or follow the user's
  button-layout setting? Recommendation: follow the setting; default to close-only.
- **Live platform toggle:** want the chrome folded into the actual Settings app as a runtime
  preview toggle (Win / Linux / Mac), so it's testable in one window? Say the word.
