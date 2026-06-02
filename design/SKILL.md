---
name: dictate-design
description: Use this skill to generate well-branded interfaces and assets for Dictate, either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the `README.md` file within this skill, and explore the other available files.

Dictate is a quiet, warm, local-first desktop dictation app ("the Quiet Console").
The whole language is built to recede: warm paper greyscale, one living green
(`--live`) for "listening", soft low shadows, two type families (Hanken Grotesk for
humans, JetBrains Mono for the machine), and almost no motion — the only loop is a
3.8s "breath" on a live agent.

Key files:
- `README.md` — full context, content fundamentals, visual foundations, iconography.
- `colors_and_type.css` — the token source of truth (color + type vars, light + dark, semantic roles). Link it and build with the variables.
- `assets/arc-mark.svg` — the brand mark (a `currentColor` glyph; carry at 16–20px).
- `preview/` — small specimen cards showing colors, type, spacing, components, brand.
- `ui_kits/dictate-app/` — an interactive recreation of the Settings app; lift its `icons.jsx`, `primitives.jsx`, and `styles.css` for accurate components.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets
out and create static HTML files for the user to view. If working on production code,
copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to
build or design, ask a few questions, and act as an expert designer who outputs HTML
artifacts _or_ production code, depending on the need.

Non-negotiables when designing for Dictate: sentence case (UPPERCASE only for tiny
labels/chips); no emoji; no hype words ("AI-powered", "seamless", "magic"); never add a
second accent color — green is the only one; keep motion minimal and calm; warm dark,
never blue-black.
