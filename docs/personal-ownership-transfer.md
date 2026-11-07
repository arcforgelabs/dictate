# Dictate personal ownership transfer

Related: [#135](https://github.com/arcforgelabs/dictate/issues/135) and
[#164](https://github.com/arcforgelabs/dictate/issues/164).

Target: `IAMSamuelRodda/dictate`. Keep the app; move repository ownership,
not the npm package or Microsoft Store identity. This runbook is preparation,
not evidence that the transfer or a release has happened.

## Keep these contracts

- Keep `@arcforgelabs/dictate`, its existing dist-tags and jsDelivr bootstrap
  URLs. A GitHub transfer neither renames an npm package nor reconfigures its
  trusted publisher.
- Keep Store product `9P5S7747V0BP`, package identity
  `ArcForgeLabs.ArcForgeDictate` and the existing publisher/signing identity.
  Changing public links is separate from changing the Store identity.
- Keep every branch, tag, issue, PR, release and release asset. Do not rebuild
  or replace existing signed binaries to change their repository URL.
- Keep the old GitHub namespace vacant. Recreating `arcforgelabs/dictate`
  permanently removes its redirects and can break already-installed updaters.
- Do not switch, reset or clean another worker's checkout. A transfer does not
  publish local commits or uncommitted changes. Update those remotes only with
  the checkout owner's coordination.

## Stop before transfer until these are resolved

1. **npm OIDC:** both `release.yml` and `npm-unstable.yml` publish using
   trusted publishing, not the repository's legacy `NPM_TOKEN`. Inspect the
   npm package's trusted-publisher settings and coordinate the exact new owner,
   repository, workflow filenames and `npm-publish` environment at cutover.
   Inspect the independent **Allow npm publish** and **Allow npm dist-tag**
   permissions for both workflow bindings: both workflows use both operations.
   Verify the npm CLI supports OIDC publishing and dist-tag management; Node
   version alone is not proof. New configurations default to staged publishing,
   not direct publishing, and require a first publish within two days. Existing
   validated bindings use immutable repository identity: inspect their actual
   transfer behavior rather than assuming a new grant is always necessary.
   See [npm trusted publishing](https://docs.npmjs.com/trusted-publishers/).
   Do not add a token fallback, rename/deprecate the package, or claim that the
   presence of `NPM_TOKEN` proves future publishing works. A publisher grant
   change requires its own authorized custody; source edits cannot supply it.
2. **Bots:** Barnacle and Labeler require organization-level
   `BARNACLE_APP_PRIVATE_KEY` and `BARNACLE_APP_ID`. Barnacle also uses that
   installation token to check out the private `arcforgelabs/.github` source.
   A personal-account installation token cannot span both owners. Coordinate
   the supported caller design and coverage with the bot fleet owner; do not
   copy private keys, widen installations or change bot ownership. Any decision
   to retire this repository's bot integration must be explicit.
3. **Windows gate:** `windows-release-gate.yml` targets the organization's
   `win11-gpu` self-hosted runner and documents an organization runner-group
   restriction. Organization runner groups do not become personal-repository
   runners. Resolve this with the existing CI work before transfer, without
   enrolling a runner or weakening release checks here.
4. **Other organization dependencies:** inspect repository, environment and
   inherited secret/variable *names*, Actions permissions, environments,
   rulesets, webhooks, apps and collaborators. Docs sync inherits
   `ARCFORGE_DOCS_SYNC_TOKEN` and writes to `arcforgelabs/docs`; decide its
   disposition rather than silently copying a business credential. Inspect
   Store/signing environments separately from repository secrets.
5. **GitHub custody:** the active identity must administer the source and be
   able to transfer to the destination. A GET of the destination may redirect
   back to the source from an earlier move; compare `full_name` and repository
   ID, not just HTTP success. GitHub's transfer action is not a dry run.

## Source prerequisites

Use a focused PR after the dependency decisions above. Update active GitHub
repository URLs in the updater (latest, tags and release assets), PowerShell
archive bootstraps, npm package metadata, release/changelog tooling, issue and
support links, documentation, and the unstable workflow's archive-URL matching
expression together. Preserve npm scope URLs. Historical release notes and
captured design evidence are historical records, not current endpoint owners.

Reuse the existing privacy and terms source under `docs/` for the approved
root `PRIVACY.md` and `TERMS.md` home. Update the app and Windows wizard
links to those pages and README, and remove the updater's obsolete assumption
that the repository is private. Follow #164's installed-version, Partner
Center and old subscription checks before retiring any existing service or
public page. Publishing a release, changing a Store submission, redirecting
business pages and removing a backend are separate activation stages.

Run the updater, installer/package and repository-triage suites, the changelog
checks and normal CI. Review the complete diff independently and satisfy the
actual required checks. Do not use an admin bypass.

## Capture, transfer, verify

Immediately before cutover, capture repository ID/default head; all branch and
tag refs; every release ID and asset ID/name/size/digest; open issues/PRs and
assignments/types; protection rules; environment metadata; and integration
configuration without secret values. Keep that manifest private if it contains
non-public infrastructure details. Preserve unique local work separately.

GitHub documents that organization-to-personal transfers remove issue types,
non-owner issue assignments and read-only collaborators. Inspect and record
those losses before proceeding; do not silently treat them as preservation.
See [GitHub's transfer documentation](https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository).

Only after the consumer and custody gates pass, use GitHub's maintained
repository-transfer operation with `new_owner=IAMSamuelRodda`. Do not create a
replacement repository or replay commits. If acceptance is pending, observe
that transfer; do not submit another request blindly.

Verify the canonical repository ID is unchanged at the new URL; compare every
captured ref and release asset; inspect protection, environments and bot/CI
coverage; and test anonymous old and new latest/tag APIs, a real asset download
against its recorded SHA-256, and old Git clone/fetch redirects. Exercise both
npm-first update discovery and GitHub fallback/asset lookup. Confirm existing
npm/jsDelivr URLs still resolve and Store product links retain the same ID.
Old installed binaries must remain able to discover and fetch updates.

A source merge is not an updater release or Store certification. Close #135
only with the canonical new URL and preservation/redirect proof; leave #164
open until its installed-build and live Store-link acceptance is complete.
