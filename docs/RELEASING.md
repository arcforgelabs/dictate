# Release policy

Dictate offers stable releases for everyday use, beta releases for testing the
next stable release, and a dev channel for building from `master`. This page
explains those choices, how versions are numbered, and what a release has been
checked for.

The structure follows OpenClaw's release policy
([`docs/reference/RELEASING.md`](https://github.com/openclaw/openclaw/blob/main/docs/reference/RELEASING.md)
and [`docs/install/development-channels.md`](https://github.com/openclaw/openclaw/blob/main/docs/install/development-channels.md)),
adapted to a desktop app.

Parts of this page are the target design, not what ships today. The version
numbering, the beta version tooling, the update order and the `dictate-*`
release workflows are in place: see [The workflows](#the-workflows). The
rest is tracked in
[#145](https://github.com/arcforgelabs/dictate/issues/145), and
[What changes from today](#what-changes-from-today) lists every gap.
[release-versioning.md](release-versioning.md) is the procedure releases
follow.

The release workflows follow Arc Forge's Flow repository
([`arcforgelabs/flow`](https://github.com/arcforgelabs/flow),
`docs/RELEASING.md`), the most complete of the Arc Forge release setups.
Dictate builds desktop installers, not a container image, so it has no
image steps.

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
an alias. Today the app already reads a saved `unstable` as `beta`, and
`set-update-channel unstable` saves `beta`.

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
number within the month, starting at 1, not a day of the month: the highest
stable patch already tagged in that month (UTC) plus 1, so it can be more than
31 (after `2026.10.31` comes `2026.10.32`). `python scripts/calver.py next`
prints it. 2026.10.1
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

Builds from the old prerelease lane, `YYYY.M.P-unstable.R.A`, are on the beta
channel. They sort below every beta and the final of the same base. When npm
has no `beta` tag, the app reads `unstable` in its place, so these installs
still find their updates. `is_newer_version` in
`src/dictate/update_status.py` and `scripts/calver.py newest` hold this
order.

Package formats map the public version as follows. The Python, Debian and MSI
strings sort in the order above; the npm strings are only names (see above).

| Format                  | Final `2026.10.1` | Beta `2026.10.1-beta.2` | Correction `2026.10.1-1` |
| ----------------------- | ----------------- | ----------------------- | ------------------------ |
| Python (PEP 440)        | `2026.10.1`       | `2026.10.1b2`           | `2026.10.1.post1`        |
| npm (named by dist-tag) | `2026.10.1`       | `2026.10.1-beta.2`      | `2026.10.1-1`            |
| Debian (`.deb`)         | `2026.10.1`       | `2026.10.1~beta.2`      | `2026.10.1-1`            |
| MSI (WiX), target       | `26.10.1100.0`    | `26.10.1002.0`          | `26.10.1101.0`           |
| MSI (WiX), today        | `26.10.1.0`       | `26.10.1.0`             | `26.10.1.1`              |

MSI versions are numeric: major `YY` and minor `M`, each at most 255, then a
build number of at most 65535. Windows Installer compares only those three
fields and ignores a fourth, so the order lives in the build number:
`patch × 1000 + slot`, where the slot is N for beta N (1–99), 100 for the
final and 100 + K for correction K. The fourth field is always 0. Every later
build therefore has a higher version than an earlier one, and the patch can
reach 65 in a month before the build number runs out. The first release on
this map jumps the build number from today's `P` to `P × 1000 + 100`, which
is still higher than every earlier MSI.

Today the MSI keeps `YY.M.P.K` (see
[release-versioning.md](release-versioning.md)). A beta takes its final's MSI
version, and a correction compares equal to its final, because Windows
Installer ignores the fourth field. The in-app updater on Windows runs the
NSIS installer, not the MSI.

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

- `release-manifest.json`: the release commit, version and channel, the
  result of each check, the npm integrity and shasum, and every published
  file with its size and SHA-256.
- `dictate-<version>-dependency-evidence.zip`: the locked Python and npm
  dependencies and the advisory report for that commit. Not made yet.
- `postpublish-evidence.json`: what the publish run verified from outside
  after npm published: the npm integrity, `npm audit signatures` and the
  dist-tags.

Each asset has a `<asset>.sha256` file beside it. Check one with
`sha256sum -c <asset>.sha256`.

These identify the tested version and the files that shipped. Later
documentation fixes can improve the release notes without rebuilding or
replacing packages.

## The workflows

Each release is one annotated tag on a `master` commit, built once. The
GitHub release and the npm package carry the same version. A beta goes to npm
`beta` and a GitHub prerelease. A stable release or correction goes to npm
`latest` and the GitHub release marked Latest.

| Workflow | Starts | Does |
| --- | --- | --- |
| `dictate-release-prepare.yml` (Dictate Release Prepare) | By hand, from `master` | Takes a `master` commit (default: the head) whose CI passed. Plans the next tag for the channel with `scripts/calver.py plan`, creates it annotated (signed when the release tag key is set), and starts Dictate Release Publish. |
| `dictate-release-checks.yml` (Dictate Release Checks) | From Dictate Release Publish, or by hand to rehearse | Requires the tag to be annotated, on `master`, and a calendar version whose base the version files hold. Runs every CI lane (`ci.yml`) on its commit. Builds the Python distributions, the npm tarball, the `.deb`, and the MSI and NSIS installers. Publishes nothing. |
| `dictate-release-publish.yml` (Dictate Release Publish) | From Dictate Release Prepare, or by hand for an existing tag | `approve` job alongside the checks: environment `release` for a stable release or correction, `release-beta` for a beta. Then it creates the GitHub release as a draft with every package, a `<asset>.sha256` file beside each, and `release-manifest.json`, and starts Dictate NPM Release. |
| `dictate-npm-release.yml` (Dictate NPM Release) | From Dictate Release Publish | Requires the tarball to match the manifest. Accepts the Publish run's `release` approval when GitHub Actions dispatched it; dispatched by hand, it waits for `npm-release`. `publish` runs in environment `npm-publish`: npm trusted publishing with an explicit `--tag beta` or `--tag latest`. Then it reads back what npm serves, attaches `postpublish-evidence.json`, and makes the GitHub release public. For a stable release or correction, it starts the Windows release gate. |
| `dictate-release-promote.yml` (Dictate Release Promote) | By hand, from `master` | Points a channel at a published release, to move `beta` up after a stable release, or to roll a channel back. It verifies the manifest and the npm package, then moves the dist-tag in environment `npm-release`. A stable tag moves `latest` and GitHub's Latest, and moves `beta` up when `beta` is older in PEP 440 order. A beta tag moves `beta`. |

| Action | Approvals |
| --- | --- |
| Beta (`vYYYY.M.P-beta.N`) | 0 (`release-beta` has no reviewer) |
| Stable release (`vYYYY.M.P`) or correction (`vYYYY.M.P-N`) | 1: `release` |
| Promote or roll back a channel | 1: `npm-release` |
| Dictate NPM Release dispatched by hand | 1: `npm-release` |

Every workflow that changes anything runs only from `master`, so the release
tooling is `master`'s. Each job that builds or publishes checks out the tag
itself, never a commit handed on from an earlier job, and stops if the tag no
longer points at the commit the checks proved
(`tests/test_release_workflows.py` holds these rules). The version files hold
the base `YYYY.M.P`. A beta or correction takes its own version only in the
build jobs (`scripts/sync_release_version.py --stamp`).

The GitHub release stays a draft until npm serves the version. A user who
follows GitHub's latest release never sees a version that npm does not have.

Running Dictate Release Publish again for the same tag is safe. It checks
again, updates the draft's assets, and starts Dictate NPM Release. That
workflow skips a version npm already has with the same bytes, and refuses one
with different bytes. A published version is never replaced.

The Windows release gate (`windows-release-gate.yml`) and the Microsoft Store
lanes do not change. Dictate NPM Release starts the gate once a stable release
or correction is public. The gate takes no beta tags.

Not ported from Flow yet:

- **Release branches** (`flow-release-branch.yml`) and the **closeout**
  (`flow-release-closeout.yml`). Dictate still tags `master` commits. A
  release branch needs its own ruleset and cherry-pick tooling. The closeout
  only brings a release branch's version and notes back to `main`, which is
  not needed while releases come from `master`.
- **Full release validation** (`flow-full-release-validation.yml`). Dictate
  Release Checks runs every lane on the tag, so nothing waits on a schedule.
- **Windows signing.** The new builds are unsigned, as the direct-download
  installers are today. `release.yml` keeps its optional signing step.
- **Dependency evidence**, and the cold-start smoke and upgrade tests listed
  in [Release validation](#release-validation).

`release.yml` and `npm-unstable.yml` stay until the 2026.10.3 beta has
shipped through `npm-unstable.yml`. Use the `dictate-*` workflows for new
releases.

### Release a beta

The version files on `master` hold the upcoming stable version, for example
`2026.10.4` (`python scripts/sync_release_version.py`). Then:

```bash
gh workflow run dictate-release-prepare.yml --repo arcforgelabs/dictate --ref master -f channel=beta
```

Prepare tags `v2026.10.4-beta.1`, or the next beta number for that base.

### Release a stable version

```bash
gh workflow run dictate-release-prepare.yml --repo arcforgelabs/dictate --ref master -f channel=stable
```

Approve environment `release` in the Dictate Release Publish run. After npm
serves the version, move `beta` up so beta users are never behind stable:

```bash
gh workflow run dictate-release-promote.yml --repo arcforgelabs/dictate --ref master -f tag=v2026.10.4
```

The app already resolves Beta to the newest of `beta` and `latest`, so a beta
user gets the stable release even before this step.

### Correct a stable release

A correction repackages the latest stable release. Prepare it from that
release's commit, which still holds its version:

```bash
gh workflow run dictate-release-prepare.yml --repo arcforgelabs/dictate --ref master \
  -f channel=correction -f commit="$(git rev-parse v2026.10.4^{commit})"
```

### Roll back

Point the channel at an earlier release. Nothing is unpublished:

```bash
gh workflow run dictate-release-promote.yml --repo arcforgelabs/dictate --ref master -f tag=v2026.10.3
```

## One-time setup

Samuel does these steps once, before the first release through the
`dictate-*` workflows. Each one can be undone in the repository settings or
on npmjs.com.

1. **Environments.** Settings → Environments. All of them deploy from
   `master` only (Deployment branches and tags → Selected branches →
   `master`).
   - `release` and `npm-release`: required reviewer Samuel.
   - `release-beta` and `npm-publish`: no reviewer.
2. **npm trusted publishers.** An npm owner of `@arcforgelabs` does this on
   npmjs.com, with two-factor authentication. On the package's
   **Settings**, under **Trusted publishing**, add GitHub Actions
   publishers for organization `arcforgelabs`, repository `dictate`:

   | Workflow file | Environment | Allowed to |
   | --- | --- | --- |
   | `npm-unstable.yml` | `npm-publish` | publish (kept until it is retired) |
   | `dictate-npm-release.yml` | `npm-publish` | publish |
   | `dictate-release-promote.yml` | `npm-release` | **Allow npm dist-tag** on, publishing off |

   npm checks the file name of the run's top-level workflow, so these names
   must match exactly. Renaming a file breaks publishing until its trusted
   publisher is changed. The `release.yml` publisher can go once
   `release.yml` is removed.
3. **Pull requests from GitHub Actions.** Settings → Actions → General →
   Workflow permissions: tick **Allow GitHub Actions to create and approve
   pull requests**. No `dictate-*` workflow opens a pull request yet; a
   closeout will need it.

Ready for when releases need signed tags; not needed now:

1. **The release tag signing key.** Prepare signs each tag with an SSH key.
   Make one on your own computer: `ssh-keygen -t ed25519 -C "dictate release
   tags" -N "" -f dictate-release-tags`. Then:
   - Repository Settings → Secrets and variables → Actions → New repository
     secret: name `RELEASE_TAG_SIGNING_KEY`, value the whole private key
     file `dictate-release-tags`.
   - Your GitHub account Settings → SSH and GPG keys → New SSH key: title
     `Dictate release tags`, key type **Signing Key**, key the line in
     `dictate-release-tags.pub`.
   - Delete both files from your computer.
   - Set the repository variable `RELEASE_REQUIRE_SIGNED_TAGS` to `true`.
     Then Dictate Release Checks refuses a tag that GitHub does not show as
     verified.

   Prepare tags as `IAMSamuelRodda <7961255+IAMSamuelRodda@users.noreply.github.com>`.
   The repository variable `RELEASE_TAGGER` (`Name <email>`) names another
   account that holds the signing key.
2. **A release tag ruleset**, so `v20*` tags cannot be moved or deleted.

## What changes from today

Each row is tracked in [#145](https://github.com/arcforgelabs/dictate/issues/145).

| Today | Target | Status |
| ----- | ------ | ------ |
| `scripts/calver.py` and `scripts/sync_release_version.py` pick and check `YYYY.M.PATCH`, corrections `-N` and betas `-beta.N` (`calver.py plan`, `next --channel beta`) | The tooling and docs generate and check `YYYY.M.PATCH`, corrections `-N` and betas `-beta.N` | Done |
| The update check uses PEP 440 order (`is_newer_version` in `src/dictate/update_status.py`): betas and old unstable builds below the final, corrections above it | PEP 440 [version order](#version-order): betas below the final, corrections above it | Done |
| The `dictate-*` workflows publish npm `beta` and tags `vYYYY.M.P-beta.N`. `npm-unstable.yml` still publishes npm `unstable` and tags `vYYYY.M.D-unstable.<run>.<attempt>` until the 2026.10.3 beta ships | npm `beta`, tags `vYYYY.M.P-beta.N` | In progress: retire `npm-unstable.yml` |
| The channel is fixed by the build (`release_channel()` in `src/dictate/version.py` reads the version string; a beta or unstable build is on Beta); the UI refuses to change it; `dictate config set-update-channel stable\|beta` saves a choice, and a saved `unstable` reads as `beta`; there is no `dictate update` command | The channel is a saved setting on any direct install; `dictate update --channel`, `--tag`, `--dry-run` and `update status`; a saved `unstable` becomes `beta` on upgrade | Open |
| A separate side-by-side beta app was planned (#131) | One app; no separate beta app | Not part of the workflows |
| Releases tagged from `master` | `release/YYYY.M.P` branches with pinned tooling | Open |
| Annotated tags; Prepare signs them when `RELEASE_TAG_SIGNING_KEY` is set, and Checks requires a verified signature when `RELEASE_REQUIRE_SIGNED_TAGS` is `true` | Signed annotated tags, verified before publishing | Waiting for the signing key ([One-time setup](#one-time-setup)) |
| Release assets are packages, install scripts, a `.sha256` file for each, `release-manifest.json` and `postpublish-evidence.json` | Packages plus release manifest, dependency evidence and post-publish evidence | Dependency evidence open |
| MSI `YY.M.P.N` (`_msi_safe_version` in `scripts/sync_release_version.py`): the release counter is the build number (2026.10.2 is `26.10.2.0`); a correction `-N` goes in the fourth field, which Windows Installer ignores, so a correction compares equal to its final; a beta takes its final's number | MSI `YY.M.(P × 1000 + slot).0`: betas slot 1–99, the final 100, corrections 101 and up | Open |
