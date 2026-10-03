# GitHub bot automation

Public repositories cannot call a private reusable workflow. These local workflow copies
come from `arcforgelabs/.github@a115c8f8dc02978d8c82c9554f02ea8e013a6981` (PR #5).
Upstream helper and reaction logic: `openclaw/openclaw@5ff5fb278348bb6d2280bfbfb7e5cd3a66e74712`, MIT.

Only delivery changes: direct event triggers, default manual inputs, trusted base checkout
of this repository, caller-only App repository scope, and the helper path here. No PR code
is executed. Preserve those substitutions when updating from the shared implementation.
Labeler uses the existing Barnacle App; reactions use GITHUB_TOKEN.

`barnacle.yml` is an inline copy of `arcforgelabs/.github@d1877d0bac0d77e614929580f071437d8ad3ac71`
for the same reason. Its scripts and config stay in `.github`: the job checks that repository
out at the pinned commit with the Barnacle App token, scoped to this repository and `.github`.
Bump the pinned SHA in both places when refreshing it.
