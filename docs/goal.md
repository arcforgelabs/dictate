# Dictate Windows Release Goal

## Target Outcome

For `~/repos/dictate`, the clean Windows release target should be:

1. Microsoft Store install as the primary public channel.
2. Arc Forge developer identity attached through Partner Center.
3. CI can build a Windows package reproducibly.
4. Store submission can later be automated with the Partner Center app credentials we already created.
5. Direct-download `.exe`/`.msi` remains optional, signed, and clearly secondary.

Microsoft's current guidance is blunt: Store-distributed apps are signed by Microsoft and avoid SmartScreen download warnings. Non-Store `.exe`/`.msi` files can still show SmartScreen warnings on first downloads even when signed, because reputation is tied to publisher and file hash.

## Execution Status

As of 2026-06-04, the repository-side Windows, Store MSIX, Store API smoke, and
ClawSweeper integration work in this goal is implemented and verified on the
current `master` line. The Windows/MSIX package verification ran on the same
code line before this doc-only refresh; the follow-up CI and Secret Scan passed
after the doc refresh.

Completed and verified:

- CI and secret scan passed after the doc refresh.
- Manual Windows desktop bundle workflow passed.
- Manual Store MSIX workflow passed.
- Microsoft Store API smoke workflow passed.
- Dictate/ClawSweeper end-to-end smoke passed against Dictate issue `#8`.

Remaining non-repo gates:

- Microsoft Partner Center certification/publishing for the first Store
  submission.
- A human Windows install/runtime smoke on a real Windows desktop after package
  download.
- Direct-download code signing before `.msi` or `.exe` installers are attached
  to a public GitHub release.
- Future Store package/listing upload automation after the first manual
  submission has completed and the API path is confirmed for the MSIX/PWA
  product.

## Current Repo Status

- Windows Tauri bundle targets are configured for `.msi` and NSIS.
- `scripts/build-windows-desktop.ps1` builds the UI, freezes `dictate-engine.exe`, stages it, and runs Tauri Windows bundling.
- `scripts/build-windows-msix-store.ps1` builds a Store-targeted MSIX loose layout
  with Microsoft `winapp` CLI and the reserved Partner Center package identity.
- Release CI has a `windows-desktop` job for tagged releases.
- Manual CI has `windows-desktop-bundle.yml` for pre-release Windows packaging iteration.
- Manual CI has `windows-msix-store-bundle.yml` for Partner Center MSIX package
  validation.
- Microsoft Store API smoke automation exists in `msstore-api-smoke.yml` and `scripts/msstore-submit.py`.
- Current verification run IDs:
  - CI: `26928859512`, success.
  - Secret Scan: `26928859524`, success.
  - Windows desktop bundle: `26927985488`, success.
  - Windows Store MSIX bundle: `26927986863`, success.
  - Microsoft Store API smoke: `26927988050`, success.
- Current workflow artifact proof:
  - `windows-desktop-bundle` contains
    `Dictate_2026.6.5_x64_en-US.msi` and
    `Dictate_2026.6.5_x64-setup.exe`.
  - `windows-store-msix` contains
    `ArcForgeDictate_2026.6.5.0_x64.msix`.
- GitHub Actions repository variables are set for Store tenant ID, client ID, and seller ID.
- GitHub Actions repository secret `MSSTORE_CLIENT_SECRET` is set from Bitwarden.
- Microsoft Store API token acquisition has been verified locally with the configured credentials.
- Partner Center product is reserved:
  - Product name: `Arc Forge Dictate`
  - Product type: `MSIX or PWA app`
  - Store ID: `9P5S7747V0BP`
  - Package identity name: `ArcForgeLabs.ArcForgeDictate`
  - Package identity publisher: `CN=56989B1A-E9FD-45E0-827B-FDB65D3C9B3C`
  - Publisher display name: `Arc Forge Labs`
  - Package family name: `ArcForgeLabs.ArcForgeDictate_tbf7er950vsxw`
  - Package SID: `S-1-15-2-414942928-860362531-3808921871-2325232450-2546095560-3460849545-2812936032`
- Partner Center manual draft submission exists:
  - Submission: `Submission 1`
  - Submission ID: `1152921505701159461`
  - Last modified: `2026-06-03`
  - Current submission state:
    - Partner Center status: in certification.
    - Certification pipeline stage: pre-processing.
    - Publishing mode: product starts publishing as soon as it passes
      certification.
    - Pricing and availability: complete.
    - Properties: complete.
    - Packages: complete; `ArcForgeDictate_2026.6.3.0_x64.msix` is validated.
    - Store listings: complete for English (United States).
    - Submission options: complete and configured to publish as soon as
      certification passes.
    - Age ratings: complete; IARC questionnaire and Terms of Use approval saved.
- Public GitHub release upload is guarded so unsigned Windows installers become internal artifacts only.
- `docs/msstore-listing.md` contains draft Store listing copy, privacy/certification notes, asset checklist, and submission checklist.
- `https://arcforge.au/privacy` is live and includes Dictate microphone/transcription disclosures.
- Public docs now label the hosted PowerShell bootstrap as developer/source only.
- Remaining external steps: wait for Microsoft certification and automatic
  publishing if it passes, complete a Windows install/runtime smoke, then add
  signing and full package/listing upload automation for future submissions.

## Sources

- Microsoft SmartScreen reputation: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation
- Microsoft code-signing options: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
- Microsoft Store submission API: https://learn.microsoft.com/en-us/windows/apps/publish/store-submission-api
- Store services submissions API: https://learn.microsoft.com/en-us/windows/uwp/monetize/create-and-manage-submissions-using-windows-store-services
- Tauri Windows installer docs: https://v2.tauri.app/distribute/windows-installer/
- Tauri Windows signing docs: https://v2.tauri.app/distribute/sign/windows/
- Tauri Microsoft Store docs: https://v2.tauri.app/distribute/microsoft-store/
- Microsoft winapp CLI with Tauri: https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/guides/tauri

## Phase 1: Make Dictate Buildable As A Windows Desktop App

Status: complete for repository and CI packaging. A human install/runtime smoke
on a real Windows desktop is still a non-repo QA gate.

Implemented changes:

1. Add Windows bundle targets in `ui-shell/src-tauri/tauri.conf.json`.
   - Add `msi` and/or `nsis`.
   - Keep Linux targets intact.
   - Add Windows metadata where useful: publisher, installer name, upgrade code if using MSI.

2. Add a Windows build script.
   - `scripts/build-windows-desktop.ps1`.
   - Build frontend.
   - Build the Python engine with PyInstaller on Windows.
   - Stage `dictate-engine.exe` into `ui-shell/src-tauri/engine/`.
   - Run `tauri build --bundles msi,nsis` or equivalent.

3. Add a Store MSIX build script.
   - Use `tauri build --no-bundle`.
   - Stage `dictate-ui-shell.exe` and `engine\dictate-engine.exe`.
   - Render the Partner Center package identity into `Package.appxmanifest`.
   - Pack with Microsoft `winapp` CLI.

4. Confirm the Tauri shell launches the Windows engine correctly.
   - Check path resolution for `.exe`.
   - Make sure process spawn works on Windows.
   - Make sure microphone/audio access behavior is sane.

Acceptance:

- On `windows-latest`, CI produces at least one installable Windows artifact:
  complete, verified by workflow run `26927985488`.
- On `windows-latest`, CI can produce a Store-targeted `.msix` artifact for the
  reserved Partner Center product: complete, verified by workflow run
  `26927986863`.
- Local/manual Windows install opens the app and can start the backend engine:
  pending human QA on a Windows desktop.

## Phase 2: Create A Store-Compatible Package Strategy

Status: complete for the first Store submission strategy and repository package
builder. The first Partner Center submission remains outside the repo while
Microsoft certification is in progress.

There are two practical Microsoft Store routes:

1. MSIX Store package

   Best for clean install UX and Store-managed signing.

2. MSI/EXE Store submission

   Microsoft now has Store submission docs for MSI/EXE apps, but this path is different from classic packaged MSIX. It may be easier if Tauri's MSI/NSIS output is already good, but we need to check Partner Center product type constraints when creating the Dictate app listing.

Recommended first target: MSIX if feasible, because it aligns best with "official Store app, no warning flags".

Steps:

1. Reserve the app name in Partner Center. Complete.
   - Product name: `Arc Forge Dictate`.
   - Publisher: Arc Forge Labs / Arc Forge developer account.
   - This must be done in Partner Center first; API cannot create the initial app record.

2. Create the first submission manually. Complete; `Submission 1` is in
   certification.
   - Microsoft's older Store submission API requires the first submission and age ratings to be completed in Partner Center before future API submissions.
   - This also avoids getting blocked by listing/compliance questions.
   - `Submission 1` exists in Partner Center and has been completed manually.

3. Prepare Store assets. Complete for the first submitted listing; screenshots
   and package/listing assets should still be refreshed for future submissions.
   - App icon.
   - Screenshots.
   - Description.
   - Short description.
   - Privacy policy URL.
   - Support URL.
   - Microphone/audio permission disclosure.
   - Any local transcription/privacy claims must be accurate.

Acceptance:

- Dictate exists as a product in Partner Center.
- First draft submission reaches a state where package upload/listing validation can run.
- Current first draft package/listing validation and age rating are complete;
  the first Store submission is now in certification.

## Phase 3: Signing Strategy

Status: complete for Store distribution strategy and public-release guardrails.
Direct-download signing implementation remains pending.

For Store distribution:

1. Let Microsoft sign the Store-distributed package after certification.
2. Use local/test signing only for internal install testing if needed.
3. Do not buy EV solely to avoid SmartScreen. Microsoft says EV no longer gives instant SmartScreen bypass for new files.

For direct download fallback:

1. Use Azure Artifact Signing / Trusted Signing or OV code signing.
2. Sign every `.exe`, `.msi`, and bundled binary.
3. Expect early SmartScreen warnings anyway until reputation builds.
4. Use the exact same publisher identity consistently.

Acceptance:

- Store users get the clean path: pending Microsoft certification/publishing.
- Direct-download users see a verified publisher even if SmartScreen reputation
  is still warming up: pending signing provider and signing workflow.
- Unsigned Windows artifacts are not attached to public GitHub releases:
  complete, guarded by `scripts/assert-windows-artifacts-signed.ps1` and the
  `windows-desktop` release job.

## Phase 4: GitHub Actions Release Pipeline

Status: complete for build jobs and unsigned-artifact protection. Public release
upload of Windows artifacts intentionally waits for signing.

Target workflow:

1. `windows-latest`
2. Install:
   - Rust
   - Node/pnpm/npm as repo requires
   - Python
   - Tauri CLI dependencies
   - WiX if using MSI
   - NSIS if using NSIS
   - PyInstaller

3. Build Python engine.
4. Stage `dictate-engine.exe`.
5. Build Tauri Windows bundle.
6. Upload artifacts:
   - `.msi`
   - `.exe` installer if NSIS
   - logs/checksums

7. Later: add signing step.
8. Later: add Store submission step.

Acceptance:

- GitHub release contains Windows artifacts: pending signing; unsigned artifacts
  are uploaded only as internal workflow artifacts.
- Artifact names are stable and versioned: complete, verified by workflow run
  `26927985488`.
- No secrets are printed in logs: complete for current workflows; CI and Secret
  Scan passed on the current doc refresh.

## Phase 5: Programmatic Store Submission

Status: complete for credential wiring and read-only smoke. Mutating submission
automation remains pending until the first manual submission is finished.

We already created the required Microsoft side pieces:

- Seller ID: `94852860`
- Tenant ID: `040ca04b-6b25-40a6-8b72-385e983e33af`
- Client ID: `1b26108f-d69b-4229-8282-c6fb937b4c03`
- Partner Center app role: `Manager(Windows)`
- Secrets stored in Bitwarden, not repo.

Implemented automation:

1. Store the non-secret IDs in GitHub Actions variables or repo config:
   complete.
2. Store the client secret in GitHub Actions secrets: complete.
3. Add a small submit script: complete with `scripts/msstore-submit.py`.

4. Token flow: complete for read-only smoke.
   - Use Entra client credentials.
   - Use the Store/Partner Center API resource expected by the chosen API path.

5. Submission flow: guarded and intentionally not used for the in-certification
   manual submission.
   - Get product/current draft.
   - Upload package or update draft metadata.
   - Validate.
   - Submit.

6. Keep manual/Partner Center edits separate from API-created submissions:
   active rule. Microsoft warns that mixing API and manual edits on the same
   API-created submission can break the submission state.

Acceptance:

- CI can authenticate to Microsoft Store API without exposing secrets:
  complete, verified by workflow run `26927988050`.
- CI can query the Dictate product: complete through the legacy MSIX/UWP Store
  services API, verified by workflow run `26927988050`.
- Later CI can create/submit a package update: pending after first manual
  submission is accepted and API path is confirmed.

## Dictate / ClawSweeper Integration Goal

### ClawSweeper Target Outcome

`arcforgelabs/dictate` should be a first-class ClawSweeper target while remaining
an open-source public app repository. The ClawSweeper implementation itself stays
private in `arcforgelabs/clawsweeper`, with Arc Forge-specific personalization
kept in config, docs, and workflow defaults rather than pushed upstream.

The integration target is:

1. Dictate is listed as an explicit ClawSweeper target.
2. The Arc Forge ClawSweeper GitHub App can read and comment on Dictate.
3. Dictate dispatches issue, PR, and command-comment events to
   `arcforgelabs/clawsweeper`.
4. Dictate dispatches always identify the target branch as `master`.
5. ClawSweeper can also recover safely when a dispatch omits `target_branch` by
   resolving the target repository's default branch.
6. ClawSweeper writes durable review state into the private
   `arcforgelabs/clawsweeper-state` repository.
7. ClawSweeper posts or updates one durable review comment on the Dictate issue
   or PR.
8. Automation remains conservative for Dictate: review/comment only, no
   automatic issue or PR closing while the integration is being proven.

### ClawSweeper Current Repo Status

- `arcforgelabs/dictate` is public and uses `master` as its default branch.
- `arcforgelabs/clawsweeper` is private and uses `main` as its default branch.
- Dictate has `.github/workflows/clawsweeper-dispatch.yml`.
- The dispatcher sends events to `arcforgelabs/clawsweeper`, not upstream
  OpenClaw infrastructure.
- The dispatcher sets:
  - `CLAWSWEEPER_DISPATCH_REPO=arcforgelabs/clawsweeper`
  - `TARGET_BRANCH=master`
  - fallback App client ID `Iv23li0ZukB8Rb86dvTp`
- Dictate GitHub Actions secret `CLAWSWEEPER_APP_PRIVATE_KEY` is configured.
- Dictate GitHub Actions variable `CLAWSWEEPER_APP_CLIENT_ID` is configured as
  `Iv23li0ZukB8Rb86dvTp`.
- The ClawSweeper receiver preserves `target_branch` through comment-router
  re-review dispatches.
- The ClawSweeper sweep workflow resolves the target repository default branch
  when a dispatch omits `target_branch`, avoiding hardcoded `main` failures for
  Dictate.
- ClawSweeper scheduled/background runs remain disabled with
  `CLAWSWEEPER_ENABLE_SCHEDULES=0` while manual smokes are the control surface.

### ClawSweeper Implemented Changes

Dictate:

- Added `.github/workflows/clawsweeper-dispatch.yml`.
- Fixed the ClawSweeper App client ID used by the dispatcher.
- Kept the workflow safe for `pull_request_target`: it does not checkout or run
  untrusted PR code; it only creates GitHub App tokens and dispatches events.

ClawSweeper:

- Added `arcforgelabs/dictate` to the Arc Forge target list.
- Preserved `target_branch` in comment-router follow-on dispatches.
- Added validation for comment-router target branch overrides.
- Changed both exact-item and normal sweep checkout paths to resolve the target
  repository default branch when `target_branch` is omitted.
- Added regression tests for target branch preservation and default branch
  resolution.

### ClawSweeper Verification

Local verification in `~/repos/clawsweeper`:

- `pnpm run build:all`
- `node --test test/repair/config.test.ts test/repair/comment-router-core.test.ts test/clawsweeper.test.ts`
- Result: 362 tests passed.

GitHub Actions verification:

- Dictate dispatcher run succeeded from a Dictate issue comment.
- ClawSweeper `repair comment router` run succeeded on current ClawSweeper
  commit `3a52455594`.
- ClawSweeper exact review run `26925824791` succeeded on
  `arcforgelabs/dictate#8`.
- That run completed:
  - target branch resolution
  - target read token creation
  - target write token creation
  - Dictate checkout
  - exact item review
  - private state setup
  - event result publish and safe-close application gate
  - synced verdict routing
  - command-router ledger commit
  - target completion reaction
- Dictate issue `#8` remained open and received an updated durable ClawSweeper
  review comment at `2026-06-04 02:16 UTC`.

Earlier smoke runs exposed two integration bugs and are intentionally retained as
evidence:

- A stale App client ID caused token creation failure.
- A hardcoded `main` fallback caused Dictate checkout failure.

Both were fixed before the final successful smoke.

### ClawSweeper Security And Boundary Notes

- The ClawSweeper GitHub App private key is not committed to the repo.
- The key is stored as a GitHub Actions secret, and the Bitwarden-held PEM was
  only piped into `gh secret set`.
- Dictate remains public; ClawSweeper and ClawSweeper state remain private.
- The dispatcher uses GitHub App tokens with scoped repository access.
- New ClawSweeper personalization should stay in Arc Forge config, workflow
  defaults, target policy, and docs.
- Upstream OpenClaw improvements should be pulled into a review branch, then
  ported selectively into the private Arc Forge fork.
- Arc Forge-specific behavior should not be contributed upstream unless it is
  generalized first.

### ClawSweeper Operating Plan

1. Keep `CLAWSWEEPER_ENABLE_SCHEDULES=0` until at least several manual Dictate
   smokes pass without branch, credential, or state-sync regressions.
2. Use Dictate issue or PR comments such as `@clawsweeper review` for manual
   integration checks.
3. Treat a successful end-to-end smoke as requiring all of:
   - Dictate dispatcher success.
   - Private ClawSweeper receiver success.
   - Dictate checkout success.
   - Private state write success.
   - Durable Dictate review comment update.
4. Do not enable auto-close for Dictate until the review/comment path has proven
   stable and the close policy has been reviewed separately.
5. Review ClawSweeper target policy before enabling scheduled fanout for Dictate.

## Phase 6: Product Readiness Checks

Status: mostly complete for repository and first-submission readiness. The open
items are Windows runtime QA, Microsoft certification, and direct-download
signing.

Readiness state:

1. Installer identity:
   - App name is stable.
   - Publisher is Arc Forge.
   - Version format is Store-compatible.
   - Status: complete for Store MSIX and current Windows artifacts.

2. Privacy/compliance:
   - Privacy policy covers microphone/audio handling.
   - If audio stays local, say that accurately.
   - If any model/API/cloud transcription is used, disclose it.
   - Status: complete for first Store submission; keep refreshed as model/API
     behavior changes.

3. Runtime:
   - WebView2 handling is correct.
   - Python engine is bundled, not downloaded at install time.
   - No dev install commands in the public user path.
   - Status: package build complete; human Windows runtime smoke pending.

4. Security:
   - No secrets in packaged files.
   - No unsigned helper executables for direct-download path.
   - No `ExecutionPolicy Bypass | iwr | iex` public install path.
   - Status: CI and Secret Scan passed; public release upload is guarded for
     unsigned Windows installers.

5. UX:
   - One-click install.
   - Normal uninstall entry.
   - First run does not require terminal.
   - App handles missing microphone permission cleanly.
   - Status: package path ready; real Windows desktop smoke pending.

## Recommended Order

Completed:

1. Implement Windows Tauri packaging in `dictate`.
2. Add Windows CI artifact build.
3. Reserve Dictate in Partner Center.
4. Create first manual Store submission.
5. Run and validate MSIX package generation for the reserved MSIX/PWA product.
6. Move old PowerShell install instructions into "developer install only".
7. Add read-only Store API smoke automation.
8. Add Dictate/ClawSweeper integration and verify it end to end.

Remaining:

1. Wait for Microsoft certification and automatic Store publishing.
2. Run a real Windows install/runtime smoke from the produced `.msi`, `.exe`, or
   Store package.
3. Add signing for direct-download artifacts.
4. Add mutating Store package/listing upload automation after the first manual
   submission is accepted.
5. Revisit whether a separate MSI/EXE Store product is useful only if the MSIX
   path fails or cannot meet the product requirements.

The key decision is this: if the goal is "no weird Windows warning flags for normal users," Microsoft Store should be the primary release path. Signed website downloads are still worth doing, but they cannot guarantee a clean first-download SmartScreen experience.
