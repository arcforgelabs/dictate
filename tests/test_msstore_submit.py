from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


def load_msstore_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "msstore-submit.py"
    spec = importlib.util.spec_from_file_location("msstore_submit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load msstore-submit.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MicrosoftStoreSubmitTests(unittest.TestCase):
    def test_missing_env_fails_before_network(self) -> None:
        module = load_msstore_module()

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as raised:
                module.StoreConfig.from_env()

        self.assertIn("MSSTORE_TENANT_ID", str(raised.exception))
        self.assertIn("MSSTORE_CLIENT_SECRET", str(raised.exception))

    def test_auth_check_does_not_print_access_token(self) -> None:
        module = load_msstore_module()
        config = module.StoreConfig(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            seller_id="seller",
            product_id=None,
        )

        with patch.object(
            module,
            "access_token",
            return_value={"access_token": "sensitive-token", "expires_in": "3600"},
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                module.command_auth_check(config)

        rendered = output.getvalue()
        self.assertIn('"ok": true', rendered)
        self.assertIn('"expires_in": 3600', rendered)
        self.assertNotIn("sensitive-token", rendered)
        self.assertNotIn("secret", rendered)

    def test_legacy_auth_check_does_not_print_access_token(self) -> None:
        module = load_msstore_module()
        config = module.StoreConfig(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            seller_id="seller",
            product_id=None,
        )

        with patch.object(
            module,
            "legacy_access_token",
            return_value={"access_token": "sensitive-token", "expires_in": "3600"},
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                module.command_legacy_auth_check(config)

        rendered = output.getvalue()
        self.assertIn('"ok": true', rendered)
        self.assertIn('"resource": "https://manage.devcenter.microsoft.com"', rendered)
        self.assertNotIn("sensitive-token", rendered)
        self.assertNotIn("secret", rendered)

    def test_status_requires_product_id(self) -> None:
        module = load_msstore_module()
        config = module.StoreConfig(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            seller_id="seller",
            product_id=None,
        )

        with self.assertRaises(SystemExit) as raised:
            module.command_status(config)

        self.assertIn("MSSTORE_PRODUCT_ID", str(raised.exception))

    def test_legacy_app_requires_product_id(self) -> None:
        module = load_msstore_module()
        config = module.StoreConfig(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            seller_id="seller",
            product_id=None,
        )

        with self.assertRaises(SystemExit) as raised:
            module.command_legacy_app(config)

        self.assertIn("MSSTORE_PRODUCT_ID", str(raised.exception))

    def test_legacy_apps_summarizes_without_tokens(self) -> None:
        module = load_msstore_module()
        config = module.StoreConfig(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            seller_id="seller",
            product_id=None,
        )

        with (
            patch.object(module, "legacy_access_token", return_value={"access_token": "token"}),
            patch.object(
                module,
                "request_json",
                return_value={
                    "totalCount": 1,
                    "value": [
                        {
                            "id": "9P5S7747V0BP",
                            "primaryName": "Arc Forge Dictate",
                            "packageIdentityName": "ArcForgeLabs.ArcForgeDictate",
                            "pendingApplicationSubmission": {"id": "1152921505701159461"},
                        }
                    ],
                },
            ),
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                module.command_legacy_apps(config)

        rendered = output.getvalue()
        self.assertIn("Arc Forge Dictate", rendered)
        self.assertIn("1152921505701159461", rendered)
        self.assertNotIn('"token"', rendered)

    def test_submit_requires_explicit_confirmation(self) -> None:
        module = load_msstore_module()
        config = module.StoreConfig(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            seller_id="seller",
            product_id="product",
        )

        with self.assertRaises(SystemExit) as raised:
            module.command_submit(config, confirm_submit=False)

        self.assertIn("--confirm-submit", str(raised.exception))

    def test_request_json_handles_empty_response(self) -> None:
        module = load_msstore_module()

        class EmptyResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b""

        with patch("urllib.request.urlopen", return_value=EmptyResponse()):
            self.assertEqual(module.request_json("https://example.test"), {})


ROOT = Path(__file__).resolve().parents[1]


class ListingSourceTests(unittest.TestCase):
    def test_repo_listing_parses_within_store_limits(self) -> None:
        module = load_msstore_module()
        listing = module.parse_listing((ROOT / "docs" / "msstore-listing.md").read_text())
        self.assertTrue(listing["shortDescription"])
        self.assertIn("Parakeet", listing["description"])
        self.assertLessEqual(len(listing["features"]), 20)
        self.assertLessEqual(len(listing["keywords"]), 7)
        for word in ("Dictate Pro", "hosted", "subscription path"):
            self.assertNotIn(word, listing["description"])

    def test_repo_screenshots_exist_in_order(self) -> None:
        module = load_msstore_module()
        folder = ROOT / "docs" / "msstore" / "assets" / "screenshots"
        shots = module.parse_screenshot_captions((folder / "README.md").read_text())
        self.assertEqual(shots[0][0], "dictate-01-ready.png")
        for name, caption in shots:
            self.assertTrue((folder / name).is_file(), name)
            self.assertTrue(caption)

    def test_missing_section_is_rejected(self) -> None:
        module = load_msstore_module()
        with self.assertRaises(SystemExit):
            module.parse_listing("## Description\n\nOnly this.\n")


class DraftChangesTests(unittest.TestCase):
    def test_replaces_package_text_and_screenshots_only(self) -> None:
        module = load_msstore_module()
        original = {
            "id": "1",
            "applicationPackages": [{"fileName": "ArcForgeDictate_2026.6.3.0_x64.msix", "fileStatus": "Uploaded"}],
            "listings": {"en-us": {"baseListing": {
                "description": "old", "title": "Arc Forge Dictate",
                "images": [
                    {"fileName": "old.png", "fileStatus": "Uploaded", "imageType": "Screenshot"},
                    {"fileName": "logo.png", "fileStatus": "Uploaded", "imageType": "StoreLogo300x300"},
                ],
            }}},
        }
        listing = {"description": "new", "features": ["a"], "releaseNotes": "- n",
                   "shortDescription": "s", "keywords": ["k"]}
        updated = module.apply_draft_changes(
            original, msix_name="ArcForgeDictate_2026.9.2600.0_x64.msix", listing=listing,
            screenshots=[("dictate-01-ready.png", "Home")],
        )
        packages = {p["fileName"]: p["fileStatus"] for p in updated["applicationPackages"]}
        self.assertEqual(packages["ArcForgeDictate_2026.6.3.0_x64.msix"], "PendingDelete")
        self.assertEqual(packages["ArcForgeDictate_2026.9.2600.0_x64.msix"], "PendingUpload")

        base = updated["listings"]["en-us"]["baseListing"]
        self.assertEqual(base["description"], "new")
        self.assertEqual(base["title"], "Arc Forge Dictate")
        images = {i["fileName"]: i for i in base["images"]}
        self.assertEqual(images["old.png"]["fileStatus"], "PendingDelete")
        self.assertEqual(images["logo.png"]["fileStatus"], "Uploaded")
        self.assertEqual(images["screenshots/dictate-01-ready.png"]["fileStatus"], "PendingUpload")
        self.assertEqual(images["screenshots/dictate-01-ready.png"]["description"], "Home")
        self.assertEqual(original["listings"]["en-us"]["baseListing"]["description"], "old")

    def test_legacy_draft_refuses_an_existing_pending_submission(self) -> None:
        module = load_msstore_module()
        config = module.StoreConfig(
            tenant_id="t", client_id="c", client_secret="s", seller_id="x", product_id="9P5S7747V0BP",
        )
        with (
            patch.object(module, "legacy_access_token", return_value={"access_token": "token"}),
            patch.object(module, "request_json", return_value={"pendingApplicationSubmission": {"id": "42"}}),
            patch("os.path.isfile", return_value=True),
        ):
            with self.assertRaises(SystemExit) as raised:
                module.command_legacy_draft(
                    config, msix="ArcForgeDictate_2026.9.2600.0_x64.msix",
                    listing_path=str(ROOT / "docs" / "msstore-listing.md"),
                    screenshots_dir=str(ROOT / "docs" / "msstore" / "assets" / "screenshots"),
                    language="en-us", replace_pending=False,
                )
        self.assertIn("already pending", str(raised.exception))


class ListingLanguageKeyTests(unittest.TestCase):
    def test_updates_the_existing_listing_whatever_its_casing(self) -> None:
        module = load_msstore_module()
        original = {
            "applicationPackages": [],
            "listings": {"en-US": {"baseListing": {"description": "old", "images": []}}},
        }
        updated = module.apply_draft_changes(
            original, msix_name="a.msix",
            listing={"description": "new", "features": [], "releaseNotes": "", "shortDescription": "", "keywords": []},
            screenshots=[],
        )
        self.assertEqual(list(updated["listings"]), ["en-US"])
        self.assertEqual(updated["listings"]["en-US"]["baseListing"]["description"], "new")

    def test_summary_carries_no_tokens(self) -> None:
        module = load_msstore_module()
        summary = module.summarize_submission({
            "id": "1", "status": "PendingCommit", "fileUploadUrl": "https://blob/sas?sig=secret",
            "applicationPackages": [{"fileName": "a.msix", "fileStatus": "PendingUpload"}],
            "listings": {"en-US": {"baseListing": {"description": "d", "images": []}}},
        })
        self.assertNotIn("sig=secret", json.dumps(summary))
        self.assertEqual(summary["packages"], ["a.msix:PendingUpload"])


if __name__ == "__main__":
    unittest.main()
