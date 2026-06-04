# Dictate Goal

## Status

The repository-side Windows release, Microsoft Store package, Store API smoke,
and Dictate/ClawSweeper integration work is complete as of 2026-06-04.

Completed implementation details and verification IDs have been moved to the
root `CHANGELOG.md`. This file now tracks only the remaining goal work.

## Remaining Work

1. Wait for Microsoft Partner Center certification and automatic Store
   publishing for the first `Arc Forge Dictate` submission.
2. Run a real Windows install/runtime smoke after package download or Store
   availability.
3. Add signing for direct-download Windows artifacts before attaching `.msi` or
   `.exe` installers to public GitHub releases.
4. Add mutating Microsoft Store package/listing upload automation after the
   first manual submission is accepted and the API path is confirmed.
5. Keep ClawSweeper scheduled/background runs disabled for Dictate until several
   manual smokes pass without branch, credential, or state-sync regressions.
6. Review and explicitly approve any future Dictate ClawSweeper auto-close
   policy before enabling it.

## Current Operating Posture

- Microsoft Store is the primary public Windows distribution target.
- Signed website/GitHub downloads remain a secondary fallback path.
- Hosted PowerShell bootstrap instructions are developer/source install guidance,
  not the normal public Windows install path.
- New npm package and install paths use `@arcforgelabs/dictate`.
- The deprecated personal npm package path should remain published only as a
  compatibility landing point unless there is a specific security or legal
  reason to remove it.
- Dictate is a public open-source repository.
- Arc Forge ClawSweeper and its durable state repository remain private.
- ClawSweeper is currently review/comment only for Dictate.

## References

- [CHANGELOG.md](../CHANGELOG.md)
- [docs/release-versioning.md](release-versioning.md)
- [docs/msstore-automation.md](msstore-automation.md)
- [docs/msstore-listing.md](msstore-listing.md)
