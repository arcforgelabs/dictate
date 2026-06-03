# Dictate Windows Release Goal

## Target Outcome

For `~/repos/dictate`, the clean Windows release target should be:

1. Microsoft Store install as the primary public channel.
2. Arc Forge developer identity attached through Partner Center.
3. CI can build a Windows package reproducibly.
4. Store submission can later be automated with the Partner Center app credentials we already created.
5. Direct-download `.exe`/`.msi` remains optional, signed, and clearly secondary.

Microsoft's current guidance is blunt: Store-distributed apps are signed by Microsoft and avoid SmartScreen download warnings. Non-Store `.exe`/`.msi` files can still show SmartScreen warnings on first downloads even when signed, because reputation is tied to publisher and file hash.

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
  publishing if it passes, then add signing and full package/listing upload
  automation for future submissions.

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

Current issue: `dictate` only targets Linux bundles in Tauri.

Target changes:

1. Add Windows bundle targets in `ui-shell/src-tauri/tauri.conf.json`.
   - Add `msi` and/or `nsis`.
   - Keep Linux targets intact.
   - Add Windows metadata where useful: publisher, installer name, upgrade code if using MSI.

2. Add a Windows build script.
   - Likely `scripts/build-windows-desktop.ps1`.
   - Build frontend.
   - Build the Python engine with PyInstaller on Windows.
   - Stage `dictate-engine.exe` into `ui-shell/src-tauri/engine/`.
   - Run `tauri build --bundles msi,nsis` or equivalent.

4. Add a Store MSIX build script.
   - Use `tauri build --no-bundle`.
   - Stage `dictate-ui-shell.exe` and `engine\dictate-engine.exe`.
   - Render the Partner Center package identity into `Package.appxmanifest`.
   - Pack with Microsoft `winapp` CLI.

3. Confirm the Tauri shell launches the Windows engine correctly.
   - Check path resolution for `.exe`.
   - Make sure process spawn works on Windows.
   - Make sure microphone/audio access behavior is sane.

Acceptance:

- On `windows-latest`, CI produces at least one installable Windows artifact.
- On `windows-latest`, CI can produce a Store-targeted `.msix` artifact for the
  reserved Partner Center product.
- Local/manual Windows install opens the app and can start the backend engine.

## Phase 2: Create A Store-Compatible Package Strategy

There are two practical Microsoft Store routes:

1. MSIX Store package

   Best for clean install UX and Store-managed signing.

2. MSI/EXE Store submission

   Microsoft now has Store submission docs for MSI/EXE apps, but this path is different from classic packaged MSIX. It may be easier if Tauri's MSI/NSIS output is already good, but we need to check Partner Center product type constraints when creating the Dictate app listing.

Recommended first target: MSIX if feasible, because it aligns best with "official Store app, no warning flags".

Steps:

1. Reserve the app name in Partner Center.
   - Product name: `Arc Forge Dictate`.
   - Publisher: Arc Forge Labs / Arc Forge developer account.
   - This must be done in Partner Center first; API cannot create the initial app record.

2. Create the first submission manually.
   - Microsoft's older Store submission API requires the first submission and age ratings to be completed in Partner Center before future API submissions.
   - This also avoids getting blocked by listing/compliance questions.
   - `Submission 1` now exists in Partner Center and must be completed manually.

3. Prepare Store assets.
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

- Store users get the clean path.
- Direct-download users see a verified publisher even if SmartScreen reputation is still warming up.

## Phase 4: GitHub Actions Release Pipeline

Add a Windows release job beside the existing Linux job.

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

- GitHub release contains Windows artifacts.
- Artifact names are stable and versioned.
- No secrets are printed in logs.

## Phase 5: Programmatic Store Submission

We already created the required Microsoft side pieces:

- Seller ID: `94852860`
- Tenant ID: `040ca04b-6b25-40a6-8b72-385e983e33af`
- Client ID: `1b26108f-d69b-4229-8282-c6fb937b4c03`
- Partner Center app role: `Manager(Windows)`
- Secrets stored in Bitwarden, not repo.

Next steps:

1. Store the non-secret IDs in GitHub Actions variables or repo config.
2. Store the client secret in GitHub Actions secrets.
3. Add a small submit script, probably:
   - `scripts/msstore-submit.ps1` or
   - `scripts/msstore-submit.py`

4. Token flow:
   - Use Entra client credentials.
   - Use the Store/Partner Center API resource expected by the chosen API path.

5. Submission flow:
   - Get product/current draft.
   - Upload package or update draft metadata.
   - Validate.
   - Submit.

6. Keep manual/Partner Center edits separate from API-created submissions. Microsoft warns that mixing API and manual edits on the same API-created submission can break the submission state.

Acceptance:

- CI can authenticate to Microsoft Store API without exposing secrets.
- CI can query the Dictate product.
- Later CI can create/submit a package update.

## Phase 6: Product Readiness Checks

Before public submission:

1. Installer identity:
   - App name is stable.
   - Publisher is Arc Forge.
   - Version format is Store-compatible.

2. Privacy/compliance:
   - Privacy policy covers microphone/audio handling.
   - If audio stays local, say that accurately.
   - If any model/API/cloud transcription is used, disclose it.

3. Runtime:
   - WebView2 handling is correct.
   - Python engine is bundled, not downloaded at install time.
   - No dev install commands in the public user path.

4. Security:
   - No secrets in packaged files.
   - No unsigned helper executables for direct-download path.
   - No `ExecutionPolicy Bypass | iwr | iex` public install path.

5. UX:
   - One-click install.
   - Normal uninstall entry.
   - First run does not require terminal.
   - App handles missing microphone permission cleanly.

## Recommended Order

1. Implement Windows Tauri packaging in `dictate`.
2. Add Windows CI artifact build.
3. Reserve Dictate in Partner Center.
4. Create first manual Store submission.
5. Run and validate the MSIX package for the reserved MSIX/PWA product; create a
   separate MSI/EXE Store product only if that path fails.
6. Add signing for direct-download artifacts.
7. Add Store API automation after first manual submission is accepted.
8. Move old PowerShell install instructions into "developer install only".

The key decision is this: if the goal is "no weird Windows warning flags for normal users," Microsoft Store should be the primary release path. Signed website downloads are still worth doing, but they cannot guarantee a clean first-download SmartScreen experience.
