# Release Versioning

> The release policy (stable, beta and dev channels; corrections and betas;
> the release workflows) is [RELEASING.md](RELEASING.md). This page is the
> procedure releases follow. The work is tracked in
> [#145](https://github.com/arcforgelabs/dictate/issues/145).

Dictate uses calendar versioning for public releases:

```text
YYYY.M.N            stable release
YYYY.M.N-beta.B     beta: a pre-release of the upcoming YYYY.M.N
YYYY.M.N-C          correction: a repackage of the stable YYYY.M.N
```

- `YYYY.M` is the month the release is cut in (UTC), without zero-padding.
- `N` is the release count in that month. It is not the day.
- `N` is the highest stable `N` already tagged in that month, plus 1. The
  first release of a month is `1`. `N` can be more than 31. Betas do not
  count.
- `B` counts the betas of one base from 1. `C` counts the corrections of one
  stable release from 1.
- Releases before 2026.10.1 used the day as `N`. Do not change those tags.
  The count continues from the highest one in the month.

For example, after `2026.10.20` comes `2026.10.21`, after `2026.10.31` comes
`2026.10.32`, and the first release of November is `2026.11.1`. Sort stable
versions as numbers, part by part, never as text: as text, `2026.10.9` comes
after `2026.10.32`.

Order betas and corrections in PEP 440 order, never in npm's semver order:

```text
2026.10.1-beta.1 < 2026.10.1-beta.2 < 2026.10.1 < 2026.10.1-1 < 2026.10.2-beta.1
```

Python package metadata uses the same version. PEP 440 reads `-beta.2` as
`b2` and `-1` as `.post1`.

Older releases sometimes added a correction `-K` (for example `2026.9.25-1`)
when an immutable package registry already had the version. A correction
now repackages the same code. New code gets the next `N`.

The app reports the public release version through:

```bash
dictate --version
```

Print the next version, or check one, with (fetch the tags first):

```bash
git fetch --tags
python scripts/calver.py next
python scripts/calver.py next --today 2026-10-20
python scripts/calver.py next --channel beta --base 2026.10.3
python scripts/calver.py check 2026.10.3
python scripts/calver.py check 2026.10.3-beta.2
python scripts/calver.py plan --channel beta --base 2026.10.3
python scripts/calver.py newest 2026.10.3-beta.2 2026.10.3-1
```

`plan` prints the tag, version, channel and npm dist-tag as JSON. Dictate
Release Prepare uses it. It refuses a beta or stable release whose base is
not the next release this month, and a correction of a release that is not
the latest one this month.

Synchronize release metadata with:

```bash
python scripts/sync_release_version.py            # the next stable version
python scripts/sync_release_version.py 2026.10.3  # must be the next version
python scripts/sync_release_version.py 2026.10.3 --check
python scripts/sync_release_version.py 2026.10.3-beta.1 --stamp
```

When it writes, `sync_release_version.py` refuses a version that is not the
next release of its kind (`--today` sets the date for a test). `--check` only
compares the files with the version, so it works for any released version.
`--stamp` writes any valid version without that check. The release build
jobs use it to stamp a beta or correction onto the tagged commit, in the job
only.

The version files on `master` hold the upcoming stable version, for example
`2026.10.3`. Its betas and the stable release are tagged from commits that
hold it. A correction is tagged from a commit that holds the version it
corrects, normally the release's own commit.

Release tags and GitHub milestones use the public version with a leading
`v`, for example:

```text
v2026.10.3
v2026.10.3-beta.1
v2026.10.32
```

## Windows MSI version

Windows MSI installers cannot use the public CalVer string directly because
WiX/MSI requires numeric `major.minor.patch[.build]`, with major and minor at
most 255. Keep `tauri.conf.json`'s public app `version` as the public
version, but map `bundle.windows.wix.version` to `YY.M.N.C` for MSI
packaging:

```text
2026.10.3         -> 26.10.3.0
2026.10.32        -> 26.10.32.0
2026.10.3-beta.2  -> 26.10.3.0
2026.9.25-1       -> 26.9.25.1
```

A beta takes its final's MSI version. Windows Installer compares only the
first three fields, so a correction compares equal to its final too. The
in-app updater on Windows runs the NSIS installer, not the MSI.
[RELEASING.md](RELEASING.md#version-order) describes the target mapping.

## Publishing a release

Use the `dictate-*` workflows ([RELEASING.md](RELEASING.md#the-workflows)).
Start a beta from `master`:

```bash
gh workflow run dictate-release-prepare.yml --repo arcforgelabs/dictate --ref master -f channel=beta
```

Start a stable release with `-f channel=stable`, and a correction with
`-f channel=correction -f commit=<the release's commit>`.

Dictate Release Prepare requires CI to have passed on the commit, tags it,
and starts Dictate Release Publish. Publish runs Dictate Release Checks: the
Linux/Windows test matrix, the hosted Windows user install smoke, the UI and
desktop shell checks, release metadata validation, Python artifact checks,
the npm package, the `.deb`, and the MSI and NSIS installers. Then it creates
the GitHub release as a draft and starts Dictate NPM Release, which publishes
to npm and makes the release public.

The `release` environment needs Samuel's approval for a stable release or
correction, so the Publish run waits until approved. A beta runs in
`release-beta`, which has no reviewer. After a stable release or correction
is public, Dictate NPM Release starts `windows-release-gate.yml`. The gate
installs that exact `setup.exe` on the `win11-gpu` VM, launches it, checks
the running engine's version, and uninstalls. See
[windows-11.md](windows-11.md#release-gate).

`release.yml` and `npm-unstable.yml` are replaced by the `dictate-*`
workflows. They stay until the 2026.10.3 beta has shipped through
`npm-unstable.yml`.

GitHub release publication and Microsoft Store publication are separate lanes.
Publishing a GitHub release updates the downloadable source and unsigned direct-install artifacts;
it does not make an update available through the Microsoft Store. Store updates
require the Store MSIX workflow in draft mode, Partner Center review, and an
explicit publish/certification step. The draft refuses to build without a
passing Windows release gate for the same version; `skip_windows_gate` is the
override. Store packages are stable only.

## npm

The npm package is published as `@arcforgelabs/dictate` and powers the hosted CDN
install/update scripts. Publishing uses GitHub OIDC trusted publishing. Do
not dispatch a release until these trusted publishers exist on the package
([RELEASING.md](RELEASING.md#one-time-setup)):

| Workflow file | Environment | Allowed to |
| --- | --- | --- |
| `dictate-npm-release.yml` | `npm-publish` | publish |
| `dictate-release-promote.yml` | `npm-release` | move dist-tags (**Allow npm dist-tag**), not publish |
| `npm-unstable.yml` | `npm-publish` | publish, until it is retired |
| `release.yml` | `npm-publish` | publish, until it is retired |

Repository owner is `arcforgelabs`. Repository name is `dictate`. A long-lived
`NPM_TOKEN` is not used. Moving a dist-tag through trusted publishing needs
npm 11.21.0 or later; both workflows install it.

Provenance is off. npm only accepts provenance statements from public source
repositories, and the repository was private when trusted publishing was set up.
The publish steps force `publishConfig.provenance` to `false`. The
repository is public now, so provenance can be turned back on by removing
that override and setting `publishConfig.provenance` to `true`.

The previous personal-scope package, `@iamsamuelrodda/dictate`, is deprecated on npm with a migration notice pointing users to `@arcforgelabs/dictate`. Keep it published as a compatibility landing point for old scripts; do not unpublish it unless there is a specific security or legal reason.

The current developer/bootstrap install path is:

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr -useb https://cdn.jsdelivr.net/npm/@arcforgelabs/dictate@latest/install.ps1 | iex"
```

## Npm Channels

npm dist-tags are the update channels:

| npm dist-tag | Meaning | Publisher |
| --- | --- | --- |
| `latest` | Stable: a stable release or a correction. | `dictate-npm-release.yml` (`release.yml` before it) |
| `beta` | Beta: a beta, or a stable release that Promote moved up. | `dictate-npm-release.yml`, `dictate-release-promote.yml` |
| `unstable` | The old beta lane: a selected branch or SHA. | `npm-unstable.yml`, until it is retired |

Every publish names its dist-tag with `--tag`. npm never picks it, because
npm's semver order ranks a correction below its final.

### Beta is never behind stable

A beta user must never be offered something older than the current stable
release. Two things keep that true:

1. After a stable release, Dictate Release Promote moves `beta` up to it when
   `beta` is older in PEP 440 order.
2. The app's update check resolves the Beta channel to the newest of `beta`
   and `latest` in PEP 440 order. When npm has no `beta` tag, it reads
   `unstable` in its place, so installs from the old lane still find their
   updates.

The channel of an installed build follows its version: a `-beta.` or
`-unstable.` build is on Beta. A saved `update_channel: unstable` reads as
`beta`.

### The unstable lane

`npm-unstable.yml` is manually dispatched. It creates a unique prerelease npm
version such as `2026.10.3-unstable.123.1`, patches the hosted `install.ps1`
and `update.ps1` scripts in the npm package so they download the exact
selected commit archive, and publishes that shim under the requested dist-tag
(`unstable` by default). It does not move GitHub releases, Microsoft Store
drafts, or the stable npm `latest` tag. Each publish also makes a GitHub
prerelease with the unsigned Windows MSI/NSIS installers and the Linux
`.deb`.

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

To save a channel choice:

```bash
dictate config set-update-channel beta
dictate config set-update-channel stable
```

`stable` is the user-facing name for npm's `latest` dist-tag. `unstable` is
the old name of `beta` and is saved as `beta`. The update check still follows
the build's version, not the saved choice; `dictate update --channel` will
change that ([#145](https://github.com/arcforgelabs/dictate/issues/145)).

Promotion rule: never promote by retagging an unstable npm package as
stable. A stable release is its own tag, built and checked by the
`dictate-*` workflows.

Windows has two supported ecosystems. Direct installs may select stable or beta
and update from the corresponding GitHub release/prerelease installer; these builds
are unsigned and Windows will show the expected untrusted-publisher warning. Microsoft
Store installs are stable-only and update through the Store. Do not revisit paid
Windows signing until there is an explicit revenue-backed decision.

Each Windows payload contains `engine/dictate-distribution.json`. Direct bundles mark
themselves `direct` and include their exact channel package version; Store MSIX bundles
mark themselves `store`. The app uses this marker rather than guessing from Windows.
