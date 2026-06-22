# Claude Design Evidence Request

Status: request
Captured: 2026-06-19T02:47:03.615Z
URL: https://claude.ai/design/p/2309408a-2350-4da0-bb4c-c03c7cfee48a?file=dictate-app%2FDictate+Settings.html

---

REQUEST: evidence needed to score implementation drift

I can't reach the harness; please collect from 127.0.0.1:5173:

REQUEST 1 — Screenshot: Status view, window state where shellStale === true
  Need: confirm the stale-shell banner renders, copy matches "Engine updated — app window still old".

REQUEST 2 — Screenshot: App update view, each phase
  checking · available · working · restart · failed · uptodate
  (and, if implemented, the same set with platform=Windows and platform=macOS).

REQUEST 3 — Source file: the repo's App update view component (ui/src/.../Update*.{tsx,jsx,vue})
  Need: confirm platform/install-kind branching exists and which copy strings are used per platform.

REQUEST 4 — Source/DOM: confirm NO prototype affordances ship in prod
  Grep result for "ReviewTweaks", "protoswitch", "Tweaks", "Simulate missing deps",
  "Prototype" in the built bundle — expect zero matches.

REQUEST 5 — Backend: the ui_server status payload shape for update
  Need fields actually emitted: platform, installKind, engine{current,latest,path},
  shell{current,latest,path}, phase, step, progress, missingDeps[]. Confirms the UI
  isn't inventing data the server can't supply.

REQUEST 6 — Screenshots: Record conversation, Push-to-talk, Model, Recent history views
  Need: confirm no regression from adding the update surface (nav order, ⌘K entries).


I'll convert these into a FINAL REVIEW: with drift findings (severity + route + evidence + smallest fix) once the conductor returns them. The single most important answer: does the repo's failed-state branch on platform (REQUEST 3), since DS-1/DS-3 are the only criteria currently at risk.

Dictate Design System




Opus 4.8
Send
Dictate Settings
Mark up
Comments
Edit
Hide tweaks
100%
Present
Share
S
