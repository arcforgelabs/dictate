# Changelog

## 2026-06-23

### Added

- Added a `dictate config` subcommand group for headless/agent setup:
  `set-key <backend> <key>` (format-validated, saved to the OS secret store),
  `set-provider private|online`, `set-model <id>`, and `show` (provider mode,
  model, per-backend key presence, secret-store status). Output is plain and
  scriptable.
- Added provider resilience via a new `ProviderSupervisor`: it tracks the
  preferred vs. active backend with on-device always available as the floor,
  classifies failures (auth / rate-limit / budget / unreachable), and applies
  class-aware exponential backoff with a single cancellable timer (never
  busy-polls). It probes for recovery opportunistically and on network-up, and
  emits `provider-degraded` / `provider-recovered` events to the UI over SSE.
- Added live provider-health tracking end to end: an engine `health_sink`
  reports every online-backend transcription outcome, the UI server publishes
  `provider-health` SSE events on each state change, and the UI hydrates and
  updates from them.
- Added a quiet "or hold Ctrl + D" shortcut hint (derived from the stored
  shortcut) to the ready state.

### Changed

- Made Dictate private by default: an unset provider resolves to the on-device
  `faster-whisper` backend. Online (xAI) transcription now requires an
  explicitly configured key.
- Changed the default push-to-talk shortcut from Ctrl+Right to **Ctrl+D**
  across the engine, daemon, preflight, doctor, Windows control, the
  push-to-talk dialog presets, the default config, and the UI.
- Made recording resilient instead of hard-blocked: recording is never disabled
  by provider state. A degraded provider now shows a one-shot flash-ring pulse
  and toast, an "On-device · <provider> unreachable" strip during recording, and
  a quiet config hint when online with no key — replacing the previous fully
  blocked home screen.
- Long (note-mode) recordings now retry the remote provider up to twice with
  backoff before degrading to on-device; quick push-to-talk dictation keeps its
  existing fail-fast CPU fallback. The supervisor learns from every outcome.
- Dropped the timestamp from the copy-last-note row and shortened the ready-state
  status copy.

### Fixed

- Fixed the engine-version test to assert against `RELEASE_VERSION` dynamically
  instead of a hardcoded version that went stale after CalVer bumps.

## 2026-06-20

### Added

- Added an App update view that distinguishes the Python engine from the
  desktop shell, reports install kind, shows stale shell state, and exposes the
  correct update action for source and packaged installs.
- Added a dedicated Record conversation entry point separate from quick
  push-to-talk dictation.
- Added a daemon single-instance guard so a second tray/headless listener exits
  before it can bind the same shortcut and duplicate typed output.

### Changed

- Made the packaged Linux `.deb` the intended daily-driver path and cleaned up
  source-install launcher precedence so local development installs do not
  silently shadow packaged Dictate.
- Switched the packaged Linux shell to native OS window decorations by default
  for real window-manager shadows, edges, and hit testing.
- Kept the prior frameless custom chrome available for comparison with
  `DICTATE_CUSTOM_CHROME=1 /usr/bin/dictate-ui-shell`.

### Fixed

- Fixed duplicate paste/dictation caused by multiple Dictate listener processes
  running from mixed source and packaged installs.
- Fixed the Linux shell startup race that could spawn more than one bundled
  engine before the first process wrote its UI handshake.
- Removed the transparent fake-edge gutter around the shell window.

### Verified

- Rebuilt and installed the Linux `.deb` daily-driver package locally.
- Ran focused Python tests for update status, UI server, launcher, startup
  selection, and process locking.
- Ran the UI test suite: 30 tests passed.
- Ran the Tauri shell test suite: 7 tests passed.

## 2026-06-18

### Added

- Added chunked streaming dictation for local STT backends so longer recordings
  are transcribed in bounded windows instead of retaining one large capture
  until push-to-talk release.
- Added live transcript events in the Settings UI, including partial/final
  transcript display and stale transcript suppression.

### Fixed

- Bounded audio/transcription queues and terminal recording caches to prevent
  long-running dictation sessions from growing memory without limit.
- Preserved stop-time audio callbacks and short final tails so streamed
  recordings do not lose the last spoken words.
- Kept hosted STT providers on final-audio transcription unless their backend
  explicitly opts into chunk streaming.

### Verified

- Ran the full Python test suite: 280 tests passed.
- Ran the UI test suite: 29 tests passed.
- Verified UI build, Python compile checks, npm package dry-run, and final
  forge re-review.

## 2026-06-06

### Fixed

- Fixed the Linux Settings launcher flow so reopening Dictate focuses the
  existing hidden Settings window instead of starting a disconnected shell.
- Added a Linux update action for the Settings About screen: source checkouts
  can run `update.sh`, while packaged installs open the GitHub release flow.
- Hardened the Tauri shell bridge refresh path so stale UI handshakes are
  recovered after the engine restarts.

### Verified

- Rebuilt and installed the local Linux Tauri shell through the Tauri CLI
  release path, confirming Settings assets load correctly and the second-launch
  single-instance path stays at one shell process.
- Verified the live local engine reports `2026.6.5` before this release bump
  and responds to `/api/update-status`.

## 2026-06-05

### Fixed

- Fixed the Linux Tauri shell startup path so stale `ui-server.json` handshakes
  are ignored and removed instead of preventing the shell from spawning a live
  engine.
- Updated side-specific shortcut labels to use Linux-style names such as
  `Ctrl (R)` while preserving the existing `ctrl_r` engine token.

### Changed

- Switched the local Linux workstation config from `faster-whisper/turbo` to
  `faster-whisper/base` on CPU to reduce release-to-text latency when CUDA is
  unavailable.

### Verified

- Confirmed the local Linux daemon is active under `dictate-local.service`,
  using `faster-whisper/base` with the `ctrl_r` push-to-talk combo.
- Ran focused hotkey and UI server unit tests with the repo virtualenv:
  `PYTHONPATH=src .venv/bin/python -m unittest tests.test_hotkey
  tests.test_ui_server tests.test_headless_ui_server`.

## 2026-06-04

### Added

- Added Windows desktop packaging support for Dictate, including Tauri MSI/NSIS
  bundle targets and a Windows build script that stages the Python engine before
  bundling.
- Added an opt-in Windows Authenticode signing script and release workflow step
  for direct-download `.msi` and `.exe` artifacts. Public release upload still
  requires signature validation, and unsigned artifacts remain internal.
- Added Microsoft Store MSIX packaging for the reserved Partner Center product
  identity `ArcForgeLabs.ArcForgeDictate`.
- Added Microsoft Store API smoke automation with repository variables for
  non-secret IDs and `MSSTORE_CLIENT_SECRET` stored as a GitHub Actions secret.
- Added a guarded manual Microsoft Store MSIX publish workflow. It can check
  status, upload a generated MSIX as an uncommitted draft, or explicitly commit
  a draft after the first manual submission is accepted.
- Added Dictate as a first-class Arc Forge ClawSweeper target with a Dictate
  dispatcher workflow for issue, pull request, and command-comment events.
- Added ClawSweeper default-branch fallback handling so dispatches that omit
  `target_branch` resolve the target repository default branch instead of
  assuming `main`.

### Changed

- Moved public install messaging toward Microsoft Store as the primary Windows
  distribution path, with website/GitHub download artifacts treated as a signed
  secondary path.
- Updated Microsoft Store readiness docs to use the dedicated Dictate privacy
  policy URL, `https://arcforge.au/privacy/dictate`, after Partner Center
  rejected the prior general privacy URL.
- Reclassified hosted PowerShell bootstrap instructions as developer/source
  install guidance rather than the normal public Windows install path.
- Preserved the deprecated personal npm package path only as a compatibility
  landing point; new package and install paths use `@arcforgelabs/dictate`.
- Kept Dictate ClawSweeper automation conservative: review/comment only, with
  scheduled/background runs and auto-close policy disabled while the integration
  is being proven.
- Updated pinned official GitHub Actions to Node 24-compatible majors while
  preserving SHA pinning: `actions/checkout` v6, `actions/setup-python` v6, and
  `actions/setup-node` v5, and `actions/upload-artifact` v5.
- Opted workflows into GitHub's Node 24 JavaScript action runtime ahead of the
  June 2026 runner default change.
- Updated the UI development toolchain to remediate public Dependabot alerts:
  `vite` v8, `vitest` v4, and `@vitejs/plugin-react` v6.

### Verified

- Dictate CI passed on run `26929126354`.
- Dictate Secret Scan passed on run `26929126343`.
- Windows desktop bundle workflow passed on run `26927985488`, producing
  `Dictate_2026.6.5_x64_en-US.msi` and
  `Dictate_2026.6.5_x64-setup.exe`.
- Windows Store MSIX workflow passed on run `26927986863`, producing
  `ArcForgeDictate_2026.6.5.0_x64.msix`.
- Microsoft Store API smoke workflow passed on run `26927988050`.
- Dictate ClawSweeper smoke passed on run `26925824791` against
  `arcforgelabs/dictate#8`.
- Arc Forge Console ClawSweeper smoke passed on run `26929644423` against
  `arcforgelabs/arc-forge-console#136`.
- A second Dictate ClawSweeper smoke passed on run `26930314117` against
  `arcforgelabs/dictate#8`.
- A third sequential Dictate ClawSweeper smoke passed on run `26930384789`
  against `arcforgelabs/dictate#8`.
- Microsoft Store MSIX publish workflow `status` mode passed on run
  `26930465947`; it authenticated, configured Microsoft Store Developer CLI, and
  read the current pending submission as `Certification`.
- Microsoft Store MSIX publish workflow `status` mode passed again on run
  `26930602624`; it performed a read-only status check and reported the pending
  submission as `Certification`.
- Microsoft Store MSIX publish workflow `status` mode passed again on run
  `26930886850`; it performed a read-only status check on the latest commit and
  reported the pending submission as `Certification`.
- UI package audit passed with zero vulnerabilities after the Vite/Vitest
  security update.
- Dictate CI passed on run `26931280731` after the Node 24 workflow runtime
  opt-in.
- Dictate Secret Scan passed on run `26931280721` after the Node 24 workflow
  runtime opt-in.
- GitHub Dependabot reported zero open alerts after the UI development
  toolchain update.
- Microsoft Partner Center certification report
  `a0cf5c57-d578-48d9-b707-68a7a207ff6a` completed on `2026-06-04` with status
  `Attention needed` under policy `10.5.1 Personal Information - Privacy
  Policy`.
- Microsoft Store MSIX publish workflow `status` mode passed on run
  `26988691332`; it reported the pending submission status as
  `CertificationFailed`.
- The Partner Center privacy policy URL was corrected to
  `https://arcforge.au/privacy/dictate` and `Submission 1` was resubmitted on
  `2026-06-05`.
- Microsoft Store MSIX publish workflow `status` mode passed on run
  `26988971067`; it reported the pending submission status as `Certification`.

### Notes

- Microsoft Partner Center submission `Submission 1` for `Arc Forge Dictate`
  was manually submitted and remained in certification during this work.
- The Microsoft Store product identity is:
  - Store ID: `9P5S7747V0BP`
  - Package identity name: `ArcForgeLabs.ArcForgeDictate`
  - Package family name: `ArcForgeLabs.ArcForgeDictate_tbf7er950vsxw`
- Store submission mutation automation remains intentionally pending until the
  first manual submission is accepted and the package/listing API path is
  confirmed for this MSIX/PWA product.
- No Windows signing certificate secret is configured in GitHub Actions yet;
  configure `WINDOWS_SIGNING_PFX_B64` and `WINDOWS_SIGNING_PFX_PASSWORD`, or a
  trusted runner-local `WINDOWS_SIGNING_CERT_PATH`, before expecting public
  direct-download Windows installers.
