# Microsoft Store Listing Draft

This draft captures public Microsoft Store listing copy and certification notes
for Dictate. Keep claims conservative and aligned with the current app behavior.

## Product Identity

- Preferred Store name: `Arc Forge Dictate`
- Fallback Store name: `Dictate by Arc Forge`
- Publisher: `Arc Forge Labs`
- Product type: `MSIX or PWA app`
- Store ID / product ID: `9P5S7747V0BP`
- Package identity name: `ArcForgeLabs.ArcForgeDictate`
- Package identity publisher: `CN=56989B1A-E9FD-45E0-827B-FDB65D3C9B3C`
- Publisher display name: `Arc Forge Labs`
- Package family name: `ArcForgeLabs.ArcForgeDictate_tbf7er950vsxw`
- Package SID: `S-1-15-2-414942928-860362531-3808921871-2325232450-2546095560-3460849545-2812936032`
- Category: `Productivity`
- Pricing: Free base app. Dictate Pro is the planned handled subscription path
  for hosted/frontier transcription. Do not present switchable hosted API
  backends as the main Store-facing product flow. If Dictate Pro is enabled in
  the Store build, disclose in-app purchases/subscriptions and price ranges in
  Partner Center before submission.
- Discoverability: Managed in Partner Center
- Primary package path: Microsoft Store submission, with GitHub installer
  artifacts kept internal until signed.
- Store MSIX builder: `scripts/build-windows-msix-store.ps1`
- Store MSIX workflow: `.github/workflows/windows-msix-store-bundle.yml`

## Required URLs

- Website: `https://arcforge.au`
- Support URL: `https://github.com/arcforgelabs/dictate/issues`
- Terms URL: `https://arcforge.au/terms`
- Privacy policy URL: `https://arcforge.au/privacy/dictate`

Privacy policy status:

- The dedicated Dictate privacy page must match
  [dictate-privacy-policy.md](dictate-privacy-policy.md) before stable
  submission. It covers local-first use, explicit Dictate Pro sign-in,
  encrypted cloud sync, hosted Pro transcription, device/recovery flows, API key
  storage, logs, analytics, crash reports, support data, export, and deletion.

## Short Description

Push-to-talk desktop dictation that types speech into the app you are already
using.

## Description

Dictate is a desktop push-to-talk dictation app for Windows. It runs from the
system tray, listens while you hold your configured shortcut, transcribes your
speech, and types the result into the currently focused app.

Dictate supports local transcription through Parakeet. Advanced users can
configure supported local and hosted transcription paths through the Dictate
CLI, but the main desktop app keeps the dictation workflow simple: press the
microphone control, dictate, and recover recent text from the local dictations
view.

Dictate Pro, when enabled, adds account sign-in, hosted model access governed by
subscription and usage limits, and optional encrypted cloud sync. Signing in
does not silently upload local dictations. Cloud sync starts only when the user
chooses to sync dictations across devices, and synced dictation content is
encrypted before upload. Hosted Pro transcription is separate from sync and may
send audio to hosted model providers when the user intentionally uses that path.

Dictate is designed for people who want fast text entry without changing their
current workflow. Use it for notes, drafts, forms, messages, and other everyday
typing tasks. Always review important transcriptions before relying on them.

## Product Features

- Push-to-talk dictation from the Windows tray
- Types transcribed text into the focused app
- Local Parakeet transcription option
- Dictate Pro subscription path for handled hosted/frontier transcription and
  encrypted cloud sync when enabled
- Local dictations view for copy/paste recovery
- Explicit sync consent before uploading local dictations
- Encrypted cloud sync for dictation history, notes, transcript segments,
  portable preferences, and synced custom vocabulary
- Export and cloud-deletion controls for Dictate Pro data
- Simple desktop controls with advanced configuration available through the CLI
- API keys stored through the operating system secret store
- Local config, logs, history, and model cache paths

## Keywords

Microsoft Store MSI/EXE keywords are limited to 7 terms and 21 unique words.

- dictation
- speech to text
- transcription
- voice typing
- productivity
- push to talk
- notes

## Copyright And Trademark

Copyright (c) Arc Forge Labs. Dictate and Arc Forge are trademarks or trade
names of Arc Forge Labs where applicable.

## License Terms

Use the repository license for open-source package terms:

- `LICENSE`

Before public Store submission, confirm whether Arc Forge wants additional
commercial terms beyond the MIT license and `https://arcforge.au/terms`. If
Dictate Pro sync or hosted models are enabled, public terms must match
[dictate-pro-terms.md](dictate-pro-terms.md) or a stricter published version.

## Store Assets

Available icons:

- `assets/dictate.png`
- `assets/dictate.ico`
- `assets/dictate-listening.png`
- `assets/dictate-listening.ico`
- `ui-shell/src-tauri/icons/icon.png`
- `ui-shell/src-tauri/icons/icon.ico`

Prepared Store logo upload artifacts:

- `docs/msstore/assets/logos/dictate-store-logo-300.png`
- `docs/msstore/assets/logos/dictate-store-logo-1080.png`
- `docs/msstore/assets/logos/dictate-store-logo-150.png`
- `docs/msstore/assets/logos/dictate-store-logo-71.png`
- `docs/msstore/assets/logos/dictate-store-logo-512.png`
- `docs/msstore/assets/logos/dictate-store-logo-600.png`
- `docs/msstore/assets/logos/dictate-store-logo-1240.png`

Known Store asset follow-up:

- The live Microsoft Store listing is currently showing the old black
  microphone logo. Replace it in Partner Center with the current Dictate app
  identity before the next public listing refresh.

Required before submission:

- 1:1 Store logo / box art
- At least one desktop screenshot
- Prefer four or more screenshots before public launch

Current Partner Center state changes over time. Check Partner Center or
`.github/workflows/msstore-publish-msix.yml` in `mode=status` for live status;
do not rely on committed docs for transient submission state.

Partner Center read-only check on 2026-06-25:

- Product overview URL:
  `https://partner.microsoft.com/en-us/dashboard/products/9P5S7747V0BP/overview`
- Product status shown: `In Microsoft Store`
- Product type shown: `MSIX or PWA app`
- Store presence shown: `Submission 1: Last modified on 06/05/2026`
- An update draft was opened from `Product release` -> `Start update`.
- Current draft shown: `Submission 2`
- Draft submission ID:
  `1152921505701298613`
- Hold this draft until the next app version is bundled, tested, and ready for
  the package upload step.
- Store listing prep completed in draft on 2026-06-25:
  - Updated English (United States) description, release notes, feature bullets,
    and short description.
  - Uploaded four Desktop screenshots.
  - Uploaded square Store logo/display assets for 1:1 box art, 300 x 300 app
    tile, 150 x 150, and 71 x 71.
  - Left package upload and certification submission untouched.
- Live Store URL shown:
  `https://apps.microsoft.com/detail/9P5S7747V0BP`

Suggested screenshots:

1. Ready state: `docs/msstore/assets/screenshots/dictate-01-ready.png`
2. Recording state: `docs/msstore/assets/screenshots/dictate-02-recording.png`
3. Dictations view: `docs/msstore/assets/screenshots/dictate-03-dictations.png`
4. Command palette: `docs/msstore/assets/screenshots/dictate-04-command-palette.png`

Do not include real dictated user text, API keys, email addresses, tokens, or
private workspace names in screenshots.

## Privacy And Data Handling Disclosure

Use this wording as the basis for Partner Center privacy/certification answers:

- Dictate uses the microphone only while the user is actively dictating through
  the configured push-to-talk flow or explicit command.
- Raw microphone audio is processed for transcription and is not intentionally
  retained by Dictate.
- The default local transcription path runs on the user's device after speech
  models are downloaded.
- Advanced users can configure a hosted transcription provider through the CLI;
  if they do, audio for that transcription request is sent to the configured
  provider.
- User-supplied hosted-provider API keys are stored through the operating system
  secret store, not intentionally written to `config.yaml`.
- Dictate Pro, when enabled, is a handled hosted transcription subscription
  rather than a user-facing provider switcher.
- Dictate stores local configuration, logs, downloaded model data, and a small
  recent transcript history on the user's device.
- Users can remove local state using the documented uninstall flags.

## Age Rating Notes

Dictate is a productivity utility and does not intentionally include mature,
violent, sexual, gambling, or user-generated public content. It can transcribe
whatever the user says, so certification answers should distinguish app content
from user-created dictation content.

Recommended age-rating stance:

- Not directed at children under 13.
- No in-app purchases in the current release. If Dictate Pro hosted/frontier
  transcription is added, treat it as an in-app subscription for a digital
  service and update Store listing metadata, price ranges, certification notes,
  and age rating answers before submission. See
  [msstore-in-app-subscriptions.md](msstore-in-app-subscriptions.md).
- No advertising.
- No social network or public content sharing features.
- No location access.
- Microphone access is core functionality.

## Certification Notes

Suggested Partner Center certification note:

```text
Dictate is a desktop productivity utility for push-to-talk dictation. The app
uses microphone input only for user-initiated dictation. The default local
transcription backend runs on-device after model download. Advanced users can
configure hosted transcription through the Dictate CLI; if they do, audio for
that request is sent to the configured provider using the user's own API key,
which is stored with the operating system secret store. Dictate Pro, when
enabled, is the handled hosted transcription subscription path. Dictate does not
intentionally retain raw audio; it stores local settings, logs, downloaded model
data, and a small local recent transcript history for copy/paste recovery.
```

## Submission Checklist

- Product name is reserved in Partner Center as `Arc Forge Dictate`.
- Build MSIX package with `windows-msix-store-bundle.yml`.
- Validate the MSIX package in Partner Center.
- Create a separate MSI/EXE product only if the MSIX package path fails
  validation.
- Complete the draft gates currently shown by Partner Center.
- Confirm `https://arcforge.au/privacy/dictate` is still live.
- Build Store MSIX package from `windows-msix-store-bundle.yml`.
- Test the new bundled version before upload.
- Keep MSI/NSIS artifacts from `windows-desktop-bundle.yml` as the signed
  direct-download fallback only.
- Upload package.
- Store listing prep is already staged in Submission 2:
  - The four clean current-UI screenshots from
    `docs/msstore/assets/screenshots/`.
  - Square Store display assets from `docs/msstore/assets/logos/`.
  - Updated short description, description, feature bullets, and release notes.
- Complete age ratings.
- Complete microphone/privacy certification notes.
- Submit through the manual Partner Center flow or through
  `msstore-publish-msix.yml` after draft review.
- Use Store ID `9P5S7747V0BP` for Store API smoke checks after this workflow is
  available on the default branch.

## Source References

- Microsoft Store MSI/EXE submission checklist: https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/create-app-submission
- Microsoft Store MSI/EXE listing info: https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/add-and-edit-store-listing-info
- Microsoft Store MSIX listing screenshots and images: https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/screenshots-and-images
- Microsoft Store policies: https://learn.microsoft.com/en-us/windows/apps/publish/store-policies
- Microsoft Store in-app subscriptions policy note:
  [msstore-in-app-subscriptions.md](msstore-in-app-subscriptions.md)
- Device capabilities guidance: https://learn.microsoft.com/en-us/windows/apps/develop/devices-sensors/enable-device-capabilities
- Microsoft winapp CLI with Tauri: https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/guides/tauri
- Tauri Microsoft Store guidance: https://v2.tauri.app/distribute/microsoft-store/
