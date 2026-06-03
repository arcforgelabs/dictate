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
    else:  # pragma: no cover - argparse enforces choices.
        raise SystemExit(f"Unsupported command: {args.command}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
