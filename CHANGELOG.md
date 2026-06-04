# Changelog

## 2026-06-04

### Added

- Added Windows desktop packaging support for Dictate, including Tauri MSI/NSIS
  bundle targets and a Windows build script that stages the Python engine before
  bundling.
- Added Microsoft Store MSIX packaging for the reserved Partner Center product
  identity `ArcForgeLabs.ArcForgeDictate`.
- Added Microsoft Store API smoke automation with repository variables for
  non-secret IDs and `MSSTORE_CLIENT_SECRET` stored as a GitHub Actions secret.
- Added Dictate as a first-class Arc Forge ClawSweeper target with a Dictate
  dispatcher workflow for issue, pull request, and command-comment events.
- Added ClawSweeper default-branch fallback handling so dispatches that omit
  `target_branch` resolve the target repository default branch instead of
  assuming `main`.

### Changed

- Moved public install messaging toward Microsoft Store as the primary Windows
  distribution path, with website/GitHub download artifacts treated as a signed
  secondary path.
- Reclassified hosted PowerShell bootstrap instructions as developer/source
  install guidance rather than the normal public Windows install path.
- Preserved the deprecated personal npm package path only as a compatibility
  landing point; new package and install paths use `@arcforgelabs/dictate`.
- Kept Dictate ClawSweeper automation conservative: review/comment only, with
  scheduled/background runs and auto-close policy disabled while the integration
  is being proven.

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

### Notes

- Microsoft Partner Center submission `Submission 1` for `Arc Forge Dictate`
  was manually submitted and was in certification during this work.
- The Microsoft Store product identity is:
  - Store ID: `9P5S7747V0BP`
  - Package identity name: `ArcForgeLabs.ArcForgeDictate`
  - Package family name: `ArcForgeLabs.ArcForgeDictate_tbf7er950vsxw`
- Store submission mutation automation remains intentionally pending until the
  first manual submission is accepted and the package/listing API path is
  confirmed for this MSIX/PWA product.
