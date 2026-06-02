# Dictate — Design System

> **The Quiet Console.** Dictate is a desktop dictation app that types your speech
> straight into whatever app you're focused on. It lives in the system tray and
> surfaces only when summoned. The design language is built to **recede**: warm
> paper greys, one living green for "listening", and a single breathing pulse as
> the only thing in the whole product that ever loops.

This folder is a working design system — tokens, fonts, assets, real component
recreations, and guidelines — so an agent (or a person) can design *for Dictate*
with full fidelity to the shipping product.

---

## Product context

- **Dictate** — a Mac/desktop app (Electron-style window + tray). Hold a push-to-talk
  shortcut, speak, release; the transcribed text is typed at the cursor into the
  focused application.
- **Local-first & honest.** Transcription can run fully on-device (faster-whisper),
  or via hosted providers (OpenAI, xAI/Grok, Google/Gemini). API keys live in the
  OS keychain; the UI always tells you where audio goes.
- **One surface today:** the **Settings window** ("the Quiet Console") with seven
  views — Status, Model, Push-to-talk, Hotwords, Recent history, Startup, Advanced —
  plus a ⌘K command palette, a floating "Listening" HUD pill, and a toast stack.
- Version string in product: `v2026.2.25`.

### Design principles (verbatim from the product)
1. **Quiet by default** — lives in the tray and recedes until summoned. Calm, never attention-seeking.
2. **Local-first & honest** — show where audio goes. Keys live in the OS keychain.
3. **Warm, not clinical** — paper greyscale and soft radii; one living green for "listening".
4. **Calm motion** — a single breathing pulse signals a live agent. Everything else settles and stops.

### Sources this was built from
The system was reverse-engineered from a complete prototype (the source of truth — prefer it over screenshots):
- Source project: `claude.ai/design/p/2309408a-2350-4da0-bb4c-c03c7cfee48a`
  - `dictate-ds/` — the live design-system doc page (`styles.css`, `ds.css`, `ds-foundations.jsx`, `ds-components.jsx`, `icons.jsx`, `primitives.jsx`)
  - `dictate-app/` — the working Settings app (`Dictate Settings.html`, `views.jsx`, `store.jsx`, `overlays.jsx`, `primitives.jsx`, `icons.jsx`, `styles.css`)
  - `assets/arc-mark.svg` — the brand mark
  - `screenshots/` — reference captures
- No external Figma or codebase was attached; all values below are lifted directly from the prototype CSS/JSX.

---

## CONTENT FUNDAMENTALS

**Voice:** quiet, literal, reassuring. Dictate explains *what happens* and *where your
data goes*, never sells. It reads like a calm, competent tool — not a launch.

- **Tense & mood:** plain present tense, imperative for actions. *"Hold your shortcut,
  speak, release."* · *"Run a quick check of microphone, model, output, clipboard and shortcut."*
- **Person:** addresses the user as **you**; the product refers to itself as **Dictate**
  (never "we"). *"Start Dictate automatically when you log in."*
- **Reassurance is a feature.** Privacy and locality are stated plainly and often:
  *"Stored in your system keychain."* · *"Hotwords stay on this device and are never
  packaged or synced."* · *"Runs on this machine — no key, nothing leaves your device."*
- **Casing:** Sentence case everywhere — headings, buttons, rows (*"Launch on sign-in"*,
  *"Check for updates"*). UPPERCASE is reserved for tiny overline **labels** and **chips**
  (`PUSH-TO-TALK`, `LOCAL`, `NEEDS KEY`) with `+.06–.07em` tracking.
- **Punctuation:** the middot `·` separates inline meta (*"11:32 AM · 2h ago"*,
  *"faster-whisper · turbo"*). Em dashes and ellipses set a calm, unhurried rhythm.
  **No exclamation marks.**
- **Length:** short. Titles are 2–3 words; helper text is one plain sentence. Buttons are
  verbs (*Rebind*, *Add word*, *Save & select*, *Run doctor*).
- **Words to avoid:** "AI-powered", "seamless", "magic", hype, and alarm. Red/danger
  language only when something is genuinely destructive (*Reset*, *Uninstall*, *Clear*).
- **Emoji:** none. Ever. Meaning is carried by line icons, the live dot, and copy.
- **Microcopy examples:** *"Ready to dictate"* · *"Listening…"* · *"Inserted into Notes"* ·
  *"That key looks too short"* · *"Names and terms the model should always spell correctly."*

---

## VISUAL FOUNDATIONS

**The vibe:** warm, recessive, paper-like. A tool that feels human and calm — closer to
a well-made native utility than a web app. Everything sits on a single warm-grey hue.

- **Color.** A warm greyscale built from *one paper hue* (`#efece6`). Text is desaturated
  ink set as **alpha** (`rgba(27,26,22,.56)` etc.) so it sits naturally on any surface.
  Exactly **one** chromatic accent in normal use: **live green** (`#2f8f63` light /
  `#4fbd86` dark) meaning "listening / connected / good". `danger` red and `amber` exist
  but are rare. Both light and dark themes are first-class, fully tokenised, and warm
  (dark is a warm near-black `#0a0a0b`, not blue-black). See `colors_and_type.css`.
- **Type.** Two families only. **Hanken Grotesk** (400–800) carries everything human —
  tight, confident headings (heavy 800 weights, negative tracking down to −.03em) and
  calm body. **JetBrains Mono** (400–600) handles the machine: shortcuts, model ids,
  timers, versions, with `tabular-nums`. Seven semantic roles (display/title/heading/
  body/meta/label/mono).
- **Spacing.** Even and few: 4 · 8 · 12 · 16 · 22 · 24 · 40 · 56. Content columns are
  narrow (≤680px) and centered — generous calm whitespace.
- **Backgrounds.** No photography, no illustration, no gradients-as-decoration. The app
  background is flat warm paper; the *only* gradient is a very subtle radial
  (`radial-gradient(120% 120% at 50% 0%, --bg → --bg-2)`) behind the window to seat it.
  A faint 45° hairline cross-hatch appears only in the DS doc demo frames.
- **Corner radii.** Climb with surface size: controls `9px`, cards/fields `13px`,
  panels/options `18px`, the status hero `24px`, chips/toggles fully pill. Nothing is
  sharp-cornered.
- **Cards.** White (`--surface`) on paper, `1px` `--border` (10% ink), `--r-lg` (18px),
  and a *very* soft `--shadow-sm`. No heavy borders, no colored left-accent stripes,
  no glow. Footers and rails use `--surface-2`; inset wells use `--surface-3`.
- **Shadows / elevation.** Four steps (sm → md → lg → pop), all soft and warm. In dark
  mode shadows **deepen** (more opaque black) rather than glow. Resting cards use `sm`;
  hover lifts to `md`; the window/HUD use `lg`; palette/menus use `pop`.
- **Borders.** Hairlines everywhere (`--hairline`, 7% ink) divide rows; `--border` (10%)
  outlines cards; `--border-2` (16%) marks inputs and hover. Keycaps get a 2px-bottom
  border for a physical feel.
- **Transparency & blur.** Used sparingly and purposefully: the sticky top bar and the
  command-palette scrim use `backdrop-filter: blur()`; the palette scrim is `rgba(0,0,0,.32)`.
  Ink/border tokens are alpha so they composite correctly on every surface.
- **Motion.** Functional and brief. One everyday easing `cubic-bezier(.22,.61,.36,1)`,
  a softer entrance easing `cubic-bezier(.16,1,.3,1)`. Durations: `140ms` (hover/tap),
  `240ms` (view/theme), `420ms` (entrance). Views fade-up `~9px` on mount. **The only
  loop in the entire product is the 3.8s "breath"** — a `box-shadow` pulse on a live
  agent (orb, dot, rec light). `prefers-reduced-motion` kills all of it.
- **Hover states.** Surfaces lighten/raise: background steps `--surface → --surface-2/3`,
  border steps to `--border-2`, mini-cards translate `-2px` and gain `--shadow-md`.
  Icons go from `--subtle` to `--muted`/`--fg`.
- **Press states.** Buttons `transform: scale(.98)`. No color flash.
- **Focus.** Inputs: border → `--fg` plus a 3px `--surface-3` ring (soft, not blue).
  Selected option rows: `--fg` border + 1px ink ring.
- **Imagery vibe.** There is essentially no imagery — the product is type, line icons,
  and warm flat surfaces. The single figurative glyph is the **microphone**.

---

## ICONOGRAPHY

- **Style:** custom **Lucide-style line glyphs** — `24×24` viewBox, `currentColor`,
  **stroke-width 1.75**, round caps and joins, no fills. They live inline in
  `ui_kits/dictate-app/icons.jsx` as an `ICONS` map rendered by an `<Icon name size>`
  component. ~35 glyphs: `mic, status, sliders, keyboard, hash, clock, power, gear,
  chev/chevd/back, check, copy, device, key, plus, x, minus, square, search, cpu, bolt,
  refresh, trash, sun, moon, wave, shield, pin, history, download`.
- **Not an icon font, not PNGs.** Everything is inline SVG path data with `currentColor`,
  so icons inherit text color and theme automatically. If you need an icon that isn't in
  the set, draw it to match (24-grid, 1.75 stroke, round) or pull the nearest **Lucide**
  glyph — Lucide is the visual reference and a safe CDN substitute.
- **Brand / provider marks** are the exception: full-color authentic logos
  (Google, OpenAI, xAI, Gemini) rendered via a `<Brand name>` component, used only in
  the Model picker and command palette. Keep these accurate; don't recolor them.
- **The brand mark** (`assets/arc-mark.svg`) is a single `currentColor` glyph — a sharp,
  forge/arc "A" form. Carried at **16–20px** in the title bar and tray. It inherits
  `--fg`, so it's ink on light and bone on dark with no second asset.
- **Emoji / unicode:** never used as UI. The only non-icon symbols are the middot `·`,
  `+` between keycaps, and `×` to remove a chip.

---

## Index — what's in this folder

| Path | What it is |
|---|---|
| `README.md` | This file — context, content & visual fundamentals, iconography, index |
| `PLAN.md` | Cross-platform UI framework plan — Tauri + Python architecture, scorecard, migration phases, macOS/Linux/Windows |
| `SKILL.md` | Agent-Skill manifest so this can be used in Claude Code |
| `colors_and_type.css` | **The token source of truth** — color + type vars (base, dark, semantic) |
| `assets/arc-mark.svg` | The Dictate brand mark (currentColor) |
| `preview/` | Small specimen cards that populate the Design System tab (+ `preview.css`) |
| `fonts/` | **Hard copies** of the two font families (variable TTFs) + their OFL licenses |
| `ui_kits/dictate-app/` | High-fidelity interactive recreation of the Settings app — see its README |

**UI kits:** `ui_kits/dictate-app` — the Quiet Console (Settings window, 7 views, ⌘K
palette, listening HUD, toasts, light/dark).

**Fonts:** Hanken Grotesk + JetBrains Mono are bundled **locally** as hard copies in
`fonts/` (variable TTFs straight from Google's open-source `google/fonts` repo, OFL-licensed).
`colors_and_type.css` declares them via `@font-face`, so the whole system works **offline** —
no CDN. Both are variable fonts covering the full weight axis used here (Hanken 400–800,
JetBrains Mono 400–600). License text: `fonts/HankenGrotesk-OFL.txt`, `fonts/JetBrainsMono-OFL.txt`.
