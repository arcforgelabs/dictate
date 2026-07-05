"""Tests for Dictate Pro store and usage metering."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
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

    def test_claim_meeting_job_is_atomic(self) -> None:
        account = self.store.get_or_create_account("claim@example.com")
        job = self.store.create_meeting_job(
            account_id=account.account_id,
            device_id="dev_1",
            plan_id=DICTATE_PRO_PLAN.plan_id,
            mode="batch_meeting",
            provider="xai",
            provider_model="test",
            language=None,
            requested_diarization=True,
            billing_period_start=iso(),
            billing_period_end=iso(),
        )
        self.assertTrue(
            self.store.claim_meeting_job(job.job_id, from_statuses=("queued", "failed"), to="processing")
        )
        self.assertFalse(
            self.store.claim_meeting_job(job.job_id, from_statuses=("queued", "failed"), to="processing")
        )
        updated = self.store.get_meeting_job(job.job_id)
        assert updated is not None
        self.assertEqual(updated.status, "processing")
        self.assertIsNotNone(updated.started_at)

    def test_billing_event_exists(self) -> None:
        self.assertFalse(self.store.billing_event_exists("evt_missing"))
        self.store.record_billing_event(
            event_id="evt_exists",
            provider="stripe",
            event_type="test.event",
            payload={"id": "evt_exists"},
        )
        self.assertTrue(self.store.billing_event_exists("evt_exists"))

    def test_upsert_subscription_if_fresh_skips_stale_event(self) -> None:
        account = self.store.get_or_create_account("atomic@example.com")
        period_start = iso()
        period_end = iso()
        row = SubscriptionRow(
            account_id=account.account_id,
            stripe_subscription_id="sub_atomic",
            stripe_customer_id="cus_atomic",
            plan_id="dictate_pro_monthly",
            status="active",
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=False,
            last_event_created=2_000,
        )
        self.store.upsert_subscription(row)
        stale = replace(row, status="canceled", last_event_created=2_000)
        result = self.store.upsert_subscription_if_fresh(stale, event_created=1_000)
        self.assertEqual(result, "skipped")
        subscription = self.store.get_subscription_by_stripe_id("sub_atomic")
        assert subscription is not None
        self.assertEqual(subscription.status, "active")

    def test_upsert_subscription_if_fresh_applies_when_null_last_event(self) -> None:
        account = self.store.get_or_create_account("nullstamp@example.com")
        period_start = iso()
        period_end = iso()
        row = SubscriptionRow(
            account_id=account.account_id,
            stripe_subscription_id="sub_null",
            stripe_customer_id="cus_null",
            plan_id="dictate_pro_monthly",
            status="active",
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=False,
            last_event_created=None,
        )
        self.store.upsert_subscription(row)
        updated = replace(row, status="canceled", last_event_created=500)
        result = self.store.upsert_subscription_if_fresh(updated, event_created=500)
        self.assertEqual(result, "applied")
        subscription = self.store.get_subscription_by_stripe_id("sub_null")
        assert subscription is not None
        self.assertEqual(subscription.status, "canceled")
        self.assertEqual(subscription.last_event_created, 500)

    def test_device_revocation_marks_tokens_and_inactive(self) -> None:
        account = self.store.get_or_create_account("device@example.com")
        device_id = self.store.register_device(
            account_id=account.account_id,
            device_id="device_1",
            label="Desktop",
        )
        self.store.save_auth_token(
            token_hash="tok_1",
            account_id=account.account_id,
            device_id=device_id,
            token_type="access",
            expires_at=iso(),
        )

        revoked = self.store.revoke_device(account_id=account.account_id, device_id=device_id)

        self.assertTrue(revoked)
        self.assertFalse(self.store.device_is_active(account_id=account.account_id, device_id=device_id))
        token = self.store.get_auth_token("tok_1")
        assert token is not None
        self.assertIsNotNone(token["revoked_at"])

    def test_delete_account_cloud_data_removes_sync_and_revokes_devices(self) -> None:
        account = self.store.get_or_create_account("delete@example.com")
        device_id = self.store.register_device(
            account_id=account.account_id,
            device_id="device_1",
            label="Desktop",
        )
        self.store.upsert_sync_records(
            account_id=account.account_id,
            records=[
                {
                    "collection": "history",
                    "record_id": "hist_1",
                    "rev": 1,
                    "device_id": device_id,
                    "updated_at": "2026-07-05T12:00:00+00:00",
                    "deleted": False,
                    "content_type": "application/vnd.dictate.history+json;v=1",
                    "ciphertext": "opaque",
                    "nonce": "nonce",
                    "aad_hash": "hash",
                    "payload_bytes": 6,
                }
            ],
        )

        counts = self.store.delete_account_cloud_data(account.account_id)

        self.assertEqual(counts["sync_records"], 1)
        self.assertEqual(self.store.list_sync_changes(account_id=account.account_id, since=0, limit=10), [])
        self.assertFalse(self.store.device_is_active(account_id=account.account_id, device_id=device_id))


if __name__ == "__main__":
    unittest.main()
