# Source and release policy

Dictate is a Linux-only open-source personal app. There is no official
deployment, release schedule, or automated GitHub/npm/Store publisher.

## Supported path

Develop and run from a trusted checkout using the Linux installers. CI checks
Python, the Linux UI/shell, package metadata, clipboard integration and secrets.
The existing manual desktop-bundle workflow builds downloadable CI artifacts;
it does not create a GitHub Release, publish npm or deploy a service.

## Existing distributions

Historical GitHub Releases, tags, assets, npm versions/dist-tags and Store
identifiers remain intact. Their availability supports old installations; it
is not a promise that those snapshots contain current source. No package is
renamed or deprecated. Do not overwrite existing signed binaries.

A future public release requires an explicit maintainer decision and a focused,
reviewed publishing change. It is not part of routine source merges. Preserve
version consistency and the split changelog rules in CONTRIBUTING.md; normal
PRs do not edit release notes. See [versioning](release-versioning.md).

## Retired paths

Windows builds/signing, the organization Windows release-gate runner, Microsoft
Store submission, npm publishing and the business docs mirror are no longer
part of this repository's active pipeline. Retained scripts and historical
pages are not instructions to invoke them. No existing Store product, package,
service or credential was changed by removing those source workflows.
