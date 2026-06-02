# UI Kit — Dictate Settings ("the Quiet Console")

A high-fidelity, interactive recreation of Dictate's desktop **Settings window**.
This is the product's core surface: a tray-resident utility you open to configure
dictation. It's a faithful cosmetic + interaction recreation lifted from the source
prototype — not production code.

Open **`index.html`** to use it. It fits-to-viewport (designed at 1060×728) and runs
entirely client-side with React + Babel from CDN.

## What works (interactive)
- **Push-to-talk demo** — hold **Right Ctrl** (or press-and-hold the "Hold to try
  dictation" button) to "record"; release to watch text type into the mock Notes target.
  A floating **Listening HUD** pill with live waveform + timer shows while recording.
- **⌘K command palette** — jump to any view, switch model, run an action, toggle theme.
- **Model picker** — choose local vs hosted; hosted models prompt for an API key
  (anything 6+ chars "saves" to a mock keychain and connects the provider).
- **Push-to-talk rebind** — click Rebind and press a real key combo to capture it.
- **Hotwords** — add/remove word chips.
- **Recent history** — copy / clear with an undo toast.
- **Light / dark** theme toggle (rail foot, Advanced view, or palette) and an
  **ambient motion** switch that stills the breathing pulse.
- **Doctor** — Advanced › Run doctor animates a sequence of checks.

## Files
| File | Role |
|---|---|
| `index.html` | App shell: window chrome, sidebar rail, view router, global key handling, fit-to-viewport scaler, the `store` (all state + the canned dictation demo) |
| `store.jsx` | Shared React context, the `MODELS` data, demo phrases, `nowLabel()` |
| `views.jsx` | The seven setting surfaces (Status, Model, Push-to-talk, Hotwords, History, Startup, Advanced) |
| `overlays.jsx` | Listening HUD, ⌘K command palette, toast stack |
| `primitives.jsx` | Atoms: `Kbd`, `Combo`, `Chip`, `Dot`, `Toggle`, `Seg`, `Row`, `Wave` |
| `icons.jsx` | `Icon` (Lucide-style line glyphs), `Brand` (provider marks), `ArcMark` (logo) |
| `styles.css` | The product's full stylesheet — same tokens as `../../colors_and_type.css` plus every component, the window, HUD, palette, toasts |

## How to reuse
- Components are exported to `window` (see the `Object.assign(window, {...})` at the
  end of each JSX file), so any `<script type="text/babel">` loaded after them can use
  `<Icon>`, `<Toggle>`, `<Combo>`, `<Row>`, etc. directly.
- Load order matters: `icons → store → primitives → views → overlays`, after React +
  Babel. Match the `<script>` block in `index.html`.
- All visual values come from CSS custom properties — theme by setting
  `data-theme="light|dark"` on `<html>`, and `data-ambient="on|off"` to gate the loop.

## Coverage notes
- This kit recreates the **Settings window only**, because that's the one surface present
  in the source. The tray menu and onboarding are referenced in copy but were not designed
  in the source, so they're intentionally omitted rather than invented.
