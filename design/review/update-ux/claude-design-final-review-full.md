FINAL REVIEW: Dictate App update — production readiness

Verdict: no P0/P1. Two P2, three P3. The platform-awareness criterion that was the main risk is met — ship-blocking issues are absent; the P2s are truthfulness defects worth fixing before release.

Criteria scorecard
✅ Platform/install-kind aware — installKind drives isSource/manual; Windows package copy explicitly states "Dictate does not have an in-app Tauri updater wired yet" (phaseCopy). Linux source build-deps reachable only via build_deps_missing/linux-source (failureTitle/failureCopy). This resolves my earlier DS-1/DS-3.
✅ No prototype affordances in prod — grep for ReviewTweaks|protoswitch|Tweaks|Simulate…|PROTOTYPE|JUMP TO STATE → zero matches.
✅ Backend contract complete — /api/update-status emits platform, installKind, engine, shell, shellStale, phase, step, progress, actions, commands, missingDeps, errorCode, errorDetail. UI invents no data the server can't supply.
✅ Update view structure — version panel (both paths), stale callout, check/update/restart/manual actions, advanced terminal disclosure all present.
⚠️ No-regression (Record/PTT/Model/History) — UNVERIFIED; screenshots not accessible in this project.
IMPLEMENTATION DRIFT (repo vs approved prototype)

D-1 · P2 · Engine row can render "stale" when the engine is actually current Route: App update → version panel, stale-shell state. Evidence: <VersionRow label="Engine" … stale={!!engine.stale || !!u.updateAvailable} />. In the canonical stale-shell case the engine is current but updateAvailable is true (driven by the stale shell), so the engine row shows current → latest as if it needs updating — directly contradicting the callout's "The engine is on vX … this window is still old." The whole feature exists to show that split honestly; this muddies it. Smallest fix: drop || u.updateAvailable — use stale={!!engine.stale}. Backend already emits per-component stale.

D-2 · P2 · "Restart Dictate now" button only shows a toast telling the user to restart manually Route: App update → restart phase. Evidence: primaryLabel … phase === "restart" ? "Restart Dictate now" but primaryAction … phase === "restart" ? () => s.toast("Restart Dictate from the app menu"). The label promises an action the handler doesn't perform — the exact "truthful and actionable" goal this surface was built for. Smallest fix: if the shell can self-restart, wire it; if it can't, relabel to "How to restart" and keep the instructional toast. Don't say "now."

DESIGN-SOURCE / COPY ISSUES

D-3 · P3 · Stale callout overline reads "Ready" — semantically a warning, drift from approved amber/alert treatment Route: App update → stale callout. Evidence: <div className="t-label">Ready</div> above "Engine updated, app window still old." The approved prototype used an alert icon + amber chip, not a "Ready" label (which in this design system's vocabulary pairs with live-green and reads as success). Risk of a warning state looking like a good state. Smallest fix: replace the "Ready" overline with the prototype's alert icon + amber styling; if a label is wanted, use "Action needed." (Confirm against status-stale.png — I couldn't open it.)

D-4 · P3 · "Run the installer or package manager" / "package manager" copy on Windows Route: App update → manual step list & Windows package phaseCopy. Windows users run a signed installer, not a package manager. Minor untruth. Smallest fix: branch step-2 copy — Windows: "Run the installer"; Linux package: "Install it with your package manager."

D-5 · P3 · Advanced "update from a terminal" shows a release URL as a "command" Route: App update → Advanced disclosure, manual installs. Evidence: code renders u.commands?.release (a URL) under a terminal heading, and copyCommand toasts "Copied update command." A URL isn't a terminal command. Smallest fix: for manual/release installs, relabel the disclosure to "Open the release page" with the URL as a link, and reserve the terminal framing for *-source installs that actually emit commands.update.

Cannot confirm without the missing evidence
Visual token adherence on the new classes (version-panel, update-callout, update-card, numbered .step badges) — the prototype's soft-card/amber/--live-bg system. Need update-*.png.
No-regression on Record conversation, Push-to-talk, Model, Recent history — need the four view-*.png.

Re-copy design/review/update-ux/evidence/*.png into this project (the path arrived empty) and I'll close D-3 and the regression line in a follow-up pass. Nothing here blocks merge except D-1 and D-2, which I'd fix first.

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