# Microsoft Store Listing Draft

This draft is for the first manual Partner Center submission for Dictate. Keep
claims conservative and aligned with the current app behavior.

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
- Manual draft submission: `Submission 1`
- Submission ID: `1152921505701159461`
- Submitted package: `ArcForgeDictate_2026.6.3.0_x64.msix`
- Category: `Productivity`
- Pricing: Free
- Discoverability: Public after certification
- Primary package path: Microsoft Store submission, with GitHub installer
  artifacts kept internal until signed.
- Store MSIX builder: `scripts/build-windows-msix-store.ps1`
- Store MSIX workflow: `.github/workflows/windows-msix-store-bundle.yml`

## Required URLs

- Website: `https://arcforge.au`
- Support URL: `https://github.com/arcforgelabs/dictate/issues`
- Terms URL: `https://arcforge.au/terms`
- Privacy policy URL: `https://arcforge.au/privacy`

Privacy policy status:

- The Arc Forge privacy page is live and covers Dictate microphone/audio
  capture, local transcript history, downloaded speech models, optional hosted
  transcription providers, API key storage, logs, and deletion/removal paths.

## Short Description

Push-to-talk desktop dictation that types speech into the app you are already
using.

## Description

Dictate is a desktop push-to-talk dictation app for Windows. It runs from the
system tray, listens while you hold your configured shortcut, transcribes your
speech, and types the result into the currently focused app.

Dictate supports local transcription through faster-whisper and optional hosted
transcription providers when you choose to configure an API key. The app includes
model selection, push-to-talk controls, startup integration, and a small recent
history view for recovering recent dictated text.

Dictate is designed for people who want fast text entry without changing their
current workflow. Use it for notes, drafts, forms, messages, and other everyday
typing tasks. Always review important transcriptions before relying on them.

## Product Features

- Push-to-talk dictation from the Windows tray
- Types transcribed text into the focused app
- Local faster-whisper transcription option
- Optional OpenAI, xAI, and Gemini provider support when configured by the user
- Recent History for local copy/paste recovery
- Configurable model and hotkey settings
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
commercial terms beyond the MIT license and `https://arcforge.au/terms`.

## Store Assets

Available icons:

- `assets/dictate.png`
- `assets/dictate.ico`
- `assets/dictate-listening.png`
- `assets/dictate-listening.ico`
- `ui-shell/src-tauri/icons/icon.png`
- `ui-shell/src-tauri/icons/icon.ico`

Required before submission:

- 1:1 Store logo / box art
- At least one desktop screenshot
- Prefer four or more screenshots before public launch

Current Partner Center state:

- The first draft listing has one uploaded Desktop screenshot generated from
  the live Vite UI preview at `1400 x 900`.
- The screenshot source used for the draft was
  `/tmp/arc-forge-dictate-store-screenshot-1400x900.png`.
- The package icons are being used for Store logos unless separate art is added
  later.

Suggested screenshots:

1. Settings window with provider/model controls visible.
2. Hotkey/settings view.
3. Recent History view with safe sample text.
4. Tray menu or app running from the Windows taskbar.

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
- If the user selects a hosted transcription provider and configures an API key,
  audio for that transcription request is sent to the selected provider.
- Hosted-provider API keys are stored through the operating system secret store,
  not intentionally written to `config.yaml`.
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
- No in-app purchases.
- No advertising.
- No social network or public content sharing features.
- No location access.
- Microphone access is core functionality.

## Certification Notes

Suggested Partner Center certification note:

```text
Dictate is a desktop productivity utility for push-to-talk dictation. The app
uses microphone input only for user-initiated dictation. The default local
transcription backend runs on-device after model download. If a user explicitly
selects and configures a hosted transcription provider, audio for that request is
sent to the selected provider using the user's own API key. API keys are stored
with the operating system secret store. Dictate does not intentionally retain raw
audio; it stores local settings, logs, downloaded model data, and a small local
recent transcript history for copy/paste recovery.
```

## Submission Checklist

- Product name is reserved in Partner Center as `Arc Forge Dictate`.
- Build MSIX package with `windows-msix-store-bundle.yml`.
- Validate the MSIX package in Partner Center.
- Create a separate MSI/EXE product only if the MSIX package path fails
  validation.
- Complete the `Submission 1` draft gates currently shown by Partner Center.
  Current state on `2026-06-03`:
  - Pricing and availability: complete.
  - Properties: complete.
  - Packages: complete; `ArcForgeDictate_2026.6.3.0_x64.msix` validated.
  - Store listings: complete for English (United States).
  - Submission options: complete, with publishing held until manual `Publish now`.
  - Age ratings: complete; IARC questionnaire and Terms of Use approval saved.
- Confirm privacy policy page is still live.
- Build Store MSIX package from `windows-msix-store-bundle.yml`.
- Keep MSI/NSIS artifacts from `windows-desktop-bundle.yml` as the signed
  direct-download fallback only.
- Upload package.
- Add Store logo / box art.
- Add at least one clean screenshot.
- Add short description, description, features, keywords, support URL, terms URL,
  and privacy policy URL.
- Complete age ratings.
- Complete microphone/privacy certification notes.
- Submit first draft manually.
- Use Store ID `9P5S7747V0BP` for Store API smoke checks after this workflow is
  available on the default branch.

## Source References

- Microsoft Store MSI/EXE submission checklist: https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/create-app-submission
- Microsoft Store MSI/EXE listing info: https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/add-and-edit-store-listing-info
- Microsoft Store policies: https://learn.microsoft.com/en-us/windows/apps/publish/store-policies
- Device capabilities guidance: https://learn.microsoft.com/en-us/windows/apps/develop/devices-sensors/enable-device-capabilities
- Microsoft winapp CLI with Tauri: https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/guides/tauri
- Tauri Microsoft Store guidance: https://v2.tauri.app/distribute/microsoft-store/
