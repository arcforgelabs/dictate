# Microsoft Store Automation

This runbook covers the non-secret automation pieces for publishing Dictate
through the Microsoft Store for the existing Partner Center product. Deployment
credential boundaries and approval requirements are tracked in
[deployment-security.md](deployment-security.md).

## Current Partner Center Identity

- Product name: `Arc Forge Dictate`
- Product type: `MSIX or PWA app`
- Store ID / product ID: `9P5S7747V0BP`
- Package/Identity/Name: `ArcForgeLabs.ArcForgeDictate`
- Package/Identity/Publisher: `CN=56989B1A-E9FD-45E0-827B-FDB65D3C9B3C`
- Package/Properties/PublisherDisplayName: `Arc Forge Labs`
- Package Family Name (PFN): `ArcForgeLabs.ArcForgeDictate_tbf7er950vsxw`
- Package SID: `S-1-15-2-414942928-860362531-3808921871-2325232450-2546095560-3460849545-2812936032`
- Partner Center app role: `Manager(Windows)`
- Store publication status changes in Partner Center. Do not hard-code transient
  submission IDs, draft package names, certification stages, or internal account
  identifiers in this public repository.

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

The Store reserves the fourth version part, so it is always `0`. The day and
the same-day release number share the third part: `2026.9.25` packs as
`2026.9.2500.0` and `2026.9.25-1` as `2026.9.2501.0`. Unstable versions are
rejected; the Store is stable-only.

A draft upload fails if Partner Center already holds a submission created by
hand there. Delete that submission in Partner Center, then rerun `mode=draft`.

## GitHub Actions Wiring

Add these repository variables in GitHub Actions. Keep the values in repository
settings, not in committed docs:

- `MSSTORE_TENANT_ID`
- `MSSTORE_CLIENT_ID`
- `MSSTORE_SELLER_ID`

Add this repository secret:

- `MSSTORE_CLIENT_SECRET`: the Partner Center Publisher app client secret value.

Do not store the client secret in this repository.

Current GitHub Actions state:

- Repository variables are set for tenant ID, client ID, and seller ID.
- `MSSTORE_CLIENT_SECRET` is set as a GitHub Actions repository secret.
- `msstore-publish-msix.yml` status mode verifies credentials and current Store
  submission status without creating or committing a package.

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
path.

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

`mode=draft` uploads a newly built MSIX into a Store draft without committing it.
Review that draft in Partner Center before running `mode=publish`, which commits
the current draft and polls Microsoft certification.

## Updating the listing

The Store listing text and screenshots live in the repo and ship with every
draft:

- Text: `docs/msstore-listing.md` sections `Short Description`, `Description`,
  `Product Features`, `Release Notes` and `Keywords`.
- Screenshots: `docs/msstore/assets/screenshots/`, in the order the README
  there lists them, with its captions.

`mode=draft` runs `scripts/msstore-submit.py legacy-draft`, which creates one
API submission, queues the new MSIX (the previous package is marked for
removal), replaces the `en-us` text and screenshots (logos are kept), uploads
the package and screenshots in one zip, and reads the draft back to check the
package and description landed. It never commits. To change only the listing,
edit those files, merge, and run a draft; the package is rebuilt from `master`
either way.

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

1. Use the API smoke/status workflow to confirm credentials and product access.
2. Run the Windows release gate against the GitHub release you are about to
   ship: `scripts/windows-vm-release-gate.sh --tag vYYYY.M.D-N`. It installs
   the published `setup.exe` on the `win11-gpu` VM, launches it in the
   signed-in session, checks the engine's `/api/health` version, and
   uninstalls. Do not draft if it fails. See
   [windows-11.md](windows-11.md#release-gate).
3. Use `msstore-publish-msix.yml` with `mode=draft` to create/update the Store
   draft package.
4. Review the draft in Partner Center.
5. Use `mode=publish` only when that draft should be submitted for Microsoft
   certification.
6. Use API-created submissions consistently for future automated updates.

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
- `legacy-draft` (MSIX draft with package, listing text and screenshots; no commit)

`mode=draft` uploads through `scripts/msstore-submit.py legacy-draft` (see
"Updating the listing"). `mode=publish` and `mode=status` use the Microsoft
Store Developer CLI: `msstore submission publish <productId>` commits the draft
and `msstore submission poll` follows certification.

An earlier draft step used `msstore publish --inputDirectory <dir>` with no
project path. The CLI then inspected the working directory, saw `package.json`,
treated the repo as an Electron app and uploaded without attaching the package;
the Store re-published the previous package and reported success. That happened
with the first September 2026 submission.
