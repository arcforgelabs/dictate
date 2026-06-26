"""Tests for Dictate Pro store and usage metering."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dictate.pro.plans import DICTATE_PRO_PLAN, USAGE_THRESHOLDS
from dictate.pro.store import ProStore, SubscriptionRow, iso


class ProStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ProStore(Path(self._tmp.name) / "pro.sqlite3")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_grant_and_usage_reservation(self) -> None:
        account = self.store.get_or_create_account("pro@example.com")
        period_start = iso()
        period_end = iso()
        self.store.upsert_subscription(
            SubscriptionRow(
                account_id=account.account_id,
                stripe_subscription_id="sub_test",
                stripe_customer_id="cus_test",
                plan_id=DICTATE_PRO_PLAN.plan_id,
                status="active",
                current_period_start=period_start,
                current_period_end=period_end,
                cancel_at_period_end=False,
            )
        )
        usage = self.store.ensure_usage_period(
            account_id=account.account_id,
            plan_id=DICTATE_PRO_PLAN.plan_id,
            period_start=period_start,
            period_end=period_end,
            included_seconds=DICTATE_PRO_PLAN.included_batch_meeting_seconds,
        )
        self.assertEqual(usage.used_seconds, 0)
        self.assertTrue(
            self.store.reserve_usage_seconds(
                account_id=account.account_id,
                period_start=period_start,
                seconds=3600,
                hard_stop_seconds=USAGE_THRESHOLDS.hard_stop_seconds,
            )
        )
        updated = self.store.get_usage_period(account.account_id, period_start)
        assert updated is not None
        self.assertEqual(updated.used_seconds, 3600)

    def test_usage_event_is_idempotent(self) -> None:
        account = self.store.get_or_create_account("meter@example.com")
        first = self.store.record_usage_event(
            event_id="evt_1",
            account_id=account.account_id,
            job_id="mtg_1",
            billable_seconds=120,
            period_start=iso(),
        )
        second = self.store.record_usage_event(
            event_id="evt_1",
            account_id=account.account_id,
            job_id="mtg_1",
            billable_seconds=120,
            period_start=iso(),
        )
        self.assertTrue(first)
        self.assertFalse(second)


if __name__ == "__main__":
    unittest.main()
