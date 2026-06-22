# Dictate — design

Design for **Dictate**, the "Quiet Console" desktop dictation app. The locked product
direction is **Note Capture** — one mic that toggles; every capture is a Note you read /
edit / insert — and its **core is now merged to production** (`../ui/src/`).

> **Source of truth & sync policy.** The Claude Design **cloud** projects are the source of
> truth; the local mirror (`.claude-design-ds/`) is a **disposable, gitignored cache** —
> re-export anytime, never commit. To freeze a stable target, make a deliberate
> **`locks/<name>/`** (the committed durable artifact). See the `claude-design` + `forge` skills.

> **Canonical cloud project:** "Dictate Design System" (`2477ec…`) — the Note Capture ui-kit
> + the design system. The old **"[LEGACY] dictate"** project (`2309408a…`) is superseded and
> flagged for deletion.

## What's here
| Path | What it is |
|---|---|
| **`locks/note-capture-core/`** | **The canonical freeze** of the shipped core (capture + notes + chrome): `LOCK.md` + baseline/implementation captures + the parity verdict. The convergence target the production port was measured against. |
| `review/` | Forge + Claude Design review findings from the port. |
| `platforms/` | Cross-platform chrome study (macOS / Win11 / Win10 / GNOME / KDE). |
| `logos.html`, `logo-marks.jsx` | Brand-mark exploration history. The chosen **cradle-mic** mark is shipped (`../assets/dictate.svg`) and used in the app. |
| `fonts/` | Hanken Grotesk + JetBrains Mono. |
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
design system, superseded by the `2477ec` cloud project), `explorations/` (the A/B/C
concepts), and the loose `dictate-note-capture/` working copy (the lock holds the freeze;
the prototype is re-exportable from the cloud cache). All recoverable from git history.
