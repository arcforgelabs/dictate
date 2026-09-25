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
- Pricing: Free. No in-app purchases, no subscription, no account.
- Discoverability: Managed in Partner Center
- Primary package path: Microsoft Store submission, with GitHub installer
  artifacts kept internal until signed.
- Store MSIX builder: `scripts/build-windows-msix-store.ps1`
- Store MSIX workflow: `.github/workflows/windows-msix-store-bundle.yml`

## Required URLs

- Website: `https://arcforge.au`
- Support URL: `https://github.com/arcforgelabs/dictate/issues`
- Terms URL: `https://arcforge.au/terms/dictate` (source:
  [dictate-terms.md](dictate-terms.md)). Until that page exists, use
  `https://arcforge.au/terms`.
- Privacy policy URL: `https://arcforge.au/privacy/dictate`

Privacy policy status:

- The dedicated Dictate privacy page must match
  [dictate-privacy-policy.md](dictate-privacy-policy.md). As of 2026-09-26 the
  live page still describes Dictate Pro, hosted processing and API keys, which
  no longer exist; it is being replaced.

## Short Description

Hold a key, speak, and your words are typed into the app you are using. Runs
entirely on your PC.

## Description

Dictate is voice typing for Windows that runs entirely on your PC. Hold Right
Ctrl, or click the microphone, speak, and let go: your words are typed into
whatever app you are already using, whether that is an email, a document, a
chat or a form.

Transcription happens on your own machine. Dictate uses the Parakeet speech
model, which ships with the app, so there is nothing to download or set up.
There is no account, no subscription, no API key and no cloud service. Your
audio and your text never leave your computer.

Recent dictations are kept on your PC so you can find, copy or export anything
you said, even if it did not land where you expected.

Dictate is free and open source under the MIT licence.

## Product Features

- Hold Right Ctrl to talk, release to type
- Types into the app you are already using
- Speech recognition runs entirely on your PC (Parakeet)
- Works offline; no account, subscription or API key
- Recent dictations list with search, copy and Markdown export
- Copy last dictation, in case it did not land where you expected
- Free and open source (MIT)

## Release Notes

- Fully local: accounts, subscriptions and online transcription are gone.
  Everything runs on your PC.
- The Parakeet speech model is built in, so dictation works straight after
  install.
- A new, simpler window: click or hold Right Ctrl to dictate, with your recent
  dictations one click away.
- Starts even with no microphone connected, and tells you when one is needed.

## Keywords

Microsoft Store MSI/EXE keywords are limited to 7 terms and 21 unique words.

- dictation
- speech to text
- transcription
- voice typing
- productivity
- push to talk
- offline

## Copyright And Trademark

Copyright (c) Arc Forge Labs. Dictate and Arc Forge are trademarks or trade
names of Arc Forge Labs where applicable.

## License Terms

Use the repository license for open-source package terms:

- `LICENSE`

Dictate is free, local-only software under the MIT license. The Dictate terms
page ([dictate-terms.md](dictate-terms.md)) restates that in plain language;
there are no subscription or purchase terms because there is nothing to buy.

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

The Store shows the logos inside the package when no listing logos are
uploaded. Packages from `2026.9.2503.0` carry the current Dictate mark, which
replaced the old black microphone on the listing.

Required before submission:

- 1:1 Store logo / box art
- At least one desktop screenshot
- Prefer four or more screenshots before public launch

Current Partner Center state changes over time. Check Partner Center or
`.github/workflows/msstore-publish-msix.yml` in `mode=status` for live status;
do not rely on committed docs for transient submission state.

Screenshots (see [msstore/assets/screenshots/README.md](msstore/assets/screenshots/README.md)):

1. `docs/msstore/assets/screenshots/dictate-01-ready.png`
2. `docs/msstore/assets/screenshots/dictate-02-recording.png`
3. `docs/msstore/assets/screenshots/dictate-03-dictations.png`
4. `docs/msstore/assets/screenshots/dictate-04-about.png`

Do not include real dictated user text in screenshots.

## Privacy And Data Handling Disclosure

Use this wording as the basis for Partner Center privacy/certification answers:

- Dictate uses the microphone only while the user is dictating (holding the
  push-to-talk key or after clicking the microphone).
- Speech is transcribed on the device by the bundled Parakeet model. Audio and
  text are never sent anywhere; there is no hosted transcription path.
- There is no account, no sign-in, no API key, no analytics and no crash
  reporting.
- Dictate stores its settings, logs and a recent dictation history on the
  device only. Users can export or delete it, and remove it by uninstalling.
- The only network access is the update check (Microsoft Store installs update
  through the Store).

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
Dictate is a desktop dictation utility. It uses the microphone only while the
user dictates (push-to-talk or the microphone button). Speech is transcribed on
the device by the bundled Parakeet model; audio and text are never sent off the
device. There is no account, sign-in, API key, in-app purchase, analytics or
crash reporting. Dictate stores its settings, logs and a recent dictation
history locally for copy and recovery.
```

## Submission Checklist

- Cut a release and let `windows-release-gate.yml` pass for it.
- `msstore-publish-msix.yml` `mode=draft`: builds the MSIX from `master` and
  uploads it; it refuses without a passing gate for that version.
- Apply this file's short description, description, features, release notes
  and the four screenshots to the draft (see "Updating the listing" in
  [msstore-automation.md](msstore-automation.md)).
- Review the draft in Partner Center, then `mode=publish`.
- Never start a submission by hand in Partner Center; the API cannot touch it.
- Keep Microsoft Store delivery stable-only.

## Source References

- Microsoft Store MSI/EXE submission checklist: https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/create-app-submission
- Microsoft Store MSI/EXE listing info: https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msi/add-and-edit-store-listing-info
- Microsoft Store MSIX listing screenshots and images: https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/screenshots-and-images
- Microsoft Store policies: https://learn.microsoft.com/en-us/windows/apps/publish/store-policies
- Device capabilities guidance: https://learn.microsoft.com/en-us/windows/apps/develop/devices-sensors/enable-device-capabilities
- Microsoft winapp CLI with Tauri: https://learn.microsoft.com/en-us/windows/apps/dev-tools/winapp-cli/guides/tauri
- Tauri Microsoft Store guidance: https://v2.tauri.app/distribute/microsoft-store/
