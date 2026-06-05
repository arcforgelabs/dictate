# Dictate Goal

## Status

The repository-side Windows release, Microsoft Store package, Store API smoke,
and Dictate/ClawSweeper integration work is complete as of 2026-06-04.

Completed implementation details and verification IDs have been moved to the
root `CHANGELOG.md`. This file now tracks only the remaining goal work.

## Remaining Work

1. Wait for Microsoft Partner Center certification and automatic Store
   publishing after the privacy URL correction was resubmitted on `2026-06-05`.
   Store CLI status run `26988971067` confirmed the pending submission is back
   in `Certification`.
2. Run a real Windows install/runtime smoke after package download or Store
   availability.
3. Configure a real Windows signing certificate in GitHub Actions before
   attaching `.msi` or `.exe` installers to public GitHub releases. The signing
   script and release workflow path exist, but no signing certificate secret is
   currently configured.
4. Use the guarded Microsoft Store MSIX publish workflow for future package
   updates after the first manual submission is accepted. The workflow can check
   status, upload a generated MSIX as an uncommitted draft, or explicitly commit
   the draft.
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
- Recent manual ClawSweeper smokes passed for Dictate and Arc Forge Console:
  `26925824791`, `26929644423`, `26930314117`, and `26930384789`.
- Microsoft Store Developer CLI status mode passed on run `26930465947` and
  reported the pending submission status as `Certification`.
- Microsoft Store Developer CLI status mode passed again on run `26930602624`
  and reported the pending submission status as `Certification`.
- Microsoft Store Developer CLI status mode passed again on run `26930886850`
  and reported the pending submission status as `Certification`.
- Microsoft Partner Center certification report
  `a0cf5c57-d578-48d9-b707-68a7a207ff6a` completed on `2026-06-04` with status
  `Attention needed` because the submitted privacy URL pointed to the general
  Arc Forge privacy page rather than the dedicated Dictate privacy policy.
- Microsoft Store Developer CLI status mode passed on run `26988691332` and
  reported the pending submission status as `CertificationFailed`.
- The Partner Center privacy policy URL was corrected to
  `https://arcforge.au/privacy/dictate` and resubmitted on `2026-06-05`.
- Microsoft Store Developer CLI status mode passed on run `26988971067` and
  reported the pending submission status as `Certification`.
- UI Dependabot alerts for `vitest`, `vite`, and `esbuild` were remediated by
  upgrading the UI development toolchain; `npm audit` now reports zero
  vulnerabilities in the UI package.

## References

- [CHANGELOG.md](../CHANGELOG.md)
- [docs/release-versioning.md](release-versioning.md)
- [docs/msstore-automation.md](msstore-automation.md)
- [docs/msstore-listing.md](msstore-listing.md)
