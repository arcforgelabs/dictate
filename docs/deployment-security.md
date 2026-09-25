# Deployment Security

Dictate is open source. The repository contents, tests, and build scripts are
public by design, but deployment authority must stay private and deliberate.

This document defines the security boundary for workflows that publish packages
or change Microsoft Partner Center state. Authenticode signing support remains
in the repository as future plumbing only; paid Windows signing is not part of
the current release plan.

## Deployment Boundaries

Public and contributor-safe:

- Pull request tests.
- Unit tests, UI tests, Rust/Tauri tests, and package dry-runs.
- Manual unsigned/internal bundle builds that do not use deployment secrets.
- Secret scanning with redacted output.

Privileged:

- Creating or updating GitHub releases.
- Publishing the npm shim package.
- Uploading Microsoft Store packages to a draft.
- Publishing or committing a Microsoft Store submission.
- Reading or mutating Partner Center state with app credentials.

Privileged workflows must run from the default branch workflow definition, not a
feature branch. This prevents a branch from changing its own deployment workflow
and then running that modified version with production credentials.

## GitHub Environments

Use GitHub Environments to store secrets and require approval for privileged
lanes:

| Environment | Purpose | Secrets / variables |
| --- | --- | --- |
| `release` | GitHub release assets and desktop bundles | none beyond `GITHUB_TOKEN` |
| `npm-publish` | npm publish from `release.yml` and `npm-unstable.yml` | none; npm trusted publishing (GitHub OIDC, `id-token: write`) |
| `windows-signing` | Future paid Authenticode lane only; not required for current Store/staging releases | `WINDOWS_SIGNING_PFX_B64`, `WINDOWS_SIGNING_PFX_PASSWORD`, signing timestamp variables |
| `microsoft-store-status` | Read-only Store credential smoke/status checks | Store tenant/client/seller/product values and Store client secret |
| `microsoft-store-draft` | Build and upload Store package to an uncommitted draft | Store tenant/client/seller/product values and Store client secret |
| `microsoft-store-publish` | Commit a Store submission for Microsoft certification | Store tenant/client/seller/product values and Store client secret |

`microsoft-store-publish` should have the strictest approval requirement. Draft
upload is lower-risk than publish, but still uses Partner Center credentials and
should require maintainer intent.

Current repository settings:

- These environments exist in GitHub and require approval from
  `IAMSamuelRodda`.
- Environment deployment branch policy is set to protected branches only.
- The default branch ruleset requires PR review and the `gitleaks` status check
  for `main`/`master`.
- A release-tag ruleset protects `refs/tags/v20*` from deletion and
  non-fast-forward updates.

## Self-Hosted Runner

`windows-release-gate.yml` runs on a self-hosted runner, `win11-gpu`, inside the
Windows 11 VM on the maintainer workstation. The runner connects outbound to
GitHub; nothing on the VM or host is exposed. It starts at the `samuel` logon
(the VM signs in automatically) so the gate can launch the desktop app.

Because the repository is public, the runner sits in the organization runner
group `dictate-windows-gate`, restricted to
`arcforgelabs/dictate/.github/workflows/windows-release-gate.yml@refs/heads/master`.
Pull requests, including edited copies of that workflow on a branch or fork,
cannot schedule onto it. The workflow holds no secrets beyond `GITHUB_TOKEN`.

## Release Rules

1. Only release CalVer tags matching `vYYYY.M.D` or `vYYYY.M.D-N`.
2. The release tag must resolve to a commit reachable from the default branch.
3. The release workflow must be dispatched from the default branch.
4. Release jobs must pass tests before any publish step.
5. Stable public Windows releases go through Microsoft Store packaging and
   certification. Unsigned MSI/NSIS artifacts may be published for direct installs
   builds when the tester accepts Windows untrusted-publisher warnings.
6. Do not block ordinary release work on Windows signing configuration. The
   dedicated signing scripts/workflow are future-only unless a revenue-backed
   direct-download signing spend is explicitly approved.
7. Microsoft Store `draft` mode uploads a package without committing the
   submission. Microsoft Store `publish` mode submits the current draft for
   certification and must be explicitly approved.
8. Manual unstable npm publishes may move only non-stable dist-tags such as
   `unstable`. Stable promotion must go through the normal release workflow,
   not by moving `latest` to an unstable package.

## Secrets

- Do not store deployment credentials in the repository.
- Prefer environment secrets over repository-wide secrets for deployment lanes.
- Keep Microsoft Store read/status, draft-upload, and publish credentials
  separate where Partner Center permissions allow it.
- If Windows signing material is ever purchased, keep it only in the
  `windows-signing` environment.
- Do not expose provider keys, signing certificates, npm tokens, Store secrets,
  access tokens, or customer data to pull request workflows.
- Rotate a secret immediately if it is printed, copied into an artifact, or
  committed, even if the commit is later removed.

## Third-Party Tooling

Actions should be pinned by full commit SHA. Runtime installers used inside
release workflows should be version-pinned or checksum-verified where practical,
especially for tools that participate in signing, packaging, or Store upload.

Current acceptable exceptions are platform package managers used on ephemeral
GitHub-hosted runners (`winget`, `choco`, `apt`, and `rustup`) when no stable
checksum flow is practical. Treat failures or unexpected version changes in
those tools as release blockers until inspected.

## Pull Requests

Pull requests, including fork PRs, must not receive deployment secrets. They may
run build/test/dry-run workflows only. Any workflow using `pull_request_target`
must avoid checking out or executing untrusted PR code with privileged tokens.

## Verification Checklist

Before publishing:

1. Confirm secret scan is green.
2. Confirm CI is green on the release commit.
3. Confirm the release tag points to the intended default-branch commit.
4. Confirm Windows artifacts are signed before public upload.
5. Confirm Microsoft Store draft contents in Partner Center before publish.
6. Confirm website/legal notices match the release surface.
7. Confirm no support logs, screenshots, or artifacts contain deployment
   tokens, customer transcript text, lexicon terms, or private file paths.
8. Confirm the public privacy page is aligned with
   [dictate-privacy-policy.md](dictate-privacy-policy.md) and the public
   terms are current. Dictate is local-only, so the only network surfaces to
   review are model downloads, update checks, and Store install telemetry.

## Emergency Rotation

If a deployment secret may be exposed:

1. Revoke or rotate the secret at the provider first.
2. Replace the GitHub Environment secret.
3. Invalidate any active sessions or refresh tokens if the provider supports it.
4. Run secret scan across the affected commits.
5. Publish a short internal incident note with the secret name, exposure path,
   revocation time, replacement time, and any release artifacts that need to be
   rebuilt.
