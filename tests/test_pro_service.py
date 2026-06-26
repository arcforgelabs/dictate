"""Tests for Dictate Pro service flows."""

from __future__ import annotations

import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dictate.pro.relay import RelayResult
from dictate.pro.service import ProService, ProServiceError, ProSettings
from dictate.pro.store import TranscriptSegmentRow


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
