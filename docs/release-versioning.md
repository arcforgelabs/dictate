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

The app reports the public release version through:

```bash
dictate --version
```

Generate versions with:

```bash
python scripts/calver.py --date 2026-05-18
python scripts/calver.py --date 2026-05-18 --format pep440
```

Release tags and GitHub milestones should use the public version with a leading `v`, for example:

```text
v2026.5.18
```

Pushing a `v20*` tag is the only deployment trigger. The release workflow runs the Linux/Windows test matrix, the hosted Windows user install smoke test, release metadata validation, Python artifact checks, and npm package validation before publishing.

The npm package is published as `@iamsamuelrodda/dictate`. Configure npm trusted publishing for this repository and `.github/workflows/release.yml`, or add a granular `NPM_TOKEN` repository secret with publish rights. Do not push a release tag until that npm publisher path is ready; the CDN one-liner uses the package published to npm.
