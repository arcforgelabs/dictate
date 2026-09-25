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
Publishing a GitHub release updates the downloadable source and unsigned direct-install artifacts;
it does not make an update available through the Microsoft Store. Store updates
require the Store MSIX workflow in draft mode, Partner Center review, and an
explicit publish/certification step.

The npm package is published as `@arcforgelabs/dictate` and powers the hosted CDN
install/update scripts. Publishing uses GitHub OIDC trusted publishing on the
`npm-publish` environment. Do not dispatch a release until both publishers exist
on the package, each with direct `npm publish` allowed:

| Workflow file | Environment |
| --- | --- |
| `release.yml` | `npm-publish` |
| `npm-unstable.yml` | `npm-publish` |

Repository owner is `arcforgelabs`. Repository name is `dictate`. A long-lived
`NPM_TOKEN` is not used. The June 2026 granular token expired, so `latest`
stayed on `2026.7.4` while the GitHub release moved to `2026.9.25`.

Provenance is off. npm only accepts provenance statements from public source
repositories, and this repository is private. Both publish steps force
`publishConfig.provenance` to `false`, so tags cut before this change still
publish.

The previous personal-scope package, `@iamsamuelrodda/dictate`, is deprecated on npm with a migration notice pointing users to `@arcforgelabs/dictate`. Keep it published as a compatibility landing point for old scripts; do not unpublish it unless there is a specific security or legal reason.

The current developer/bootstrap install path is:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"
```

## Npm Channels

Use npm dist-tags as update channels for the hosted developer/source bootstrap:

| npm dist-tag | Meaning | Publisher |
| --- | --- | --- |
| `latest` | Stable developer bootstrap that points at a reviewed CalVer GitHub release tag. | `.github/workflows/release.yml` |
| `unstable` | Test bootstrap for a selected branch/SHA before it is considered stable. | `.github/workflows/npm-unstable.yml` |

The stable release workflow publishes `@arcforgelabs/dictate@latest` only from a
validated `v20*` release tag reachable from the default branch. Do not publish
feature work to `latest`.

The unstable workflow is manually dispatched. It creates a unique prerelease npm
version such as `2026.7.4-unstable.123.1`, patches the hosted `install.ps1` and
`update.ps1` scripts in the npm package so they download the exact selected
commit archive, and publishes that shim under the requested dist-tag
(`unstable` by default). It does not move GitHub releases, Microsoft Store
drafts, or the stable npm `latest` tag. The app version reported by
`dictate --version` still comes from the selected source commit, so branch builds
without a version bump can report the base CalVer while being delivered through
the unstable channel.

Every unstable publish produces a durable GitHub prerelease containing the matching
unsigned Windows MSI/NSIS installers **and** the Linux `.deb`, because installed
direct builds cannot update from short-lived Actions artifacts. With `run_tests=true`,
the unstable publish waits for the Linux/Windows Python
matrix, the Windows user install/update/uninstall smoke, the Linux user
encrypted-sync install smoke, UI build/server smoke, desktop shell compile/Rust
tests, Linux/Windows desktop bundles, and npm package dry-run. Store upload/publish
remains a separate guarded
workflow. Paid Authenticode signing for direct-download Windows installers is a
future-only lane, not a current release blocker.

### Unstable is upstream of stable

The channels are ordered: everything on `latest` went through `unstable`
first, or a newer build is on `unstable`. A Beta (unstable) user must never
be offered something older than the current stable release. Two mechanisms
keep that true:

1. `release.yml` moves the npm `unstable` dist-tag forward to the stable
   version it just published whenever the unstable pointer is behind it
   (same-base prereleases and newer-base unstable builds are left alone).
2. The app's update check resolves the Beta channel to the newer of the
   `unstable` and `latest` dist-tags, so installed copies get the same
   answer even if the pointer was not moved.

To publish an unstable bootstrap:

```bash
gh workflow run npm-unstable.yml \
  -f source_ref=feature/my-branch \
  -f npm_tag=unstable \
  -f run_tests=true
```

To install or update from the unstable bootstrap:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@unstable/install.ps1 | iex"
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@unstable/update.ps1 | iex"
```

For Linux user installs that update through the in-app/npm path, set:

```bash
dictate config set-update-channel unstable
dictate config set-update-channel stable
```

`stable` is the user-facing name for npm's `latest` dist-tag. `unstable` maps to
the `unstable` dist-tag. `DICTATE_UPDATE_CHANNEL=unstable` remains available for
temporary process-level overrides, but the CLI setting is the supported user
opt-in mechanism.

Promotion rule: once a feature set is locked, tested, and accepted, merge it to
the release branch/default branch, create the normal CalVer tag, run
`.github/workflows/release.yml`, then advance official channels such as
Microsoft Store through their own guarded workflows. Never promote by retagging
an unstable npm package as stable.

Windows has two supported ecosystems. Direct installs may select stable or unstable
and update from the corresponding GitHub release/prerelease installer; these builds
are unsigned and Windows will show the expected untrusted-publisher warning. Microsoft
Store installs are stable-only and update through the Store. Do not revisit paid
Windows signing until there is an explicit revenue-backed decision.

Each Windows payload contains `engine/dictate-distribution.json`. Direct bundles mark
themselves `direct` and include their exact channel package version; Store MSIX bundles
mark themselves `store`. The app uses this marker rather than guessing from Windows.
