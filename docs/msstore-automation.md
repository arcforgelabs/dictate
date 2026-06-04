# Microsoft Store Automation

This runbook covers the non-secret automation pieces for publishing Dictate
through the Microsoft Store after the first Partner Center product/submission
exists.

## Current Partner Center Identity

- Product name: `Arc Forge Dictate`
- Product type: `MSIX or PWA app`
- Store ID / product ID: `9P5S7747V0BP`
- Package/Identity/Name: `ArcForgeLabs.ArcForgeDictate`
- Package/Identity/Publisher: `CN=56989B1A-E9FD-45E0-827B-FDB65D3C9B3C`
- Package/Properties/PublisherDisplayName: `Arc Forge Labs`
- Package Family Name (PFN): `ArcForgeLabs.ArcForgeDictate_tbf7er950vsxw`
- Package SID: `S-1-15-2-414942928-860362531-3808921871-2325232450-2546095560-3460849545-2812936032`
- Manual draft submission: `Submission 1`
- Submission ID: `1152921505701159461`
- Submission last modified: `2026-06-03`
- Current draft package: `ArcForgeDictate_2026.6.3.0_x64.msix`
- Current draft package status: validated in Partner Center.
- Current submission status: in certification.
- Current certification stage: pre-processing.
- Current publishing mode: publish as soon as certification passes.
- Current gate status: all gates complete; the IARC questionnaire and Terms of
  Use approval are saved.
- Seller ID: `94852860`
- Tenant ID: `040ca04b-6b25-40a6-8b72-385e983e33af`
- Client ID: `1b26108f-d69b-4229-8282-c6fb937b4c03`
- Partner Center app role: `Manager(Windows)`
- Client secret: stored in Bitwarden and GitHub Actions secrets only.

## Store Package Builder

- MSIX manifest template: `packaging/msix/Package.appxmanifest.in`
- MSIX build script: `scripts/build-windows-msix-store.ps1`
- Manual MSIX workflow: `.github/workflows/windows-msix-store-bundle.yml`
- Manual MSIX publish workflow:
  `.github/workflows/msstore-publish-msix.yml`
- Output pattern: `packaging/msix/out/ArcForgeDictate_<version>_x64.msix`

The MSIX manifest is pinned to the reserved Partner Center identity. The builder
uses `tauri build --no-bundle`, stages `dictate-ui-shell.exe` and
`engine\dictate-engine.exe`, renders the four-part MSIX version from
`tauri.conf.json`, and packs the loose layout with Microsoft `winapp`.

## GitHub Actions Wiring

Add these repository variables:

- `MSSTORE_TENANT_ID`: `040ca04b-6b25-40a6-8b72-385e983e33af`
- `MSSTORE_CLIENT_ID`: `1b26108f-d69b-4229-8282-c6fb937b4c03`
- `MSSTORE_SELLER_ID`: `94852860`

Add this repository secret:

- `MSSTORE_CLIENT_SECRET`: the Partner Center Publisher app client secret value.

Do not store the client secret in this repository.

Current GitHub Actions state:

- Repository variables are set for tenant ID, client ID, and seller ID.
- `MSSTORE_CLIENT_SECRET` is set as a GitHub Actions repository secret.
- Local `auth-check` has verified token acquisition for
  `https://api.store.microsoft.com/.default`.
- Local `legacy-apps` has verified the MSIX/UWP Store services API can see
  `Arc Forge Dictate`:
  - App ID: `9P5S7747V0BP`
  - Primary name: `Arc Forge Dictate`
  - Package identity name: `ArcForgeLabs.ArcForgeDictate`
  - Pending submission ID: `1152921505701159461`
- Local `status` against Store ID `9P5S7747V0BP` returns `No Product Found` on
  `https://api.store.microsoft.com/submission/v1/product/...`, which is expected
  until we validate the correct API path for this MSIX/PWA product or create an
  MSI/EXE product. Do not treat this as a secret or token failure.

## Smoke Workflow

Use `.github/workflows/msstore-api-smoke.yml` to verify credentials.

Auth-only smoke:

```bash
gh workflow run msstore-api-smoke.yml
```

After this workflow is committed to the default branch, query the reserved
MSIX/PWA product:

```bash
gh workflow run msstore-api-smoke.yml -f product_id=9P5S7747V0BP -f query=legacy-app
gh workflow run msstore-api-smoke.yml -f query=legacy-apps
```

Use `.github/workflows/msstore-publish-msix.yml` for the guarded package update
path after the first manual submission is accepted.

Read-only status:

```bash
gh workflow run msstore-publish-msix.yml -f mode=status -f product_id=9P5S7747V0BP
```

Upload a newly built MSIX into the current draft without committing it:

```bash
gh workflow run msstore-publish-msix.yml -f mode=draft -f product_id=9P5S7747V0BP
```

Commit the current draft to Microsoft certification:

```bash
gh workflow run msstore-publish-msix.yml -f mode=publish -f product_id=9P5S7747V0BP
```

Do not run `mode=draft` or `mode=publish` against `Submission 1` while it is in
certification. The workflow exists for future API-managed updates after the
first manual submission is accepted.

## Local Smoke

Set the same environment variables locally, then run:

```bash
python scripts/msstore-submit.py auth-check
python scripts/msstore-submit.py legacy-auth-check
python scripts/msstore-submit.py legacy-apps
MSSTORE_PRODUCT_ID=9P5S7747V0BP python scripts/msstore-submit.py legacy-app
```

The script never prints access tokens or client secrets.

## Submission Discipline

Microsoft warns that once a submission is created through the API, edits to that
same submission should continue through the API rather than Partner Center. For
Dictate:

1. Complete `Submission 1` manually in Partner Center.
2. Use the API smoke workflow to confirm credentials and product access.
3. Use `msstore-publish-msix.yml` for future API-managed package updates after
   the MSIX/PWA product accepts the first manual submission, or after a separate
   MSI/EXE product is created for Tauri installer output.
4. Use API-created submissions consistently for future automated updates.

Current state: `Submission 1` is already in certification. Do not create or
modify this submission through the API while certification is in progress.

Use [msstore-listing.md](msstore-listing.md) for the first listing copy,
privacy/certification notes, screenshots checklist, and remaining pre-submit
requirements.

## API Notes

The current helper targets the newer Store API surface documented by Microsoft
for MSI/EXE submissions. The reserved product is an `MSIX or PWA app`; Microsoft
still documents the older Store services API for registered UWP/MSIX apps at
`https://manage.devcenter.microsoft.com/v1.0/my/applications`. Validate the
correct API path for `9P5S7747V0BP` after the first manual submission is
accepted, or create a separate MSI/EXE product if we choose the Tauri installer
path.

The MSIX/UWP Store services API uses:

- Token endpoint: `https://login.microsoftonline.com/<tenant-id>/oauth2/token`
- Resource: `https://manage.devcenter.microsoft.com`
- Base URL: `https://manage.devcenter.microsoft.com/v1.0/my`

The newer Store Submission API uses:

- Token endpoint: `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token`
- Scope: `https://api.store.microsoft.com/.default`
- Base URL: `https://api.store.microsoft.com`
- Required request header: `X-Seller-Account-Id`

The current helper supports:

- `auth-check`
- `legacy-auth-check`
- `legacy-apps`
- `legacy-app`
- `status`
- `metadata`
- guarded `submit --confirm-submit`

The manual publish workflow uses Microsoft Store Developer CLI because Microsoft
documents `msstore publish --inputFile <msix> --appId <productId> --noCommit`
for MSIX package upload and `msstore submission publish <productId>` for the
separate commit step.
