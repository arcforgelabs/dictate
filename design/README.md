# Dictate — design

Design for **Dictate**, the "Quiet Console" desktop dictation app. The locked product
direction is **Note Capture** — one mic that toggles; every capture is a Note you read /
edit / insert — and its **core is now merged to production** (`../ui/src/`).

> **Source of truth.** Tokens (colour, type, spacing, radius, shadow) and the brand-book
> rules live in the **Dictate design system artifact**:
> <https://claude.ai/artifact/2kMgmfMmYfH5xDuBxKye7D> (`project/README.md` is the brand book,
> `project/tokens.json` the tokens). It was derived from `../ui/src/styles.css` and the
> September 2026 icon reference, so where the code and the artifact disagree the code is
> wrong unless the artifact's note says "source kept". `locks/<name>/` stays the frozen UI
> target the shipped views are measured against. Brand raster assets are regenerated from
> `../assets/*.svg` with `python scripts/render_brand_icons.py`.

> The earlier Claude Design cloud projects ("Dictate Design System" `2477ec…`, the legacy
> `2309408a…`) and the gitignored `.claude-design-ds/` mirror are superseded by the artifact.

## What's here
| Path | What it is |
|---|---|
| **`locks/note-capture-core/`** | **The canonical freeze** of the shipped core (capture + notes + chrome): `LOCK.md` + `captures/` (eight states × light/dark, re-frozen 2026-09-20 after the design-system alignment). Re-render with `tools/capture-lock.mjs`. |
| `review/` | Forge + Claude Design review findings from the port. |
| `platforms/` | Cross-platform chrome study (macOS / Win11 / Win10 / GNOME / KDE). |
| `logos.html`, `logo-marks.jsx` | Brand-mark exploration history. The chosen **cradle-mic** mark is shipped (`../assets/dictate.svg`) and used in the app. |
| `fonts/` | Hanken Grotesk + JetBrains Mono. |
| `tools/capture-lock.mjs` | Playwright script that renders the lock captures from the mock-mode dev server. |
| `WORK-BRIEF.md` | Remaining follow-ups. |

## Status
- ✅ **Note Capture core merged to production** (`../ui/src/`): Breath Cradle capture, note
  flow (Transcribing → Note-ready → Expanded), one quiet titlebar, system-theme default.
  Frozen in `locks/note-capture-core/` (parity VISUAL CLEAN).
- ⏳ **Follow-ups** (see `WORK-BRIEF.md`): settings detail surfaces (cloud-design → port),
  real `/api/insert`, Tauri window resize / per-OS titlebar polish, finish the cloud cleanup.

## Retired (2026-06-22)
The pre-Note-Capture prototypes were retired now that the direction shipped and is frozen in
`locks/`: `dictate-app/` (the dense seven-view console), `dictate-ds/` (the old embedded
design system, superseded by the design system artifact), `explorations/` (the A/B/C
concepts), and the loose `dictate-note-capture/` working copy (the lock holds the freeze;
the prototype is re-exportable from the cloud cache). All recoverable from git history.
