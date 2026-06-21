# Dictate — frontend-direction assessment (live inspection)

Produced with `frontend-direction`, after pulling the Claude Design **cloud**
project into `.claude-design/` and rendering it live (not just reading repo PNGs).

> **Read this first — the local repo is stale.** The cloud project
> (`claude.ai/design/p/2309408a…`, 2026-06-21) holds a newer **locked** direction:
> **"Note Capture"**. The local `simplified-ui/` files (A/B/C "Concepts",
> 2026-06-20) are **behind it**. The compare-design report shows the cloud and
> local `design/` trees differ in only these two files — the COMPARISON and the
> concepts HTML — i.e. the refinement diverged here. Assess against the cloud.
>
> The earlier version of this note (recommending "lock A + C rows + B discipline")
> is **retracted** — it predated this inspection and litigated a retired decision.

## What is actually locked (cloud): Note Capture

- **One capture object.** The centered mic *toggles* (press start / press stop).
  No Quick-vs-Record split, no second capture area, no notes sandbox, no left
  rail, no dashboard hero.
- **Dictate is the text field.** Capture lands *inside* Dictate as a Note you
  read / accept / edit / copy / insert / export — no external focused field.
- **Long meetings are graceful** — chunked streaming, per-chunk transcription,
  "on device in 30s chunks" reassurance; never "held whole".
- **Speakers first-class**; **capability-gated providers** (xAI for long +
  diarised; on-device fallback with amber caveats; incapable providers hidden).
- **Visualizer is a choice inside the one model** (Ring Pulse default).

## Calibrate — quiet + sparse, and it now lands it (verified live)

- **Ready:** a single centered mic — *"Press the mic and speak — it becomes a
  note"* + hold hint. Nothing else. This *is* recede-until-summoned.
- **Recording:** Ring Pulse green rings, "Recording…", timer, a live streaming
  transcript with the speaker label ("You …"). The one living green = active,
  exactly as the design system prescribes; the button stays the visual anchor.

## Crit

**Works — protect it:**
- The **one-capture-object** decision resolves, at the root, every problem in the
  *old* production Status surface (competing primaries, the same facts three
  times, dual navigation, the notes sandbox). This is the right call and it is
  the whole point of the simplification.
- The recording state is **system-true**: one green, single anchor, transcript
  streams under it — calm, not busy.
- **"Dictate is the text field"** is a strong conceptual move — the right *view*
  removes the need for an external focused field (Bret Victor).

**Refine — grounded in a full state walk** (Ready, Recording, Note-ready,
Expanded note, gear menu, Provider sheet; Processing is a transient auto-advancing
step), ranked by leverage:

1. **Note-ready: the visual primary doesn't match the user's goal.** "Read full
   note" is the one filled button — but reading isn't why anyone dictated; *using*
   the text is. The surface also offers 6–7 actions (Read · Accept · Edit · Copy ·
   Insert · Export · New). Attention follows contrast to the wrong target, and the
   choice count taxes a calm moment (Hick). *Fix:* make **Insert** (or **Accept**)
   the single filled primary; demote Read / Copy / Export to quiet secondaries or
   an overflow. One primary, and let it be the actual goal. **(Highest leverage.)**
2. **Provider sheet — better than feared; keep it.** Inspected: two options,
   radio-select, capability chips in *meaningful* colour (green ✓ supported · amber
   caveats), incapable providers hidden with an honest one-line note, one
   RECOMMENDED guide. Exactly the system's "colour only when it means something".
   Only watch: the capability caption text is small — keep it above the legibility
   floor.
3. **Expanded note is strong** — back-nav, search transcript, a Times (timestamp)
   toggle, speaker-labelled lines with colored initial avatars, readable measure.
   Nothing to change.
4. **Processing** is the one state that won't hold still (it auto-advances to the
   note). Confirm the chunked-progress + "on device in 30s chunks" copy reads calm
   at rest — it's the reassurance moment for long meetings.
5. **Ready-state void** unchanged: reads as intentional rest; keep, don't decorate.

**Verdict — two separate questions, don't conflate them:**

- **Is the direction sound?** Yes. The unified Note-Capture model is a strong,
  defensible decision that resolves the old surface's structural problems. Lock the
  *direction*; build the production work against it, not A/B/C.
- **Is the prototype ready to port?** **No** — and calling it "ready" would be
  wrong. What's verified is the **happy path, dark theme only, one window size,
  mock data**, and it already has one real flaw (Note-ready primary). This is a
  *locked direction with a working prototype*, not a design-locked production
  target.

**Before it could be a lockable production target, verify / resolve:**
- The **Note-ready primary-action** fix (Insert/Accept over "Read full note").
- **Light theme** for every state (system is "both themes first-class"; only dark
  was seen).
- **Error / edge / empty states** — mic permission denied, no mic, provider or
  network failure, on-device fallback active, failed/over-budget chunk, interrupted
  recording, first-run with zero notes. The prototype's listed states are all
  happy-path; confirm these exist at all.
- **Processing at rest** (it auto-advances) and the real
  recording → stop → processing → note transition timing.
- **Reduced-motion** fallback; **contrast** on the small capability captions.
- The **brand mark** (still the Arc candidate, not the final Dictate mic/cradle).
- The **production app is still the old dense version** — none of this lives in
  `dictate-app` / `ui/src` yet. The port is a separate, real effort.

## Design system — already strong; no redirection (Move 3)

The "**Quiet Console**" system (`dictate-ds/`) already encodes the soul I would
otherwise have briefed: *recede-until-summoned*, *one living green = listening*, a
*single 3.8s breath* as the only loop, *warm-not-clinical*, an explicit voice
("no hype, no jargon, no alarm"), a full 7-role type scale (Hanken Grotesk +
JetBrains Mono) and surface tokens for **both** themes. **Move-3 verdict: do not
redirect the system** — it is the standard. The work is bringing the production
app into line with it, which Note Capture does. (My earlier "make recede a
principle / reserve the green" note was redundant — the system already says all of
it; that was the cost of not inspecting first.)

## Process finding

- **Local `simplified-ui/` is behind the cloud.** Anyone porting to
  `dictate-app` / `ui/src` must use the cloud **Note Capture** files, not the
  local A/B/C concepts. Consider promoting the cloud's locked files
  (`COMPARISON.md`, the concepts HTML + `note-app.jsx` / `visualizers.jsx` /
  `icons.jsx`) from `.claude-design/unpacked/current/` into the repo so local ==
  cloud and the stale A/B/C set is retired.
- The cloud's own porting list (in its COMPARISON) already matches this crit:
  remove rail / hero / split / duplicate capture / sandbox; one mic; settings
  behind gear + ⌘K; swap the Arc mark for the Dictate mic/cradle mark; keep the
  single breath.
