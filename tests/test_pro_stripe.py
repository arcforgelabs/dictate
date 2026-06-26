"""Tests for Stripe webhook mirroring."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dictate.pro.stripe_handler import StripeSettings, StripeWebhookHandler, verify_stripe_signature
from dictate.pro.store import ProStore, SubscriptionRow, iso


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

    def test_duplicate_event_is_not_recorded_when_processing_fails(self) -> None:
        account = self.store.get_or_create_account("fail@example.com")
        self.store.link_stripe_customer(account_id=account.account_id, stripe_customer_id="cus_fail")

        class BrokenStore(ProStore):
            def upsert_subscription(self, row: SubscriptionRow) -> None:
                raise RuntimeError("simulated mutation failure")

        broken = BrokenStore(Path(self._tmp.name) / "broken.sqlite3")
        broken_account = broken.get_or_create_account("fail@example.com")
        broken.link_stripe_customer(account_id=broken_account.account_id, stripe_customer_id="cus_fail")
        handler = StripeWebhookHandler(
            broken,
            StripeSettings(webhook_secret="whsec_test", price_to_plan={"price_pro": "dictate_pro_monthly"}),
        )
        event = {
            "id": "sub_fail",
            "customer": "cus_fail",
            "status": "active",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_700_086_400,
            "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        }
        with self.assertRaises(RuntimeError):
            handler.handle(event_id="evt_fail_1", event_type="customer.subscription.created", payload=event)
        self.assertFalse(broken.billing_event_exists("evt_fail_1"))

        working = StripeWebhookHandler(
            self.store,
            StripeSettings(webhook_secret="whsec_test", price_to_plan={"price_pro": "dictate_pro_monthly"}),
        )
        result = working.handle(event_id="evt_fail_1", event_type="customer.subscription.created", payload=event)
        self.assertEqual(result["status"], "ok")

    def test_stale_subscription_event_is_skipped(self) -> None:
        account = self.store.get_or_create_account("stale@example.com")
        self.store.link_stripe_customer(account_id=account.account_id, stripe_customer_id="cus_stale")
        period_start = iso()
        period_end = iso()
        self.store.upsert_subscription(
            SubscriptionRow(
                account_id=account.account_id,
                stripe_subscription_id="sub_stale",
                stripe_customer_id="cus_stale",
                plan_id="dictate_pro_monthly",
                status="canceled",
                current_period_start=period_start,
                current_period_end=period_end,
                cancel_at_period_end=True,
                last_event_created=2_000,
            )
        )
        stale_event = {
            "id": "sub_stale",
            "customer": "cus_stale",
            "status": "active",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_700_086_400,
            "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        }
        result = self.handler.handle(
            event_id="evt_stale",
            event_type="customer.subscription.updated",
            payload=stale_event,
            event_created=1_000,
        )
        self.assertEqual(result["status"], "skipped")
        subscription = self.store.get_subscription_by_stripe_id("sub_stale")
        assert subscription is not None
        self.assertEqual(subscription.status, "canceled")

    def test_newer_subscription_event_updates_stored_state(self) -> None:
        account = self.store.get_or_create_account("fresh@example.com")
        self.store.link_stripe_customer(account_id=account.account_id, stripe_customer_id="cus_fresh")
        period_start = iso()
        period_end = iso()
        self.store.upsert_subscription(
            SubscriptionRow(
                account_id=account.account_id,
                stripe_subscription_id="sub_fresh",
                stripe_customer_id="cus_fresh",
                plan_id="dictate_pro_monthly",
                status="canceled",
                current_period_start=period_start,
                current_period_end=period_end,
                cancel_at_period_end=True,
                last_event_created=1_000,
            )
        )
        newer_event = {
            "id": "sub_fresh",
            "customer": "cus_fresh",
            "status": "active",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_700_086_400,
            "cancel_at_period_end": False,
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        }
        result = self.handler.handle(
            event_id="evt_fresh",
            event_type="customer.subscription.updated",
            payload=newer_event,
            event_created=2_000,
        )
        self.assertEqual(result["status"], "ok")
        subscription = self.store.get_subscription_by_stripe_id("sub_fresh")
        assert subscription is not None
        self.assertEqual(subscription.status, "active")
        self.assertEqual(subscription.last_event_created, 2_000)


if __name__ == "__main__":
    unittest.main()
