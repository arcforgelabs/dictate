# Changelog

## 2026-09-25-2

### Fixed

- The Linux dock and app menu show the Dictate icon instead of a generic
  microphone. The packaged app's own launcher entry used a fallback icon that
  hid the one the `.deb` installs. Existing entries are repaired on next start.

## 2026-09-25-1

### Fixed

- The packaged engine includes the X11 hotkey library, so a normal desktop
  session can dictate without being in the `input` group.
- Pasting into a terminal uses plain text. The focused window is recognized
  from its process and window class, including Ghostty, not from a single app
  name.
- A disconnected engine no longer writes stock demo sentences into the
  dictation list.
- Dictation stays on CPU when every NVIDIA GPU is bound to vfio for a VM.
  The RTX 4090 passed through to Windows is not taken.

## 2026-09-25

### Fixed

- The dictation list and **Copy last dictation** follow when the words were
  spoken. A crash recovery that stamped old notes with a later finish time no
  longer floats those notes above a new dictation.
- A saved backend this build does not ship, including the removed xAI, OpenAI,
  and Gemini backends, is rewritten to Parakeet when the desktop UI loads. The
  window was reporting `faster-whisper` for that stale setting even though the
  engine was already running Parakeet.

### Changed

- The About dialog no longer shows a model name. Version, package, and the
  update channel stay.
- Starting a meeting, and the All / Meetings / Quick filter, are on the beta
  channel only. The normal channel is dictation, and every saved note stays
  in the one list.
- Dictation into a terminal, including the Grok CLI, is inserted with
  Shift+Insert as plain text. Ctrl+V in that CLI treats a WebKit clipboard
  as a file chip.
- A `.deb` update downloads while Dictate stays open. The app installs that
  package and restarts only after a second click.
- Stable and beta are separate builds. The installed version decides which
  one you have. About no longer switches between them.

## 2026-09-20

This is the first published release since 2026.7.4; the 2026-09-19 entry below
was versioned but never tagged or published, and ships here.

### Added

- `distil-large-v3.5` is selectable on the faster-whisper lane (English only,
  about one WER point better than `turbo` at the same speed).
- Transparent brand marks, a circular badge, and Store/MSIX logos rendered
  from the brand SVG.

### Changed

- ONNX Runtime moved to 1.30 for the CPU and CUDA lanes. The CUDA lane now
  uses CUDA 13 runtime wheels and needs NVIDIA driver 580 or newer; on older
  drivers Parakeet falls back to CPU. `onnxruntime-directml` is capped at
  1.24.x, the last published DirectML wheel.
- `onnx-asr` 0.12 and `pyannote.audio` 4.0.7.
- The desktop views follow the brand-book spacing and colour rules.
- `parakeet-tdt-0.6b-v2` stays the English default after a head-to-head with
  `parakeet-unified-en-0.6b`; the evaluation is recorded in
  `docs/TRANSCRIPTION_PLAN.md`.

### Fixed

- The published npm `latest` package now carries the Python source, so
  `npx @arcforgelabs/dictate install` works on Linux on the stable channel.
- Documentation no longer describes the removed cloud, Pro, or API-key
  surfaces.

## 2026-09-19

### Removed

- Dictate is now local-only. Accounts, subscriptions, encrypted cloud sync,
  hosted transcription and API-key configuration are gone, along with the
  remote-provider fallback machinery. 27,064 lines across 107 files were
  deleted. See `docs/local-only-audit.md`.
- The `dictate pro` command tree, and the `dictate config set-key`,
  `set-provider` and `set-cloud-preference` subcommands.
- The hosted OpenAI, xAI and Gemini transcription backends. Only local
  engines remain: Parakeet (with its diarisation variants), faster-whisper
  and WhisperX.
- The `cryptography` runtime dependency, which existed only to encrypt sync
  records.

### Changed

- `dictate config show` reports the local backend instead of a private/online
  provider mode, and no longer prints key or secret-store status.
- The desktop UI's account dialog is replaced by a smaller About dialog. The
  version rows, the Stable/Beta update channel selector and the update actions
  are unchanged and live there now.
- The privacy policy is rewritten: with no account and no network
  transcription path, the only things that reach the network are model
  downloads, update checks and Microsoft Store install telemetry, none of
  which carry dictation content.

### Upgrade notes

- No migration is required. Transcription, dictation history, notes, hotwords
  and preferences are unaffected, and all local data stays where it is.
- A saved `stt_backend` of `openai`, `xai` or `gemini` is no longer valid.
  Startup already rejects an unknown backend and falls back to the
  hardware-appropriate local default, so no action is needed.

## 2026-08-04

### Changed

- The repository is now private. Update checks no longer depend on repository
  visibility: the `stable` channel resolves the latest version from the npm
  registry's `latest` dist-tag first, falling back to the GitHub API. Previously
  a private repository would have put every install into a visible
  `check_failed` state showing a raw HTTP 404.

### Known issues

- Linux `stable` install/update via npm fails until a new self-contained stable
  release is published. See `KNOWN_ISSUES.md`.

## 2026-07-13

### Fixed

- Linux microphone capture after Ubuntu 26 / PipeWire upgrades: the frozen engine
  no longer bundles private `libportaudio` / `libasound` / `libpulse`. Capture
  uses distro `libportaudio2` (+ `libpulse0`), and the recorder prefers the
  Pulse host API / soft PCMs and resamples to 16 kHz when a device cannot open
  at that rate.
- Beta/unstable Linux `.deb` updates: the unstable publish lane now attaches a
  `.deb` to the prerelease, and the in-app updater downloads that channel tag
  (not only GitHub `latest`). Linux packaging pins CPU torch and strips
  nvidia/triton so the `.deb` stays under GitHub's 2 GiB asset limit.

## 2026-07-04

### Added

- NVIDIA Parakeet-TDT English speech-to-text backend (ONNX via `onnx-asr`, no
  NeMo/torch). On CPU it is both faster and more accurate than Whisper
  `small.en` (~6% WER, ~13x real-time), emits punctuation and casing directly,
  and — being a transducer — outputs silence instead of hallucinating filler.
  It is now the default on-device engine for English on CPU.
- A Private-mode language toggle (English / Multilingual) on the home: English
  uses the on-device Parakeet engine; Multilingual falls back to the
  hardware-aware Whisper tier. No provider or brand names surface in the UI.
- Automatic capture gain control and optional noise suppression on the input
  path, so hot microphones no longer clip into garbage transcriptions and no
  manual level tuning is required across different mics and environments.

### Changed

- Parakeet decodes the whole utterance in one pass rather than through streaming
  chunks: it has no prompt input to carry context across chunk seams, so
  full-utterance decoding is both higher quality and, at ~13x real-time, still
  low-latency.
- The canonical Linux install is now per-user (`install.sh --user`, under
  `~/.local`): one venv process both dictates and serves the UI, and in-app
  updates apply without `sudo`/`pkexec`.

### Fixed

- The desktop shell is now built through the Tauri CLI (not a raw `cargo build`),
  which embeds the frontend. A plain cargo build omitted the `custom-protocol`
  feature and the shell tried to load the dev server, showing "Could not connect
  to localhost: Connection refused" at runtime.
- The webview reconnects its live event stream after the engine restarts (e.g.
  an in-app update), re-resolving the new port/token and re-syncing state, so the
  dictation history and quick-copy no longer freeze at their last snapshot.

## 2026-07-02

### Changed

- Local (on-device) dictation now streams through overlapping, silence-aligned,
  prompt-threaded chunks that are merged into the transcript, instead of joining
  independent 2-second windows. This removes the word-splitting and duplication
  ("confetti") that made local dictation unreliable: on-device quality now
  tracks a full-utterance decode while keeping push-to-talk latency low (the
  perceived wait is the final chunk, not a re-decode of the whole recording).
- The default on-device model is now chosen by hardware, from one resolver used
  everywhere (startup, tray, `dictate doctor`, the UI, and the installers). A
  CUDA GPU or a capable CPU (~8 GB+ RAM and 8+ cores) defaults to the
  higher-quality `turbo` model; weaker CPUs default to `small`. No machine is
  told it runs `turbo` while actually running `small`, and installers no longer
  force a ~1.5 GB `turbo` download onto a box that will run `small`.
- On-device decode quality was restored for dictation (beam search + generous
  VAD padding so word onsets are not clipped at chunk boundaries), while long
  note recordings keep their lighter, CPU-tuned decode settings unchanged.

### Fixed

- The GUI privacy toggle no longer pins `turbo` into config on a weak machine
  (which previously bypassed the hardware-aware default permanently).
- Case- and punctuation-only differences at a streamed chunk seam are now
  de-duplicated, so overlapping words are not typed twice.

### Added

- Dictate Pro control-plane baseline (account auth, entitlements, Stripe
  handling, relay/server). Pre-release scaffolding; the purchase path is not yet
  wired end-to-end (see `docs/GOALS.md`).

## 2026-06-25

### Added

- The installed Linux app (`.deb`/AppImage) now registers its launcher and
  start-on-sign-in autostart entry on first run, pointing at `dictate-ui-shell`.
  Previously only the source `install.sh` set these up, so packaged installs
  never started on login despite the docs saying they did. One-time and gated to
  the frozen app, so it never overrides a user who later disables startup.
- `dictate stop` command — stops a running engine via its single-instance lock
  (SIGTERM, then SIGKILL fallback). Updaters use it so a fresh engine can claim
  the lock cleanly instead of colliding with a stale daemon.
- Clean shutdown on Linux update: `install.sh`/`update.sh` stop the running
  engine before reinstalling, and the `.deb` ships a `preinst` that stops the
  engine and desktop shell before unpacking an upgrade. Previously the old engine
  kept running and held the lock, so the newly installed engine could not start
  (Windows `update.ps1` already stopped the old process; Linux did not).

### Fixed

- Autostart/launcher `.desktop` entries written by the frozen app now target
  `dictate-ui-shell` instead of a `~/.local/bin/dictate` console script that does
  not exist in packaged installs — the cause of "Dictate doesn't start / the
  hotkey does nothing" after switching from a source install to the `.deb`.
- `dictate doctor` now flags launcher/startup entries whose `Exec` target is
  missing (e.g. a stale pip-era `~/.local/bin/dictate` left behind after moving
  to the package) and `dictate doctor --fix` repairs them.
- Quietened startup log noise: passively enumerating provider key status (done
  for every backend on startup) no longer logs a validation failure for an
  unused, optionally-configured backend (e.g. a stale `openai` key while running
  local faster-whisper). The status is still reported; only the noisy log is
  suppressed. Explicit user validation and the provider health probe still log.

## 2026-06-23 (later)

### Changed

- Restored on-screen navigation that the native-decorations switch had hidden:
  the capture (mic) home now carries a settings gear and a Notes button, since
  the custom titlebar holding the old gear/search is hidden under native window
  decorations. The capture screen stays the home; Notes is a searchable list of
  recent dictations one tap away, and back returns to the mic.
- Made the Wayland default push-to-talk shortcut Ctrl+D too, matching every
  other platform (it previously fell back to Ctrl+Space on Wayland).

### Fixed

- Re-centred the cradle-mic desktop/app icon. It was shifted off-centre; the
  Linux package icons and the Windows `.ico` are regenerated from the canonical
  `assets/dictate.svg`, with the cradle rendering as a clean curve.
- Note "Export" no longer claims success while writing nothing. The packaged
  webview has no file-download path, so it now copies the note as Markdown to
  the clipboard and says so ("Copied as Markdown").

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
