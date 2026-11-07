# Versioning and historical releases

Dictate retains its existing CalVer versions and package identity. There is no
automated publishing pipeline or official deployment; current development is
Linux-only source work. See [source/release policy](RELEASING.md).

## Source metadata

Keep pyproject.toml, package.json and src/dictate/version.py consistent. Run
`python scripts/release_check.py` and `npm run changelog:check`.
Versions use YYYY.M.N, where N is the release count in the month; existing
correction suffixes remain readable. Do not bump a version just to merge a
pipeline cleanup.

## Historical distribution compatibility

Existing npm `@arcforgelabs/dictate` versions and latest/unstable dist-tags,
jsDelivr bootstraps, GitHub releases/tags/assets and updater behavior remain
unchanged. New source is not automatically published to any of those channels.
The old unstable shim tags are not full releases.

Split changelog tooling remains useful for historical records and an explicitly
authorized future release. CONTRIBUTING.md owns the format. Release-note and
contribution-record history is not rewritten by platform-support changes.

A future publisher must independently validate its custody, trusted-publisher
permissions, source provenance, Linux installation/update behavior and release
notes. The old Windows gate and Store submission are not release prerequisites
for the current Linux-only project.
