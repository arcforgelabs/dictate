#!/usr/bin/env python3
"""Microsoft Store API helper for Dictate.

This script intentionally starts small:

- `auth-check` verifies the GitHub Actions/Partner Center credentials.
- `status` and `metadata` are read-only MSI/EXE Store API product checks after
  the Partner Center product ID exists.
- `legacy-auth-check`, `legacy-apps`, and `legacy-app` are read-only checks for
  MSIX/UWP apps through the older Store services API.
- `submit` is present but guarded by `--confirm-submit`, because API-created
  submissions should not be mixed with manual Partner Center edits.
- `legacy-draft` creates an MSIX draft carrying a new package plus the listing
  text from docs/msstore-listing.md and the screenshots, without committing.

Secrets are read only from the environment and are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


STORE_API_BASE = "https://api.store.microsoft.com"
STORE_API_SCOPE = "https://api.store.microsoft.com/.default"
LEGACY_STORE_API_BASE = "https://manage.devcenter.microsoft.com/v1.0/my"
LEGACY_STORE_API_RESOURCE = "https://manage.devcenter.microsoft.com"


@dataclass(frozen=True)
class StoreConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    seller_id: str
    product_id: str | None

    @classmethod
    def from_env(cls) -> "StoreConfig":
        missing = [
            name
            for name in (
                "MSSTORE_TENANT_ID",
                "MSSTORE_CLIENT_ID",
                "MSSTORE_CLIENT_SECRET",
                "MSSTORE_SELLER_ID",
            )
            if not os.environ.get(name)
        ]
        if missing:
            raise SystemExit(f"Missing required environment variable(s): {', '.join(missing)}")
        return cls(
            tenant_id=os.environ["MSSTORE_TENANT_ID"],
            client_id=os.environ["MSSTORE_CLIENT_ID"],
            client_secret=os.environ["MSSTORE_CLIENT_SECRET"],
            seller_id=os.environ["MSSTORE_SELLER_ID"],
            product_id=os.environ.get("MSSTORE_PRODUCT_ID") or None,
        )


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
    body: Any | None = None,
) -> dict[str, Any]:
    data: bytes | None = None
    request_headers = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw_error = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {url} failed with HTTP {error.code}: {raw_error}") from error
    except urllib.error.URLError as error:
        raise SystemExit(f"{method} {url} failed: {error}") from error


def access_token(config: StoreConfig) -> dict[str, Any]:
    token_url = f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/v2.0/token"
    return request_json(
        token_url,
        method="POST",
        form={
            "grant_type": "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "scope": STORE_API_SCOPE,
        },
    )


def legacy_access_token(config: StoreConfig) -> dict[str, Any]:
    token_url = f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/token"
    return request_json(
        token_url,
        method="POST",
        form={
            "grant_type": "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "resource": LEGACY_STORE_API_RESOURCE,
        },
    )


def api_headers(config: StoreConfig, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Seller-Account-Id": config.seller_id,
    }


def legacy_api_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


LISTING_LIMITS = {"features": 20, "keywords": 7, "releaseNotes": 1500, "description": 10000}


def _markdown_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = sections.setdefault(line[3:].strip(), [])
        elif current is not None:
            current.append(line)
    return sections


def _paragraphs(lines: list[str]) -> str:
    blocks = "\n".join(lines).strip().split("\n\n")
    return "\n\n".join(" ".join(part.split()) for part in blocks if part.strip())


def _bullets(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in lines:
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("  ") and items and line.strip():
            items[-1] += " " + line.strip()
    return items


def parse_listing(markdown: str) -> dict[str, Any]:
    """Store listing text from docs/msstore-listing.md, the single source."""
    sections = _markdown_sections(markdown)
    for name in ("Short Description", "Description", "Product Features", "Release Notes", "Keywords"):
        if name not in sections:
            raise SystemExit(f"listing markdown has no '## {name}' section")
    listing = {
        "shortDescription": _paragraphs(sections["Short Description"]),
        "description": _paragraphs(sections["Description"]),
        "features": _bullets(sections["Product Features"]),
        "releaseNotes": "\n".join(f"- {item}" for item in _bullets(sections["Release Notes"])),
        "keywords": [item.strip("`") for item in _bullets(sections["Keywords"])],
    }
    for key, limit in LISTING_LIMITS.items():
        size = len(listing[key])
        if size > limit:
            raise SystemExit(f"listing {key} is {size}, over the Store limit of {limit}")
    return listing


def parse_screenshot_captions(readme: str) -> list[tuple[str, str]]:
    """`1. \\`file.png\\` - caption` lines from the screenshots README, in order."""
    shots: list[tuple[str, str]] = []
    for line in readme.splitlines():
        parts = line.strip().split("`")
        if len(parts) >= 3 and parts[0].rstrip(". ").isdigit() and parts[1].endswith(".png"):
            shots.append((parts[1], parts[2].strip(" -")))
    if not shots:
        raise SystemExit("screenshots README lists no numbered `file.png` entries")
    return shots


def apply_draft_changes(
    submission: dict[str, Any],
    *,
    msix_name: str,
    listing: dict[str, Any],
    screenshots: list[tuple[str, str]],
    language: str = "en-us",
) -> dict[str, Any]:
    """Queue the new package and listing on a cloned submission.

    Existing packages and screenshots are marked PendingDelete; the new ones are
    PendingUpload and travel in the same zip. Logos and other images are kept.
    """
    updated = json.loads(json.dumps(submission))
    packages = updated.setdefault("applicationPackages", [])
    for package in packages:
        if package.get("fileName") != msix_name:
            package["fileStatus"] = "PendingDelete"
    packages.append({
        "fileName": msix_name,
        "fileStatus": "PendingUpload",
        "minimumDirectXVersion": "None",
        "minimumSystemRam": "None",
    })

    listings = updated.setdefault("listings", {})
    entry = listings.setdefault(language, {"baseListing": {}, "platformOverrides": {}})
    base = entry.setdefault("baseListing", {})
    base.update(listing)
    images = base.setdefault("images", [])
    for image in images:
        if image.get("imageType") == "Screenshot":
            image["fileStatus"] = "PendingDelete"
    for file_name, caption in screenshots:
        images.append({
            "fileName": f"screenshots/{file_name}",
            "fileStatus": "PendingUpload",
            "imageType": "Screenshot",
            "description": caption,
        })
    return updated


def upload_submission_zip(upload_url: str, zip_path: str) -> None:
    size = os.path.getsize(zip_path)
    with open(zip_path, "rb") as body:
        request = urllib.request.Request(
            upload_url,
            data=body,
            method="PUT",
            headers={
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": "2020-04-08",
                "Content-Length": str(size),
                "Content-Type": "application/zip",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=3600) as response:
                response.read()
        except urllib.error.HTTPError as error:
            raise SystemExit(f"upload failed with HTTP {error.code}: {error.read().decode(errors='replace')}") from error


def command_legacy_draft(
    config: StoreConfig,
    *,
    msix: str,
    listing_path: str,
    screenshots_dir: str,
    language: str,
    replace_pending: bool,
) -> None:
    import zipfile
    import tempfile

    product_id = require_product_id(config)
    with open(listing_path, encoding="utf-8") as fh:
        listing = parse_listing(fh.read())
    with open(os.path.join(screenshots_dir, "README.md"), encoding="utf-8") as fh:
        screenshots = parse_screenshot_captions(fh.read())
    for file_name, _ in screenshots:
        if not os.path.isfile(os.path.join(screenshots_dir, file_name)):
            raise SystemExit(f"missing screenshot {file_name}")
    msix_name = os.path.basename(msix)

    token = legacy_access_token(config)["access_token"]
    headers = legacy_api_headers(token)
    app_url = f"{LEGACY_STORE_API_BASE}/applications/{urllib.parse.quote(product_id)}"
    app = request_json(app_url, headers=headers)
    pending = (app.get("pendingApplicationSubmission") or {}).get("id")
    if pending:
        if not replace_pending:
            raise SystemExit(
                f"A submission ({pending}) is already pending. Wait for it to finish, "
                "or rerun with --replace-pending to delete it (API-created drafts only)."
            )
        request_json(f"{app_url}/submissions/{pending}", method="DELETE", headers=headers)
        print(f"Deleted pending submission {pending}")

    created = request_json(f"{app_url}/submissions", method="POST", headers=headers)
    submission_id = created["id"]
    upload_url = created["fileUploadUrl"]
    print(f"Created submission {submission_id}")

    updated = apply_draft_changes(
        created, msix_name=msix_name, listing=listing, screenshots=screenshots, language=language,
    )
    request_json(f"{app_url}/submissions/{submission_id}", method="PUT", headers=headers, body=updated)
    print(f"Queued {msix_name}, the {language} listing text and {len(screenshots)} screenshots")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "submission.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(msix, msix_name)
            for file_name, _ in screenshots:
                archive.write(os.path.join(screenshots_dir, file_name), f"screenshots/{file_name}")
        upload_submission_zip(upload_url, zip_path)
    print("Uploaded the package and screenshots")

    check = request_json(f"{app_url}/submissions/{submission_id}", headers=headers)
    names = {p.get("fileName") for p in check.get("applicationPackages", [])}
    base = (check.get("listings", {}).get(language) or {}).get("baseListing", {})
    if msix_name not in names:
        raise SystemExit(f"Draft {submission_id} does not list {msix_name}")
    if base.get("description") != listing["description"]:
        raise SystemExit(f"Draft {submission_id} did not keep the new {language} description")
    print(f"Draft {submission_id} contains {msix_name} and the new listing; not committed")


def require_product_id(config: StoreConfig) -> str:
    if not config.product_id:
        raise SystemExit("MSSTORE_PRODUCT_ID is required for this command.")
    return config.product_id


def command_auth_check(config: StoreConfig) -> None:
    token = access_token(config)
    expires_in = int(token.get("expires_in", 0) or 0)
    expires_at = int(time.time()) + expires_in if expires_in else None
    if "access_token" not in token:
        raise SystemExit(f"Token response did not include an access token: {sorted(token)}")
    print(
        json.dumps(
            {
                "ok": True,
                "scope": STORE_API_SCOPE,
                "expires_in": expires_in,
                "expires_at": expires_at,
            },
            indent=2,
        )
    )


def command_legacy_auth_check(config: StoreConfig) -> None:
    token = legacy_access_token(config)
    expires_in = int(token.get("expires_in", 0) or 0)
    expires_at = int(time.time()) + expires_in if expires_in else None
    if "access_token" not in token:
        raise SystemExit(f"Token response did not include an access token: {sorted(token)}")
    print(
        json.dumps(
            {
                "ok": True,
                "resource": LEGACY_STORE_API_RESOURCE,
                "expires_in": expires_in,
                "expires_at": expires_at,
            },
            indent=2,
        )
    )


def command_legacy_apps(config: StoreConfig) -> None:
    token = legacy_access_token(config)["access_token"]
    response = request_json(
        f"{LEGACY_STORE_API_BASE}/applications?top=100",
        headers=legacy_api_headers(token),
    )
    apps = []
    for app in response.get("value", []):
        apps.append(
            {
                "id": app.get("id"),
                "primaryName": app.get("primaryName"),
                "packageFamilyName": app.get("packageFamilyName"),
                "packageIdentityName": app.get("packageIdentityName"),
                "publisherName": app.get("publisherName"),
                "pendingSubmissionId": (app.get("pendingApplicationSubmission") or {}).get("id"),
                "lastPublishedSubmissionId": (
                    app.get("lastPublishedApplicationSubmission") or {}
                ).get("id"),
            }
        )
    print(
        json.dumps(
            {
                "ok": True,
                "totalCount": response.get("totalCount", len(apps)),
                "apps": apps,
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_legacy_app(config: StoreConfig) -> None:
    product_id = require_product_id(config)
    token = legacy_access_token(config)["access_token"]
    response = request_json(
        f"{LEGACY_STORE_API_BASE}/applications/{product_id}",
        headers=legacy_api_headers(token),
    )
    print(json.dumps(response, indent=2, sort_keys=True))


def command_status(config: StoreConfig) -> None:
    product_id = require_product_id(config)
    token = access_token(config)["access_token"]
    response = request_json(
        f"{STORE_API_BASE}/submission/v1/product/{product_id}/status",
        headers=api_headers(config, token),
    )
    print(json.dumps(response, indent=2, sort_keys=True))


def command_metadata(config: StoreConfig) -> None:
    product_id = require_product_id(config)
    token = access_token(config)["access_token"]
    response = request_json(
        f"{STORE_API_BASE}/submission/v1/product/{product_id}/metadata"
        "?languages=en-us&includelanguagelist=true",
        headers=api_headers(config, token),
    )
    print(json.dumps(response, indent=2, sort_keys=True))


def command_submit(config: StoreConfig, *, confirm_submit: bool) -> None:
    if not confirm_submit:
        raise SystemExit(
            "Refusing to submit without --confirm-submit. Complete the first Partner Center "
            "submission manually, then use API-created submissions consistently."
        )
    product_id = require_product_id(config)
    token = access_token(config)["access_token"]
    response = request_json(
        f"{STORE_API_BASE}/submission/v1/product/{product_id}/submit",
        method="POST",
        headers=api_headers(config, token),
    )
    print(json.dumps(response, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dictate Microsoft Store API helper.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth-check", help="Verify token acquisition without printing secrets.")
    subparsers.add_parser(
        "legacy-auth-check",
        help="Verify legacy MSIX/UWP Store services token acquisition without printing secrets.",
    )
    subparsers.add_parser("legacy-apps", help="List registered MSIX/UWP apps.")
    subparsers.add_parser("legacy-app", help="Read one registered MSIX/UWP app.")
    subparsers.add_parser("status", help="Read the current product draft status.")
    subparsers.add_parser("metadata", help="Read the current product draft metadata.")
    submit = subparsers.add_parser("submit", help="Submit the current draft. Guarded.")
    submit.add_argument("--confirm-submit", action="store_true")
    draft = subparsers.add_parser(
        "legacy-draft",
        help="Create an MSIX draft with a new package, listing text and screenshots. Does not commit.",
    )
    draft.add_argument("--msix", required=True, help="Path to the .msix to upload.")
    draft.add_argument("--listing", default="docs/msstore-listing.md", help="Listing markdown source.")
    draft.add_argument(
        "--screenshots", default="docs/msstore/assets/screenshots",
        help="Directory with the screenshots and a README listing them in order.",
    )
    draft.add_argument("--language", default="en-us")
    draft.add_argument(
        "--replace-pending", action="store_true",
        help="Delete an existing API-created pending submission first.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = StoreConfig.from_env()
    if args.command == "auth-check":
        command_auth_check(config)
    elif args.command == "legacy-auth-check":
        command_legacy_auth_check(config)
    elif args.command == "legacy-apps":
        command_legacy_apps(config)
    elif args.command == "legacy-app":
        command_legacy_app(config)
    elif args.command == "status":
        command_status(config)
    elif args.command == "metadata":
        command_metadata(config)
    elif args.command == "submit":
        command_submit(config, confirm_submit=args.confirm_submit)
    elif args.command == "legacy-draft":
        command_legacy_draft(
            config,
            msix=args.msix,
            listing_path=args.listing,
            screenshots_dir=args.screenshots,
            language=args.language,
            replace_pending=args.replace_pending,
        )
    else:  # pragma: no cover - argparse enforces choices.
        raise SystemExit(f"Unsupported command: {args.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
