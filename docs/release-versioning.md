# Release Versioning

Dictate uses calendar versioning for public releases:

```text
YYYY.M.D
```

The release version is the calendar date of the release without zero-padding month or day. A release on May 18, 2026 is:

```text
2026.5.18
```

Python package metadata uses the same PEP 440-compatible version:

```text
2026.5.18
```

If a same-day replacement package is needed because an immutable package
registry already has `YYYY.M.D`, append a small patch sequence:

```text
2026.5.18-1
```

The app reports the public release version through:

```bash
dictate --version
```

Generate versions with:

```bash
python scripts/calver.py --date 2026-05-18
python scripts/calver.py --date 2026-05-18 --sequence 1
python scripts/calver.py --date 2026-05-18 --format pep440
```

Synchronize release metadata before tagging with:

```bash
python scripts/sync_release_version.py --date 2026-05-18
python scripts/sync_release_version.py --date 2026-05-18 --sequence 1
python scripts/sync_release_version.py 2026.5.18 --check
```

Release tags and GitHub milestones should use the public version with a leading `v`, for example:

```text
v2026.5.18
v2026.5.18-1
```

Windows MSI installers cannot use the public CalVer string directly because
WiX/MSI requires numeric `major.minor.patch[.build]`, with major and minor at
most 255. Keep `tauri.conf.json`'s public app `version` as `YYYY.M.D[-N]`, but
map `bundle.windows.wix.version` to `YY.M.D.N` for MSI packaging:

```text
2026.6.4   -> 26.6.4.0
2026.6.4-1 -> 26.6.4.1
```

After creating a `v20*` CalVer tag on a commit that has reached the default
branch, start `.github/workflows/release.yml` manually with the `release_tag`
input. The release workflow first verifies that the requested tag resolves to a
commit reachable from the default branch, then runs the Linux/Windows test
matrix, the hosted Windows user install smoke test, release metadata validation,
Python artifact checks, and npm package validation before publishing.

GitHub release publication and Microsoft Store publication are separate lanes.
Publishing a GitHub release updates the downloadable source/developer artifacts;
it does not make an update available through the Microsoft Store. Store updates
require the Store MSIX workflow in draft mode, Partner Center review, and an
explicit publish/certification step.

The npm package is published as `@arcforgelabs/dictate` and powers the hosted CDN
install/update scripts. Configure npm trusted publishing for this repository and
`.github/workflows/release.yml`, or add a granular `NPM_TOKEN` repository secret
with publish rights. Do not dispatch the release workflow for a tag until that
npm publisher path is ready.

The previous personal-scope package, `@iamsamuelrodda/dictate`, is deprecated on npm with a migration notice pointing users to `@arcforgelabs/dictate`. Keep it published as a compatibility landing point for old scripts; do not unpublish it unless there is a specific security or legal reason.

The current developer/bootstrap install path is:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"
```

Do not present this as the normal public Windows install path. The Windows
release target is Microsoft Store distribution, with signed direct-download
artifacts only as a secondary fallback.
