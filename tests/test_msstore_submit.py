from __future__ import annotations

import importlib.util
import io
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


if __name__ == "__main__":
    unittest.main()
