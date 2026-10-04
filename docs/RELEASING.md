# Release policy

Dictate offers stable releases for everyday use, beta releases for testing the
next stable release, and a dev channel for building from `master`. This page
explains those choices, how versions are numbered, and what a release has been
checked for.

The structure follows OpenClaw's release policy
([`docs/reference/RELEASING.md`](https://github.com/openclaw/openclaw/blob/main/docs/reference/RELEASING.md)
and [`docs/install/development-channels.md`](https://github.com/openclaw/openclaw/blob/main/docs/install/development-channels.md)),
adapted to a desktop app.

This is the target design, not what ships today. Only the version numbering
has started: 2026.10.1 was the first release numbered `YYYY.M.PATCH`. The rest
is planned and tracked in
[#145](https://github.com/arcforgelabs/dictate/issues/145), and
[What changes from today](#what-changes-from-today) lists every gap. Until it
lands, [release-versioning.md](release-versioning.md) is the procedure
releases follow.

## Release channels

| Channel | What you get |
| ------- | ------------ |
| Stable  | The regular release: the GitHub release marked Latest, npm `latest`, and the Microsoft Store. |
| Beta    | A candidate on npm `beta` and a GitHub prerelease. It may be a prerelease or a final version awaiting promotion. |
| Dev     | The moving head of `master`, built from source. For development only; it may be incomplete or broken. |

Every channel is the same app. There is no separate beta app: a user switches
channel on the install they have, and the choice is saved in `config.yaml` as
`update_channel`. Beta carries what is heading to the next stable release, and
nothing else: unfinished or shelved features are in no release, beta or
stable, switched off or otherwise. Meetings, shelved as P3 in
[`VISION.md`](../VISION.md), was removed from the app before 2026.10.1
([#143](https://github.com/arcforgelabs/dictate/pull/143)) and is kept on the
`archive/meeting-2026-10-03` branch
([#140](https://github.com/arcforgelabs/dictate/issues/140)).

On upgrade, a saved `update_channel: unstable` from the old prerelease lane
becomes `beta`, and the old `dictate config set-update-channel` command is
replaced by `dictate update --channel`. The old value is migrated, not kept as
an alias.

None of the commands below exist yet; they are planned in
[#145](https://github.com/arcforgelabs/dictate/issues/145). Today the channel
is fixed by the build, as described in
[release-versioning.md](release-versioning.md#npm-channels).

```bash
dictate update --channel stable
dictate update --channel beta
dictate update --channel dev
```

- `--channel` updates and saves the choice after a successful update. A
  refused or failed update keeps the previous channel.
- **Beta** installs the newest of npm `beta` and `latest` by
  [version order](#version-order). An older beta never replaces a newer
  stable release.
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
number within the month, starting at 1, not a day of the month. 2026.10.1
(released 3 October 2026) was the first version numbered this way. Git tags add
`v`, as in `v2026.10.1`. Release tags are annotated and signed, and the
publication workflow refuses lightweight, unsigned or unverified tags.

Published versions and release tags are never replaced. A fix gets a new
version: a correction (`-1`) for a repackage of the same code, or the next
patch for new code.

### Version order

Version order is PEP 440 order applied to the public version. A beta is older
than the final with the same base number, and a correction is newer:

```text
2026.10.1-beta.1 < 2026.10.1-beta.2 < 2026.10.1 < 2026.10.1-1 < 2026.10.2-beta.1
```

Every update decision uses this order: whether an update is available, which
of npm `beta` and `latest` the beta channel installs, and whether an install
is a downgrade that needs confirmation.

npm's semver order is different and never makes these decisions. npm reads
`2026.10.1-1` as a prerelease, so it ranks the correction below `2026.10.1`
and even below `2026.10.1-beta.2`. The app therefore never asks npm for the
"newest" version: it reads the exact versions that the `latest` and `beta`
dist-tags point at and compares them in PEP 440 order, and the release
workflow always publishes with an explicit `--tag`.

Package formats map the public version as follows. The Python and MSI strings
sort in the order above; the npm strings are only names (see above).

| Format                  | Final `2026.10.1` | Beta `2026.10.1-beta.2` | Correction `2026.10.1-1` |
| ----------------------- | ----------------- | ----------------------- | ------------------------ |
| Python (PEP 440)        | `2026.10.1`       | `2026.10.1b2`           | `2026.10.1.post1`        |
| npm (named by dist-tag) | `2026.10.1`       | `2026.10.1-beta.2`      | `2026.10.1-1`            |
| MSI (`YY.M.P.N`, WiX)   | `26.10.1.100`     | `26.10.1.2`             | `26.10.1.101`            |

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

Each row is tracked in [#145](https://github.com/arcforgelabs/dictate/issues/145).

| Today | Target |
| ----- | ------ |
| Releases since 2026.10.1 are numbered `YYYY.M.PATCH` by hand. `scripts/calver.py` still generates the day as the third number, and `scripts/sync_release_version.py`, `scripts/release_check.py`, the tag check in `release.yml` and `release-versioning.md` still call it the day. They accept any one- or two-digit third number with an optional `-N`, and reject `-beta.N` | The tooling and docs generate and check `YYYY.M.PATCH`, corrections `-N` and betas `-beta.N` |
| The update check ranks a same-base prerelease above the final (`_compare_prerelease` in `src/dictate/update_status.py`), so `2026.10.1-beta.2` would count as newer than `2026.10.1` | PEP 440 [version order](#version-order): betas below the final, corrections above it |
| Prerelease channel named `unstable`: npm `unstable`, tags `vYYYY.M.D-unstable.<run>.<attempt>` | npm `beta`, tags `vYYYY.M.P-beta.N` |
| The channel is fixed by the build (`release_channel()` in `src/dictate/version.py` reads the version string); the UI refuses to change it; `dictate config set-update-channel stable\|unstable` saves a choice; there is no `dictate update` command | The channel is a saved setting on any direct install; `dictate update --channel`, `--tag`, `--dry-run` and `update status`; a saved `unstable` becomes `beta` on upgrade |
| A separate side-by-side beta app was planned (#131) | One app; no separate beta app |
| Releases tagged from `master` | `release/YYYY.M.P` branches with pinned tooling |
| Unsigned annotated tags | Signed annotated tags, verified before publishing |
| Release assets are packages and install scripts | Packages plus release manifest, dependency evidence and post-publish evidence |
| MSI `YY.M.P.N` with the final at `.0` and corrections at `.1` and up (2026.10.2 is `26.10.2.0`); an unstable build keeps the MSI number of the commit it was built from | MSI `YY.M.P.N`: betas `.1`–`.99`, the final `.100`, corrections `.101` and up |
