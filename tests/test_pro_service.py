"""Tests for Dictate Pro service flows."""

from __future__ import annotations

import os
import tempfile
import unittest
import wave
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dictate.pro.relay import RelayResult
from dictate.pro.service import ProService, ProServiceError, ProSettings
from dictate.pro.store import SubscriptionRow, TranscriptSegmentRow, iso, utcnow
from dictate.sync import PlainSyncRecord, encrypt_record, generate_account_key


class ProServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DICTATE_PRO_DEV_AUTH"] = "1"
        self.settings = ProSettings(data_dir=Path(self._tmp.name))
        self.service = ProService(self.settings)
        self.grant = self.service.grant_subscription_for_testing(email="customer@example.com")
        start = self.service.auth.start_sign_in("customer@example.com")
        session = self.service.auth.complete_sign_in(
            challenge_id=start["challenge_id"],
            code=start["dev_code"],
            device_label="Test Desktop",
        )
        self.account_id = session.account_id
        self.device_id = session.device_id

    def tearDown(self) -> None:
        self._tmp.cleanup()
        os.environ.pop("DICTATE_PRO_DEV_AUTH", None)

    def test_entitlements_and_usage_for_active_subscription(self) -> None:
        entitlements = self.service.get_entitlements(self.account_id)
        usage = self.service.get_current_usage(self.account_id)
        self.assertTrue(entitlements["active"])
        self.assertEqual(entitlements["plan_id"], "dictate_pro_monthly")
        self.assertEqual(usage["included_seconds"], 90_000)
        self.assertEqual(usage["used_seconds"], 0)

    def test_device_revocation_blocks_sync(self) -> None:
        devices = self.service.list_devices(self.account_id)["devices"]
        self.assertTrue(any(device["device_id"] == self.device_id for device in devices))

        revoked = self.service.revoke_device(self.account_id, self.device_id)

        self.assertTrue(revoked["revoked"])
        with self.assertRaises(ProServiceError) as ctx:
            self.service.get_sync_changes(self.account_id, self.device_id)
        self.assertEqual(ctx.exception.status, 403)

    def test_sync_rejects_device_mismatch(self) -> None:
        record = encrypt_record(
            "acct_local",
            generate_account_key(),
            PlainSyncRecord(
                collection="history",
                record_id="hist_1",
                rev=1,
                updated_at="2026-07-05T12:00:00+00:00",
                device_id="other_device",
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "private"},
            ),
        )

        with self.assertRaises(ProServiceError) as ctx:
            self.service.push_sync_records(self.account_id, self.device_id, [asdict(record)])
        self.assertEqual(ctx.exception.status, 403)

    def test_export_and_delete_cloud_data(self) -> None:
        record = encrypt_record(
            "acct_local",
            generate_account_key(),
            PlainSyncRecord(
                collection="history",
                record_id="hist_1",
                rev=1,
                updated_at="2026-07-05T12:00:00+00:00",
                device_id=self.device_id,
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "private"},
            ),
        )
        self.service.push_sync_records(self.account_id, self.device_id, [asdict(record)])

        exported = self.service.export_account_cloud_data(self.account_id)
        self.assertEqual(len(exported["sync_records"]), 1)

        deleted = self.service.delete_account_cloud_data(self.account_id)

        self.assertGreaterEqual(deleted["deleted"]["sync_records"], 1)
        self.assertEqual(self.service.store.list_sync_changes(account_id=self.account_id, since=0, limit=10), [])

    def test_key_envelope_requires_active_device_and_exports(self) -> None:
        saved = self.service.save_key_envelope(
            self.account_id,
            self.device_id,
            envelope_kind="recovery",
            envelope={"version": 1, "ciphertext": "opaque"},
        )

        self.assertEqual(saved["device_id"], self.device_id)
        listed = self.service.list_key_envelopes(self.account_id, self.device_id, envelope_kind="recovery")
        self.assertEqual(listed["envelopes"][0]["envelope"]["ciphertext"], "opaque")
        exported = self.service.export_account_cloud_data(self.account_id)
        self.assertEqual(exported["key_envelopes"][0]["envelope_kind"], "recovery")

        self.service.revoke_device(self.account_id, self.device_id)
        with self.assertRaises(ProServiceError) as ctx:
            self.service.save_key_envelope(
                self.account_id,
                self.device_id,
                envelope_kind="recovery",
                envelope={"version": 1, "ciphertext": "opaque"},
            )
        self.assertEqual(ctx.exception.status, 403)

    def test_meeting_upload_debits_usage_once(self) -> None:
        fake = RelayResult(
            text="Speaker 1: hello",
            segments=[
                TranscriptSegmentRow(
                    seq=0,
                    speaker_id="0",
                    speaker_label="Speaker 1",
                    text="hello",
                    t_start=0.0,
                    t_end=1.0,
                )
            ],
            audio_duration_seconds=61.2,
            billable_seconds=62,
            provider_request_id="req_test",
            raw_response={},
        )
        with patch.object(self.service._settings, "transcribe", return_value=fake):
            job = self.service.create_meeting_job(
                account_id=self.account_id,
                device_id=self.device_id,
                language="en",
            )
            wav = self._write_wav(seconds=61)
            result = self.service.upload_meeting_audio(
                account_id=self.account_id,
                job_id=job["job_id"],
                audio_path=wav,
            )
        usage = result["usage"]
        self.assertEqual(result["job"]["status"], "ready")
        self.assertEqual(usage["used_seconds"], 62)
        transcript = self.service.get_meeting_transcript(self.account_id, job["job_id"])
        self.assertIn("hello", transcript["text"])

    def test_quota_exhaustion_blocks_new_jobs(self) -> None:
        subscription = self.service.store.get_active_subscription(self.account_id)
        assert subscription is not None
        usage = self.service.store.ensure_usage_period(
            account_id=self.account_id,
            plan_id=subscription.plan_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            included_seconds=90_000,
        )
        self.service.store.reserve_usage_seconds(
            account_id=self.account_id,
            period_start=usage.period_start,
            seconds=90_000,
            hard_stop_seconds=90_000,
        )
        with self.assertRaises(ProServiceError) as ctx:
            self.service.create_meeting_job(
                account_id=self.account_id,
                device_id=self.device_id,
            )
        self.assertEqual(ctx.exception.status, 402)

    def test_concurrent_upload_claim_rejects_second_attempt(self) -> None:
        fake = RelayResult(
            text="Speaker 1: hello",
            segments=[
                TranscriptSegmentRow(
                    seq=0,
                    speaker_id="0",
                    speaker_label="Speaker 1",
                    text="hello",
                    t_start=0.0,
                    t_end=1.0,
                )
            ],
            audio_duration_seconds=61.2,
            billable_seconds=62,
            provider_request_id="req_test",
            raw_response={},
        )
        job = self.service.create_meeting_job(
            account_id=self.account_id,
            device_id=self.device_id,
            language="en",
        )
        self.assertTrue(
            self.service.store.claim_meeting_job(job["job_id"], from_statuses=("queued", "failed"), to="processing")
        )
        wav = self._write_wav(seconds=61)
        with patch.object(self.service._settings, "transcribe", return_value=fake) as transcribe:
            with self.assertRaises(ProServiceError) as ctx:
                self.service.upload_meeting_audio(
                    account_id=self.account_id,
                    job_id=job["job_id"],
                    audio_path=wav,
                )
        self.assertEqual(ctx.exception.status, 409)
        transcribe.assert_not_called()

    def test_hard_stop_does_not_clobber_ready_job_under_stale_queued_read(self) -> None:
        job = self.service.create_meeting_job(
            account_id=self.account_id,
            device_id=self.device_id,
            language="en",
        )
        self.service.store.update_meeting_job(job["job_id"], status="ready")
        subscription = self.service.store.get_active_subscription(self.account_id)
        assert subscription is not None
        usage = self.service.store.ensure_usage_period(
            account_id=self.account_id,
            plan_id=subscription.plan_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            included_seconds=90_000,
        )
        self.service.store.reserve_usage_seconds(
            account_id=self.account_id,
            period_start=usage.period_start,
            seconds=90_000,
            hard_stop_seconds=90_000,
        )
        ready_job = self.service.store.get_meeting_job(job["job_id"])
        assert ready_job is not None
        stale_queued_job = replace(ready_job, status="queued")
        wav = self._write_wav(seconds=1)
        with patch.object(self.service, "_owned_job", return_value=stale_queued_job):
            with self.assertRaises(ProServiceError) as ctx:
                self.service.upload_meeting_audio(
                    account_id=self.account_id,
                    job_id=job["job_id"],
                    audio_path=wav,
                )
        self.assertEqual(ctx.exception.status, 409)
        refreshed = self.service.store.get_meeting_job(job["job_id"])
        assert refreshed is not None
        self.assertEqual(refreshed.status, "ready")

    def test_ready_job_rejected_under_exhausted_quota_without_mutation(self) -> None:
        job = self.service.create_meeting_job(
            account_id=self.account_id,
            device_id=self.device_id,
            language="en",
        )
        self.service.store.update_meeting_job(job["job_id"], status="ready")
        subscription = self.service.store.get_active_subscription(self.account_id)
        assert subscription is not None
        usage = self.service.store.ensure_usage_period(
            account_id=self.account_id,
            plan_id=subscription.plan_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            included_seconds=90_000,
        )
        self.service.store.reserve_usage_seconds(
            account_id=self.account_id,
            period_start=usage.period_start,
            seconds=90_000,
            hard_stop_seconds=90_000,
        )
        wav = self._write_wav(seconds=1)
        with self.assertRaises(ProServiceError) as ctx:
            self.service.upload_meeting_audio(
                account_id=self.account_id,
                job_id=job["job_id"],
                audio_path=wav,
            )
        self.assertEqual(ctx.exception.status, 409)
        refreshed = self.service.store.get_meeting_job(job["job_id"])
        assert refreshed is not None
        self.assertEqual(refreshed.status, "ready")

    def test_malformed_audio_resets_job_to_failed(self) -> None:
        job = self.service.create_meeting_job(
            account_id=self.account_id,
            device_id=self.device_id,
            language="en",
        )
        bad_audio = Path(self._tmp.name) / "not-a-wav.bin"
        bad_audio.write_bytes(b"not wav data")
        with self.assertRaises(ProServiceError) as ctx:
            self.service.upload_meeting_audio(
                account_id=self.account_id,
                job_id=job["job_id"],
                audio_path=bad_audio,
            )
        self.assertEqual(ctx.exception.status, 400)
        refreshed = self.service.store.get_meeting_job(job["job_id"])
        assert refreshed is not None
        self.assertEqual(refreshed.status, "failed")
        self.assertGreater(refreshed.retry_count, 0)

    def test_expired_subscription_period_rejected_beyond_grace(self) -> None:
        subscription = self.service.store.get_active_subscription(self.account_id)
        assert subscription is not None
        expired_end = iso(utcnow() - timedelta(days=10))
        self.service.store.upsert_subscription(
            replace(subscription, current_period_end=expired_end),
        )
        os.environ["DICTATE_PRO_PERIOD_GRACE_SECONDS"] = "259200"
        try:
            with self.assertRaises(ProServiceError) as ctx:
                self.service.get_current_usage(self.account_id)
            self.assertEqual(ctx.exception.status, 403)
            self.assertIn("expired", ctx.exception.message)
        finally:
            os.environ.pop("DICTATE_PRO_PERIOD_GRACE_SECONDS", None)

    def test_subscription_within_grace_period_still_accepted(self) -> None:
        subscription = self.service.store.get_active_subscription(self.account_id)
        assert subscription is not None
        grace_end = iso(utcnow() - timedelta(days=1))
        self.service.store.upsert_subscription(
            replace(subscription, current_period_end=grace_end),
        )
        os.environ["DICTATE_PRO_PERIOD_GRACE_SECONDS"] = "259200"
        try:
            usage = self.service.get_current_usage(self.account_id)
            self.assertEqual(usage["included_seconds"], 90_000)
        finally:
            os.environ.pop("DICTATE_PRO_PERIOD_GRACE_SECONDS", None)

    def test_finalization_failure_resets_job_and_reconciles_usage(self) -> None:
        fake = RelayResult(
            text="Speaker 1: hello",
            segments=[
                TranscriptSegmentRow(
                    seq=0,
                    speaker_id="0",
                    speaker_label="Speaker 1",
                    text="hello",
                    t_start=0.0,
                    t_end=1.0,
                )
            ],
            audio_duration_seconds=61.2,
            billable_seconds=62,
            provider_request_id="req_test",
            raw_response={},
        )
        job = self.service.create_meeting_job(
            account_id=self.account_id,
            device_id=self.device_id,
            language="en",
        )
        subscription = self.service.store.get_active_subscription(self.account_id)
        assert subscription is not None
        usage_before = self.service.store.get_usage_period(
            self.account_id,
            subscription.current_period_start,
        )
        assert usage_before is not None
        initial_used = usage_before.used_seconds
        wav = self._write_wav(seconds=61)
        with patch.object(self.service._settings, "transcribe", return_value=fake):
            with patch.object(self.service.store, "save_transcript_segments", side_effect=RuntimeError("db down")):
                with self.assertRaises(ProServiceError) as ctx:
                    self.service.upload_meeting_audio(
                        account_id=self.account_id,
                        job_id=job["job_id"],
                        audio_path=wav,
                    )
        self.assertEqual(ctx.exception.status, 502)
        refreshed = self.service.store.get_meeting_job(job["job_id"])
        assert refreshed is not None
        self.assertEqual(refreshed.status, "failed")
        usage_after = self.service.store.get_usage_period(
            self.account_id,
            subscription.current_period_start,
        )
        assert usage_after is not None
        self.assertEqual(usage_after.used_seconds, initial_used)
        self.assertFalse(self.service.store.usage_event_exists(f"usage_{job['job_id']}"))

        with patch.object(self.service._settings, "transcribe", return_value=fake):
            result = self.service.upload_meeting_audio(
                account_id=self.account_id,
                job_id=job["job_id"],
                audio_path=wav,
            )
        self.assertEqual(result["job"]["status"], "ready")
        self.assertEqual(result["usage"]["used_seconds"], initial_used + 62)
        self.assertTrue(self.service.store.usage_event_exists(f"usage_{job['job_id']}"))

    def _write_wav(self, *, seconds: int) -> Path:
        path = Path(self._tmp.name) / "sample.wav"
        sample_rate = 16000
        samples = np.zeros(sample_rate * seconds, dtype=np.int16)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(samples.tobytes())
        return path


if __name__ == "__main__":
    unittest.main()
