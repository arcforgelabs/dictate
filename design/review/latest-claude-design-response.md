# Claude Design Watch Result

Status: timeout
Captured: 2026-06-21T06:29:03.351Z
URL: https://claude.ai/design/p/2477ec21-a493-41a0-b400-2a65c5bc3bf6

---

 short. Titles are 2–3 words; helper text is one plain sentence. Buttons are verbs (Insert, Accept, Retry, Keep as note, Use on-device instead).

Words to avoid: "AI-powered", "seamless", "magic", hype, and alarm. Red/danger language only when something is genuinely destructive — never on recoverable faults (a dropped connection, a blocked mic, an interrupted recording read calm, not red).

Amber, not red, for caveats. On-device limits, a dropped chunk, and the fallback banner use amber and lead with reassurance: "Couldn’t reach xAI · Your audio is safe on this device."

Emoji: none. Ever. Meaning is carried by line icons, the live dot, and copy.

Microcopy examples: "Ready to capture" · "Recording…" · "Inserted into the focused app" · "Dictate kept what it captured before it stopped — 2:14." · "No notes yet — your captures will appear here."

VISUAL FOUNDATIONS

The vibe: warm, recessive, paper-like. A tool that feels human and calm — closer to a well-made native utility than a web app. Everything sits on a single warm-grey hue.

Color. A warm greyscale built from one paper hue (#efece6). Text is desaturated ink set as alpha so it sits naturally on any surface. Accessibility is a floor, not a nicety: the two secondary text tiers clear WCAG AA (4.5:1) on paper — --muted (.68 ≈ 5.5:1, secondary captions) and --subtle (.64 ≈ 4.8:1, labels/eyebrows); both also pass in dark (.66 / .52). --faint (.22) is non-text only (dots, radio rings, idle waveform bars). Exactly one chromatic accent in normal use: live green (#2f8f63 light / #4fbd86 dark) meaning "active capture / connected / good". Amber (#9a6f24 light / #e0aa55 dark, with --amber-bg/-line/-dot) is reserved for real caveats — on-device limits, a dropped chunk, the fallback banner — and never for alarm. Amber carries meaning through the dot / icon / line + ink text; on the rare occasion words must read amber, use --amber-text (≈ 5.3:1 on paper), never raw --amber (≈ 3.8:1, too low for body text). danger red is reserved for genuine destruction only (never recoverable faults). Both light and dark themes are first-class, fully tokenised, and warm (dark is a warm near-black #0a0a0b, not blue-black). See colors_and_type.css.

Type. Two families only. Hanken Grotesk (400–800) carries everything human — tight, confident headings and calm body. JetBrains Mono (400–600) handles the machine: shortcuts, model ids, timers, versions, with tabular-nums. The five core roles sit on one modular scale (base 15px, ratio ~1.25): meta 12 → body 15 → heading 19 → title 23 → display 29. Display (800) and Title (700) differ by weight, not just size. label (11/700 caps) and mono (12) are off-scale utility tiers.

Spacing. Even and few, on a strict 4px rhythm with no near-duplicates: 4 · 8 · 12 · 16 · 24 · 40 · 56. The capture window is narrow (~460px) and centered; content centers within it — generous calm whitespace.

Backgrounds. No photography, no illustration, no gradients-as-decoration. The app background is flat warm paper; the only gradient is a very subtle radial (radial-gradient(120% 120% at 50% 0%, --bg → --bg-2)) behind the window to seat it. A faint 45° hairline cross-hatch appears only in the DS doc demo frames.

Corner radii. Climb with surface size: controls 9px, cards/fields 13px, panels/provider sheet/notice 18px, large surfaces 24px, the app window 22px, chips/toggles and the round mic button fully pill. Nothing is sharp-cornered.

Cards & surfaces. --surface on paper, 1px --border (10% ink), soft radii, and a very soft --shadow-sm. No heavy borders, no colored left-accent stripes, no glow. The rail/footers use --surface-2; inset wells and segmented tracks use --surface-3. The mic button rests on --surface-2 and turns --live-bg/--live while recording.

Shadows / elevation. Four steps (sm → md → lg → pop), all soft and warm. In dark mode shadows deepen (more opaque black) rather than glow. Resting cards use sm; the mic button + hover lift use md; the window/toasts use lg; gear menu, provider sheet use pop.

Borders. Hairlines everywhere (--hairline, 7% ink) divide rows; --border (10%) outlines cards; --border-2 (16%) marks inputs and hover. Keycaps get a 2px-bottom border for a physical feel.

Transparency & blur. Used sparingly: the gear-menu and provider-sheet scrim is a flat rgba(0,0,0,.28). Ink/border/amber tokens are alpha so they composite correctly on every surface.

Motion. Functional and brief. One everyday easing cubic-bezier(.22,.61,.36,1), a softer entrance easing cubic-bezier(.16,1,.3,1). Durations: 140ms (hover/tap), 240ms (theme/the mic morph), 420ms (entrance). Sheets fade-up on mount. The only loop in the entire product is the 3.8s "breath" (--breath) — a box-shadow pulse on a live agent (the recording button, the live dot), joined by the 2.4s recording ring pulse (--ring). Reduced motion (prefers-reduced-motion and a runtime toggle) degrades the breath and rings to a static state-color — a steady green ring / green dot / steady waveform — never to nothing; the live state must always read. The breath halo color is tokened per theme (--live-glow) so it matches each theme's --live exactly (light glow on light, not the dark-mode green).

Hover states. Surfaces lighten/raise: background steps --surface → --surface-2/3, border steps to --border-2, mini-cards translate -2px and gain --shadow-md. Icons go from --subtle to --muted/--fg.

Press states. Buttons transform: scale(.98). No color flash.

Focus. Every interactive control gets one tokenized keyboard-focus ring — :focus-visible { outline: 2px solid var(--fg); outline-offset: 2px } — defined once in colors_and_type.css and reading on any surface in both themes (pointer clicks stay clean). Selected option/provider rows additionally take a --fg border + 1px ink ring; the selected provider radio fills with --fg.

Small green labels. Green as text below ~18px (the Recommended tag, the active Times toggle) uses --live-text (#1d6b48 light, ≈ 5.4:1) — not raw --live (≈ 3.2:1 on --live-bg, which fails AA). Borders, fills, large status text, and icons keep --live. Dark-mode --live already clears AA as text, so --live-text equals it there.

Spacing is bound to tokens. The kit consumes var(--sp-*) for its padding/gaps (no stray off-scale pixels) — the system uses its own 4px-rhythm scale.

Imagery vibe. There is essentially no imagery — the product is type, line icons, speaker avatars (initial in a colored ring), and warm flat surfaces. The single figurative glyph is the microphone (now the brand mark too).

ICONOGRAPHY

Style: custom Lucide-style line glyphs — 24×24 viewBox, currentColor, stroke-width 1.75, round caps and joins, no fills. They live inline in ui_kits/dictate-note-capture/icons.jsx as a P map rendered by an <Icon n size> component. ~28 glyphs: mic, stop, gear, cmd, chev/chevd/back, check, copy, insert, share, edit, expand, search, x, lock, cloud, cloudoff, clock, users, layers, alert, refresh, micoff, device, trash. The stop glyph is the one solid-fill icon (the recording button). Keycaps render via <Keys combo> (e.g. ⌃ + ⌥ + D).

Not an icon font, not PNGs. Everything is inline SVG path data with currentColor, so icons inherit text color and theme automatically. If you need an icon that isn't in the set, draw it to match (24-grid, 1.75 stroke, round) or pull the nearest Lucide glyph — Lucide is the visual reference and a safe CDN substitute.

Brand / provider marks: the provider sheet uses a simple cloud line glyph for hosted (xAI) and a lock glyph for on-device — not full-color vendor logos. Keep the hosted/on-device distinction legible; the cloud icon carries --live.

The brand mark (assets/dictate-mark.svg) is the new “cradle mic” — a filled capsule (the mic) cradled by an open arc (the stand), a single currentColor glyph. It replaces the legacy forge-“A”. Carried at 16–20px in the title bar and tray; it inherits --fg, so it's ink on light and bone on dark with no second asset. (The same shape is the Mark component in the kit's icons.jsx.)

Emoji / unicode: never used as UI. The only non-icon symbols are the middot ·, + between keycaps, and × to remove a chip.

Index — what's in this folder
Path	What it is
README.md	This file — context, content & visual fundamentals, iconography, index
SKILL.md	Agent-Skill manifest so this can be used in Claude Code
styles.css	Root global stylesheet — @imports colors_and_type.css (link this one file)
colors_and_type.css	The token source of truth — color + type vars (base, dark, semantic) + the breath motion
assets/dictate-mark.svg	The Dictate “cradle mic” brand mark (currentColor)
preview/	Small specimen cards that populate the Design System tab (+ preview.css, cards.css)
fonts/	Hard copies of the two font families (variable TTFs) + their OFL licenses
ui_kits/dictate-note-capture/	High-fidelity interactive recreation of the Note-Capture app — see its README

UI kits: ui_kits/dictate-note-capture — the locked Note-Capture direction: one mic that toggles, every capture a Note (Ready → Recording → Processing → Note → Expanded), three recording visualizers, provider capability sheet, every fault/blocker state, light/dark.

Fonts: Hanken Grotesk + JetBrains Mono are bundled locally as hard copies in fonts/ (variable TTFs straight from Google's open-source google/fonts repo, OFL-licensed). colors_and_type.css declares them via @font-face, so the whole system works offline — no CDN. Both are variable fonts covering the full weight axis used here (Hanken 400–800, JetBrains Mono 400–600). License text: fonts/HankenGrotesk-OFL.txt, fonts/JetBrainsMono-OFL.txt.

Brand
Dictate mark & wordmark
cradle-mic mark (currentColor), light + dark lockups
Feedback
Edit
Add usage notes
Voice — how Dictate speaks
Plain & calm vs hype & alarm
Feedback
Edit
Add usage notes
Colors
Dark theme surfaces
Every token re-declared; warm near-black
Feedback
Edit
Add usage notes
Ink tiers — text contrast
Muted & subtle clear WCAG AA (4.5:1) on paper; faint is non-text only
Feedback
Edit
Add usage notes
Borders & hairlines
Three line weights as ink alpha
Feedback
Edit
Add usage notes
Signal colors
Primary, the one living green, danger; amber for REAL caveats only
Feedback
Edit
Add usage notes
Surfaces — warm paper greyscale
Paper → inset, lightest to deepest
Feedback
Edit
Add usage notes
Components
Action hierarchy
One filled primary (Insert) · secondary · ghost · link
Feedback
Edit
Add usage notes
Capture button — states
Ready · recording (stop) — the mic IS the record button
Feedback
Edit
Add usage notes
Transcript / expanded view
Search + Times toggle + speaker lines
Feedback
Edit
Add usage notes
Keyboard focus ring
Tokenized :focus-visible — outline 2px var(--fg), offset 2px, every control, both themes
Feedback
Edit
Add usage notes
Note object
Title, meta (duration · speakers · provider), Insert-primary CTA
Feedback
Edit
Add usage notes
Notice & blocker pattern
Calm faults — reassurance first, no alarm-red on recoverable states
Feedback
Edit
Add usage notes
Provider capability sheet
Green = supported, amber = caveat; incapable providers hidden
Feedback
Edit
Add usage notes
Speaker line
Initial avatar · colored name · text · optional time
Feedback
Edit
Add usage notes
Recording visualizers
Ring pulse (default) · inline wave · transcript stream
Feedback
Edit
Add usage notes
Note Capture — full app
The locked direction: one mic that toggles, every capture a Note (interactive)
Feedback
Edit
Add usage notes
Exploration
Capture moment — concepts
Hero cradle-mic + 3 amplitude-driven visualizers (live)
Feedback
Edit
Add usage notes
Spacing
Elevation system
Soft, warm, low — never glowy
Feedback
Edit
Add usage notes
Radius scale
Climbs with surface size · 9 → pill
Feedback
Edit
Add usage notes
Spacing scale
Even & few · strict 4px rhythm · 4 → 56
Feedback
Edit
Add usage notes
Type
Type families
Hanken Grotesk (human) + JetBrains Mono (machine)
Feedback
Edit
Add usage notes
Type scale — 7 roles
One modular scale, base 15 · ratio ~1.25
Feedback
Edit
Add usage notes
