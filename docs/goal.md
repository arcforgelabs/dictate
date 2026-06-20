# Dictate Goal

## Status

The repository-side Windows release, Microsoft Store package, Store API smoke,
and Dictate/ClawSweeper integration work is complete. The current public
release lane is `v2026.6.20`.

Completed implementation details and verification IDs have been moved to the
root `CHANGELOG.md`. This file now tracks only the remaining goal work.

## Remaining Work

1. For Store updates, run the guarded Microsoft Store MSIX workflow in
   `mode=draft`, review the draft in Partner Center, then run `mode=publish`
   only when ready for Microsoft certification.
2. Run a real Windows install/runtime smoke after package download or Store
   availability for each material release.
3. Configure a real Windows signing certificate in GitHub Actions before
   attaching `.msi` or `.exe` installers to public GitHub releases. The signing
   script and release workflow path exist, but no signing certificate secret is
   currently configured.
4. Keep the GitHub release lane and Microsoft Store publication lane separate:
   a GitHub release does not automatically make a Store update available.
5. Keep ClawSweeper scheduled/background runs disabled for Dictate until the
   maintainer decides scheduled fanout should begin. Manual smokes are passing;
   `CLAWSWEEPER_ENABLE_SCHEDULES` remains `0`.
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
- Recent manual ClawSweeper smokes passed for Dictate and Arc Forge Console.
- Partner Center state changes over time; check Partner Center or
  `.github/workflows/msstore-publish-msix.yml` in `mode=status` for live Store
  status rather than relying on historical run IDs in this public doc.
- UI Dependabot alerts for `vitest`, `vite`, and `esbuild` were remediated by
  upgrading the UI development toolchain; `npm audit` now reports zero
  vulnerabilities in the UI package.

## References

- [CHANGELOG.md](../CHANGELOG.md)
- [docs/release-versioning.md](release-versioning.md)
- [docs/msstore-automation.md](msstore-automation.md)
- [docs/msstore-listing.md](msstore-listing.md)
