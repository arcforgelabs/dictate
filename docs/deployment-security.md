# Source and local-build security

Dictate is a Linux-only open-source personal app with no official deployment.
There is no release/npm/Store publishing workflow, business docs-sync token
consumer or organization self-hosted runner in the active source pipeline.

## Checks and authority

- Source CI, privacy proof, secret scanning and the manual Linux bundle builder
  run on GitHub-hosted Ubuntu with read-only contents permission.
- These workflows cannot publish releases/packages or obtain OIDC publishing
  tokens. Downloadable CI artifacts are temporary build evidence, not an
  official release.
- The retained native maintainer-command reaction uses GITHUB_TOKEN only for
  issue/PR reactions. Org-App Barnacle/Labeler callers are removed, not ported
  or granted personal-account credentials. Central fleet routing remains under
  the bot fleet owner's custody.
- A source merge never authorizes a release, official deployment, credential
  grant, Store API mutation or service stop.

## Local and historical consumers

Linux source installation prepares a public Parakeet model without a provider
credential; transcription stays local. A local build uses the existing
Tauri/PyInstaller scripts. Inspect source before running install/build scripts.

Existing installed apps still use historical npm/GitHub update channels. The
updater's digest verification and package identity remain unchanged. Existing
release artifacts and signatures are not replaced. Retained Windows/Store
scripts and old docs are historical, not active operating instructions.

Repository/environment secrets, app grants and Store/signing identities are
not deleted or copied by source workflow removal. No new credential is needed
to restore removed enterprise-style lanes; any future publishing goal needs
its own explicit review and authority. See [personal transfer](personal-ownership-transfer.md).
