# Dictate — Record Categories (Quick vs Meeting): filter toggle + per-category sync

**Status:** Proposed · **Owner:** product/design · **Phase 1 (this spec):** list filter toggle + quick-copy scoping · **Phase 2:** per-category sync scope

## Why

Dictate captures two genuinely different things, but the UI conflates them:

- **Quick records** — hold Right Ctrl, speak, get text. Fast, high-volume, copy-and-paste. Stored in the rolling **`history`** collection; surfaced as the front-page **quick-copy**.
- **Meetings** — the **Meeting** button, a full recording, diarized into **Speaker N** segments with timestamps. Stored as **`note` + `segment`**. Heavier, fewer, reference material.

Today the dictations list (`ui/src/views.jsx`, "Search dictations") shows them together, the front-page quick-copy can be polluted by non-quick items, and sync is all-or-nothing. This also caused a real bug: a long quick dictation landed in `history` but the list reads `note`, so it looked "lost." Separating the two fixes that class of confusion.

## The two categories

| | Quick record | Meeting |
|---|---|---|
| Capture | Hold Right Ctrl (`captureMode !== "meeting"`) | **Meeting** button (`startMeetingRecording`) |
| Shape | Plain transcript, no diarization | Diarized `segments` (speaker + timestamps) |
| Collection(s) | `history` | `note` + `segment` |
| Front-page quick-copy | **Yes** — this is the quick-copy | **Never** |
| Volume | Many, ephemeral-ish | Few, kept |

### Discriminator — derive, don't tag (decision)
A record is a **meeting** iff it has segments: `normalizeSegments(note.segments).length > 0`; otherwise **quick**. This is already how the app decides diarized-vs-plain rendering (`views.jsx`/`App.jsx`), so it needs **no new field and no migration**. Revisit an explicit `kind: "quick" | "meeting"` only if we later need user-retagging (e.g. promoting a quick note to a meeting) — out of scope now.

## Phase 1 — the filter toggle (the prototype)

A 3-way segmented control in the dictations list header (`notes-search` row, top-right — where the close/notebook control sits):

```
[ All ][ Meetings ][ Quick ]
```

- **Reuses the existing pill style** (`engine-opt`/segment control used for *English | Multilingual* and *Normal | Beta*) — zero new visual language, per the house rule.
- **View filter only.** It does not change how you capture (hold = quick, Meeting = meeting stay orthogonal). It never mutates data.
- **Persists** the last choice as a UI pref (alongside `ui-prefs.json`), default **All**.
- Filtering runs *before* the existing search box, so search operates within the selected category.
- **Empty states per filter:** "No meetings yet." / "No quick records yet." / (existing) "Your notes will appear here" for All-empty; the no-search-results state is unchanged.
- Optional (nice-to-have): a small count next to each segment, e.g. `Meetings · 12`.

### Quick-copy scoping
The front-page quick-copy strip draws **only** from `history` (quick). A meeting never appears there. (Largely true already via the `history` source; make it explicit and add a test so a meeting can't leak in.)

## Phase 2 — per-category sync scope

Sync is already **per-collection** (`history`, `note`, `segment`, `lexicon`, `settings`), so scoping is a filter on which collections push, not new plumbing.

**Sync scope** setting:

| Scope | Collections synced |
|---|---|
| **Meetings only** (default) | `note`, `segment` (+ `lexicon`, `settings`) |
| **Everything** | above **+ `history`** |
| **Off** | none |

- **Placement (decision):** the **Sync row** of the account panel — a compact selector shown where sync already lives. This is *not* a settings menu (the app deliberately has none; config is otherwise `dictate config`), just a contextual control on the thing it configures. Also settable via `dictate config set sync-scope …` for parity.
- Default **Meetings only** matches the intuition that meetings are the reference material worth carrying across devices, while quick records are local scratch.
- Changing scope is forward-only (doesn't retro-delete already-synced data); narrowing scope stops pushing that collection.

## Behavior / edge details

- Archived notes: the category filter applies to the active list; archive view (if any) is unaffected this phase.
- A quick record opened/expanded still renders as plain text; a meeting renders segments — unchanged.
- History entries surfaced in the list (via the `history`→note mapping in `App.jsx`) are **quick** (empty segments) and filter accordingly.

## Testing

- Filter: with a mix, `All` shows both; `Meetings` shows only segmented; `Quick` shows only non-segmented; counts correct; persistence across reload (mock pref).
- Quick-copy: a meeting is never offered as the front-page quick-copy.
- Phase 2: sync-scope=meetings pushes `note`/`segment` but not `history`; =everything includes `history`; =off pushes nothing; CLI parity.

## Out of scope
Retagging/moving records between categories; per-record sync opt-out; archive-view filtering; any capture-flow change.

---

*Phase 1 (toggle + quick-copy scoping) prototyped in `ui/src/views.jsx` reusing the existing segmented-pill style; Phase 2 (sync scope) follows.*
