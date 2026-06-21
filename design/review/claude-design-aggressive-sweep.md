# Claude Design — aggressive direction sweep (frontend-direction lens)

Source: Dictate Design System cloud project `2477ec21`, Opus 4.8, 2026-06-21.
Brief: be aggressive, not polite — question existence, remove over-show, make survivors
inspired. Agent built a new concept card and rewrote the README product context; the
locked `note-app` was not overwritten.

## Direction verdict: SUBTRACT
"VISUAL NOT CLEAN — one P1 (speaker-name AA, propagated into the spec card) blocks;
everything else is subtraction the lock invites." The agent endorsed the full sweep and
went further than "ship" — the move is removal.

## It built: "Capture moment — concepts" (`exp-capture-moment.html`)
A live, amplitude-driven exploration (synthetic speech-with-pauses signal; toggles for
Signal: speech/silent and Light/Dark). Two hero-mic directions + three visualizers:

**The capture mic — the one hero**
- **A · Breath Cradle** — the cradle arc from the brand mark *is* the button; the capsule
  rests in its cradle. Recording releases the breath: rings born at the rim, swelling with
  your voice, settling to the 3.8s resting breath in silence. Identity and the one motion
  idea become the same object. (Recommended — makes the brand mark load-bearing.)
- **B · Quiet Capsule** — restraint option: no rings; the capsule itself fills with living
  green and breathes in place, one thin halo tracks amplitude. Calmer, less iconic. Use if
  the Cradle reads too animated for a quiet app.

**Recording feedback — pick one signature**
- **1 · Breath Ring** — one ring swells with real RMS, decays to the 3.8s cadence. One
  element, honest, unmistakably alive; breath and amplitude are the same gesture.
- **2 · Halo Bloom** — each speech peak births a soft ring that blooms and fades; ripples
  from the act of speaking. More expressive.
- **3 · Live Thread** — an honest amplitude trace scrolling right-to-left, a real waveform
  (flat when the room is flat). Directly replaces today's static inline wave.

## Per-surface verdicts (agent, endorsing + detailing the sweep)
- **§1 Direction** — Note Capture is the right lock; the items below are pre-lock fixes,
  not reasons to reopen.
- **§2 Visualizers** — three is hedging; pick one. Today's inline wave is a static CSS
  keyframe identical in silence → replace with an amplitude-driven signature.
- **§3 Provider sheet** — cut the matrix → automatic + a single privacy toggle.
- **§4 Note-ready** — drop the Edit ghost (redundant with Read-full-note), fold Copy/Export
  into an overflow, **auto-save on stop so Accept disappears**.
- **§5 Recording + Processing** — CUT the engine talk. Recording sub-status → "Saved as you
  speak" (drop chunk counts/IDs + longstrip). Processing → calm "Transcribing…", no
  percentage, no per-chunk lines. **Felt speed:** live partial transcription so short
  dictations skip a visible Processing state entirely; reserve Processing for long catch-up.
- **§6 Gear** — "Microphone" dead row: remove (app picks default; surface a chooser only on
  the no-device fault). Visualizer segmented control: cut (dies with single-visualizer).
  Brand mark: FINALIZE, drop "candidate" label + aria-label.
- **Foundations** — `--sp-*`, type tiers, warm-paper greyscale, single breath: disciplined,
  no cuts. Only foundation edit = add the AA-safe speaker (Devin) token.

## New findings the brief did NOT name
- **Intentional idle pose** — even "Ready to capture" should be the Breath Cradle's idle
  pose (capsule nested, dead still), a quiet brand signature for free — not "recording
  minus motion."
- **Two destructive vocabularies** — `--danger` (true destruction) vs `--amber` (caveats):
  verify no recoverable fault (mic-denied, no-device) reaches for `--danger`; only "this
  note is gone" may be red.

## Top 3 highest-leverage, ranked (agent)
1. **Fuse the hero mic + visualizer into one Breath Cradle** — solves §2 and §3 [sic: §3 =
   spend-novelty], makes the brand mark load-bearing (forces the mark finalize), spends the
   whole novelty budget on the one moment that is the product.
2. **Strip the engine talk + auto-save on stop** — kills chunk/percentage copy, lets short
   dictations skip Processing (felt speed), deletes Accept. Biggest "quiet" gain.
3. **Fix speaker-name contrast at the token + spec-card level (P1)** — the one true defect,
   baked into the canonical kit. Smallest code, highest correctness stakes.

Concept evidence captured (zoom): the live `exp-capture-moment.html` canvas.
