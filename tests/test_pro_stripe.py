"""Tests for Stripe webhook mirroring."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dictate.pro.stripe_handler import StripeSettings, StripeWebhookHandler, verify_stripe_signature
from dictate.pro.store import ProStore


class StripeWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ProStore(Path(self._tmp.name) / "pro.sqlite3")
        self.handler = StripeWebhookHandler(
            self.store,
            StripeSettings(
                webhook_secret="whsec_test",
                price_to_plan={"price_pro": "dictate_pro_monthly"},
            ),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_signature_verification(self) -> None:
        payload = b'{"id":"evt_1","type":"test"}'
        import hashlib
        import hmac
        import time

        timestamp = str(int(time.time()))
        signed = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
        signature = hmac.new(b"whsec_test", signed, hashlib.sha256).hexdigest()
        header = f"t={timestamp},v1={signature}"
        self.assertTrue(verify_stripe_signature(payload, header, "whsec_test"))

    def test_subscription_created_grants_entitlement(self) -> None:
        account = self.store.get_or_create_account("stripe@example.com")
        self.store.link_stripe_customer(account_id=account.account_id, stripe_customer_id="cus_123")
        event = {
            "id": "sub_123",
            "customer": "cus_123",
            "status": "active",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_700_086_400,
            "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        }
        result = self.handler.handle(event_id="evt_sub_1", event_type="customer.subscription.created", payload=event)
        self.assertEqual(result["status"], "ok")
        subscription = self.store.get_active_subscription(account.account_id)
        self.assertIsNotNone(subscription)
        assert subscription is not None
        self.assertEqual(subscription.plan_id, "dictate_pro_monthly")


if __name__ == "__main__":
    unittest.main()
