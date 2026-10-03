# Release policy

Dictate offers stable releases for everyday use, beta releases for testing the
next stable release, and a dev channel for building from `master`. This page
explains those choices, how versions are numbered, and what a release has been
checked for.

The structure follows OpenClaw's release policy
([`docs/reference/RELEASING.md`](https://github.com/openclaw/openclaw/blob/main/docs/reference/RELEASING.md)
and [`docs/install/development-channels.md`](https://github.com/openclaw/openclaw/blob/main/docs/install/development-channels.md)),
adapted to a desktop app. This is the target design; the gap between it and
what ships today is listed at the end and tracked in GitHub issues.

## Release channels

| Channel | What you get |
| ------- | ------------ |
| Stable  | The regular release: the GitHub release marked Latest, npm `latest`, and the Microsoft Store. |
| Beta    | A candidate on npm `beta` and a GitHub prerelease. It may be a prerelease or a final version awaiting promotion. |
| Dev     | The moving head of `master`, built from source. For development only; it may be incomplete or broken. |

Every channel is the same app. There is no separate beta app: a user switches
channel on the install they have, and the choice is saved in `config.yaml` as
`update_channel`.

```bash
dictate update --channel stable
dictate update --channel beta
dictate update --channel dev
```

- `--channel` updates and saves the choice after a successful update. A
  refused or failed update keeps the previous channel.
- **Beta** installs the newest of npm `beta` and `latest` by version order. An
  older beta never replaces a newer stable release.
- **Dev** switches to a source checkout of `master`, builds it and reinstalls.
- `--tag <version>` installs one exact version once without changing the
  saved channel, for example `dictate update --tag 2026.10.1-beta.2`.
- Installing an older version than the one running asks for confirmation.
- `dictate update --dry-run` shows the channel, target version and planned
  steps without changing anything; `dictate update status` shows the channel,
  where that choice came from, the install kind, the current version and
  whether an update is available.
- Microsoft Store installs are stable only. The Store controls their updates.

The app's settings show the same channel choice for direct installs.

OpenClaw's fourth channel, extended-stable, is a maintenance line for its
Gateway servers. Dictate has no equivalent need and does not offer it.

## Version naming

| Release            | Version example     |
| ------------------ | ------------------- |
| Regular final      | `2026.10.1`         |
| Beta prerelease    | `2026.10.1-beta.1`  |
| Regular correction | `2026.10.1-1`       |

Versions use `year.month.patch`, without zero-padding. The patch is a release
number within the month, starting at 1, not a day of the month. Git tags add
`v`, as in `v2026.10.1`. Release tags are annotated and signed, and the
publication workflow refuses lightweight, unsigned or unverified tags.

Published versions and release tags are never replaced. A fix gets a new
version: a correction (`-1`) for a repackage of the same code, or the next
patch for new code. A prerelease is older than the final version with the same
base number.

Package formats map the public version as follows:

| Format                 | Final `2026.10.1` | Beta `2026.10.1-beta.2` | Correction `2026.10.1-1` |
| ---------------------- | ----------------- | ----------------------- | ------------------------ |
| Python (PEP 440)       | `2026.10.1`       | `2026.10.1b2`           | `2026.10.1.post1`        |
| npm                    | `2026.10.1`       | `2026.10.1-beta.2`      | `2026.10.1-1`            |
| MSI (`YY.M.P.N`, WiX)  | `26.10.1.100`     | `26.10.1.2`             | `26.10.1.101`            |

MSI versions are numeric, with major and minor at most 255. The fourth field
orders betas (1–99) below the final (100) and corrections (101+) of the same
release, so every later build installs over an earlier one.

## Release cadence

Releases go to beta first and move to stable after validation. Promotion does
not change the version: the final version is published to the beta channel,
validated, then promoted by moving npm `latest`, marking the GitHub release
Latest and submitting the same MSIX to the Store. A maintainer can publish
straight to stable when needed, and it still has to meet the stable
validation below. npm `beta` must always be at least as new as `latest`.

A release is cut from `master` onto a `release/YYYY.M.P` branch. Beta and
final builds of that release come from that branch with pinned release
tooling, and fixes reach it from `master` by cherry-pick.

## Release validation

Stable publication needs stable validation. A final version first published to
beta still has to meet it, and beta validation cannot qualify a stable release.

Blocking checks for stable:

- The Linux and Windows test matrix.
- The packaged builds: `.deb`, MSI and NSIS installers, and MSIX.
- The frozen-engine cold-start smoke: time to handshake, and the first
  authenticated `/api/state`.
- The hosted Windows user install smoke.
- The Windows release gate: install, launch, version check and uninstall on
  the release VM.
- Upgrade from the previous stable release on Windows and Linux.
- Release metadata and package integrity checks.

Beta needs the test matrix, the packaged builds and the cold-start smoke.

Every failed check needs an explicit release-lead decision: blocker or flake.
Rerun a flake on the same release commit at most twice, file its fix on
`master`, and keep the original failure on record. A skipped, cancelled or
missing check is not a pass.

Dependency advisories never block or delay a release. Release evidence records
every advisory, and the fix ships through `master` after publication. Only a
known-malware finding stops publication.

The health of `master` CI does not gate a release. Validation and publication
run from the release branch.

## Packages and apps can become available at different times

A published release does not mean every package is ready. The Microsoft Store
review, Windows signing and the npm publish can finish separately from the
GitHub release. A beta may ship without some installers; its release notes say
so, for example "no Windows installer for this beta".

## Release notes and verification

The [changelog](../CHANGELOG.md) describes user-facing changes. Each GitHub
release also carries:

- `dictate-<version>-release-manifest.json`: the release commit, version and
  channel, and every published file with its SHA-256.
- `dictate-<version>-dependency-evidence.zip`: the locked Python and npm
  dependencies and the advisory report for that commit.
- `dictate-<version>-postpublish-evidence.json`: the checks run against the
  published files after upload.

These identify the tested version and the files that shipped. Later
documentation fixes can improve the release notes without rebuilding or
replacing packages.

## What changes from today

| Today | Target |
| ----- | ------ |
| `YYYY.M.D`, the release date; same-day repackages `-N` | `YYYY.M.PATCH`, a release counter; corrections `-N`; betas `-beta.N` |
| Prerelease channel named `unstable`: npm `unstable`, tags `vYYYY.M.D-unstable.<run>.<attempt>` | npm `beta`, tags `vYYYY.M.P-beta.N` |
| The channel is fixed by the build (`release_channel()` reads the version string); the UI refuses to change it | The channel is a saved setting on any direct install; `dictate update --channel` |
| A separate side-by-side beta app was planned (#131) | One app; no separate beta app |
| Releases tagged from `master` | `release/YYYY.M.P` branches with pinned tooling |
| Unsigned annotated tags | Signed annotated tags, verified before publishing |
| Release assets are packages and install scripts | Packages plus release manifest, dependency evidence and post-publish evidence |
| MSI `YY.M.D.N` | MSI `YY.M.P.N`, betas below the final |
