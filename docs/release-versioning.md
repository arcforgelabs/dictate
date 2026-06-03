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

Release tags and GitHub milestones should use the public version with a leading `v`, for example:

```text
v2026.5.18
v2026.5.18-1
```

Pushing a `v20*` tag is the only deployment trigger. The release workflow runs the Linux/Windows test matrix, the hosted Windows user install smoke test, release metadata validation, Python artifact checks, and npm package validation before publishing.

The npm package is published as `@arcforgelabs/dictate` and powers the hosted CDN install/update scripts. Configure npm trusted publishing for this repository and `.github/workflows/release.yml`, or add a granular `NPM_TOKEN` repository secret with publish rights. Do not push a release tag until that npm publisher path is ready.

The previous personal-scope package, `@iamsamuelrodda/dictate`, should remain available long enough for existing users to update. After the first `@arcforgelabs/dictate` package is visible on npm and the hosted install smoke passes, deprecate the personal package with a migration notice pointing users to `@arcforgelabs/dictate`.

The current developer/bootstrap install path is:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"
```

Do not present this as the normal public Windows install path. The Windows
release target is Microsoft Store distribution, with signed direct-download
artifacts only as a secondary fallback.
