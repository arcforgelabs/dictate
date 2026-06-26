"""Dictate Pro business logic: entitlements, usage, and meeting jobs."""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dictate.pro.auth import ProAuth
from dictate.pro.plans import DICTATE_PRO_PLAN, USAGE_THRESHOLDS, plan_for_id, usage_level
from dictate.pro.relay import (
    RelayResult,
    audio_duration_seconds,
    billable_seconds_for_duration,
    transcribe_meeting_file,
)
from dictate.pro.store import MeetingJobRow, ProStore, SubscriptionRow, iso
from dictate.pro.stripe_handler import StripeSettings, StripeWebhookHandler


class ProServiceError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(slots=True)
class ProSettings:
    data_dir: Path
    stripe_settings: StripeSettings | None = None
    transcribe: Callable[..., RelayResult] = transcribe_meeting_file


class ProService:
    def __init__(self, settings: ProSettings) -> None:
        self._settings = settings
        db_path = settings.data_dir / "pro-control-plane.sqlite3"
        self.store = ProStore(db_path)
        self.auth = ProAuth(self.store)
        self.stripe = StripeWebhookHandler(self.store, settings.stripe_settings)

    def grant_subscription_for_testing(
        self,
        *,
        email: str,
        status: str = "active",
        period_days: int = 30,
    ) -> dict[str, Any]:
        from datetime import timedelta

        from dictate.pro.store import utcnow

        account = self.store.get_or_create_account(email)
        now = utcnow()
        period_start = iso(now)
        period_end = iso(now + timedelta(days=period_days))
        subscription_id = f"sub_test_{uuid.uuid4().hex[:12]}"
        customer_id = account.stripe_customer_id or f"cus_test_{uuid.uuid4().hex[:12]}"
        if not account.stripe_customer_id:
            self.store.link_stripe_customer(account_id=account.account_id, stripe_customer_id=customer_id)
        row = SubscriptionRow(
            account_id=account.account_id,
            stripe_subscription_id=subscription_id,
            stripe_customer_id=customer_id,
            plan_id=DICTATE_PRO_PLAN.plan_id,
            status=status,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=False,
        )
        self.store.upsert_subscription(row)
        usage = self.store.ensure_usage_period(
            account_id=account.account_id,
            plan_id=DICTATE_PRO_PLAN.plan_id,
            period_start=period_start,
            period_end=period_end,
            included_seconds=DICTATE_PRO_PLAN.included_batch_meeting_seconds,
        )
        return {
            "account_id": account.account_id,
            "email": account.email,
            "subscription_status": status,
            "usage_period": self._usage_payload(usage),
        }

    def get_me(self, account_id: str) -> dict[str, Any]:
        account = self.store.get_account(account_id)
        if account is None:
            raise ProServiceError(404, "account not found")
        subscription = self.store.get_active_subscription(account_id)
        return {
            "account_id": account.account_id,
            "email": account.email,
            "subscription": self._subscription_payload(subscription),
        }

    def get_entitlements(self, account_id: str) -> dict[str, Any]:
        subscription = self.store.get_active_subscription(account_id)
        if subscription is None:
            return {
                "active": False,
                "plan_id": None,
                "features": {
                    "hosted_meeting_transcription": False,
                    "diarization": False,
                    "streaming_dictation": False,
                },
            }
        plan = plan_for_id(subscription.plan_id) or DICTATE_PRO_PLAN
        return {
            "active": subscription.status in {"active", "trialing", "past_due"},
            "plan_id": plan.plan_id,
            "display_name": plan.display_name,
            "status": subscription.status,
            "period_start": subscription.current_period_start,
            "period_end": subscription.current_period_end,
            "features": {
                "hosted_meeting_transcription": True,
                "diarization": plan.diarization,
                "streaming_dictation": plan.included_streaming_seconds > 0,
                "provider": plan.provider,
                "stt_mode": plan.stt_mode,
                "provider_model": plan.provider_model,
            },
        }

    def get_current_usage(self, account_id: str) -> dict[str, Any]:
        subscription = self._require_active_subscription(account_id)
        plan = plan_for_id(subscription.plan_id) or DICTATE_PRO_PLAN
        usage = self.store.ensure_usage_period(
            account_id=account_id,
            plan_id=plan.plan_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            included_seconds=plan.included_batch_meeting_seconds,
        )
        return self._usage_payload(usage)

    def create_meeting_job(
        self,
        *,
        account_id: str,
        device_id: str,
        language: str | None = None,
        mode: str = "batch_meeting",
    ) -> dict[str, Any]:
        subscription = self._require_active_subscription(account_id)
        plan = plan_for_id(subscription.plan_id) or DICTATE_PRO_PLAN
        usage = self.store.ensure_usage_period(
            account_id=account_id,
            plan_id=plan.plan_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            included_seconds=plan.included_batch_meeting_seconds,
        )
        if usage.used_seconds >= USAGE_THRESHOLDS.hard_stop_seconds:
            raise ProServiceError(402, "Dictate Pro hosted meeting allowance exhausted for this billing period.")
        job = self.store.create_meeting_job(
            account_id=account_id,
            device_id=device_id,
            plan_id=plan.plan_id,
            mode=mode,
            provider=plan.provider,
            provider_model=plan.provider_model,
            language=language,
            requested_diarization=plan.diarization,
            billing_period_start=subscription.current_period_start,
            billing_period_end=subscription.current_period_end,
        )
        return self._meeting_payload(job)

    def upload_meeting_audio(
        self,
        *,
        account_id: str,
        job_id: str,
        audio_path: Path,
        hotwords: str | None = None,
    ) -> dict[str, Any]:
        job = self._owned_job(account_id, job_id)

        subscription = self._require_active_subscription(account_id)
        plan = plan_for_id(subscription.plan_id) or DICTATE_PRO_PLAN
        usage = self.store.ensure_usage_period(
            account_id=account_id,
            plan_id=plan.plan_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            included_seconds=plan.included_batch_meeting_seconds,
        )
        if usage.used_seconds >= USAGE_THRESHOLDS.hard_stop_seconds:
            self.store.update_meeting_job(job_id, status="quota_exceeded", error="quota exhausted")
            raise ProServiceError(402, "Dictate Pro hosted meeting allowance exhausted for this billing period.")

        if not self.store.claim_meeting_job(job_id, from_statuses=("queued", "failed"), to="processing"):
            refreshed = self.store.get_meeting_job(job_id)
            status = refreshed.status if refreshed else job.status
            raise ProServiceError(409, f"meeting job is not accepting audio in status {status}")

        probed_duration = audio_duration_seconds(audio_path)
        estimated_seconds = billable_seconds_for_duration(probed_duration)
        if not self.store.reserve_usage_seconds(
            account_id=account_id,
            period_start=subscription.current_period_start,
            seconds=estimated_seconds,
            hard_stop_seconds=USAGE_THRESHOLDS.hard_stop_seconds,
        ):
            self.store.update_meeting_job(
                job_id,
                status="quota_exceeded",
                audio_duration_seconds=probed_duration,
                error="quota exhausted",
                completed_at=iso(),
            )
            raise ProServiceError(402, "Dictate Pro hosted meeting allowance exhausted for this billing period.")

        try:
            result = self._settings.transcribe(
                audio_path,
                language=job.language,
                hotwords=hotwords,
                diarize=job.requested_diarization,
            )
        except Exception as exc:  # noqa: BLE001
            self.store.release_usage_seconds(
                account_id=account_id,
                period_start=subscription.current_period_start,
                seconds=estimated_seconds,
            )
            self.store.update_meeting_job(
                job_id,
                status="failed",
                error=str(exc),
                retry_count=job.retry_count + 1,
                completed_at=iso(),
            )
            raise ProServiceError(502, f"transcription failed: {exc}") from exc

        usage_delta = result.billable_seconds - estimated_seconds
        if usage_delta != 0:
            self.store.adjust_usage_seconds(
                account_id=account_id,
                period_start=subscription.current_period_start,
                seconds=usage_delta,
            )

        event_id = f"usage_{job_id}"
        self.store.record_usage_event(
            event_id=event_id,
            account_id=account_id,
            job_id=job_id,
            billable_seconds=result.billable_seconds,
            period_start=subscription.current_period_start,
        )
        self.store.save_transcript_segments(job_id, result.segments)
        self.store.update_meeting_job(
            job_id,
            status="ready",
            audio_duration_seconds=result.audio_duration_seconds,
            billable_seconds=result.billable_seconds,
            provider_request_id=result.provider_request_id,
            completed_at=iso(),
            error=None,
        )
        updated = self.store.get_meeting_job(job_id)
        return {
            "job": self._meeting_payload(updated),  # type: ignore[arg-type]
            "usage": self.get_current_usage(account_id),
            "text": result.text,
        }

    def get_meeting_job(self, account_id: str, job_id: str) -> dict[str, Any]:
        job = self._owned_job(account_id, job_id)
        return self._meeting_payload(job)

    def get_meeting_transcript(self, account_id: str, job_id: str) -> dict[str, Any]:
        job = self._owned_job(account_id, job_id)
        segments = self.store.get_transcript_segments(job_id)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "segments": [
                {
                    "seq": segment.seq,
                    "speaker_id": segment.speaker_id,
                    "speaker_label": segment.speaker_label,
                    "text": segment.text,
                    "t_start": segment.t_start,
                    "t_end": segment.t_end,
                }
                for segment in segments
            ],
            "text": "\n".join(f"{segment.speaker_label}: {segment.text}" for segment in segments),
        }

    def save_uploaded_audio(self, suffix: str, payload: bytes) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="dictate-pro-upload-"))
        path = temp_dir / f"audio{suffix}"
        path.write_bytes(payload)
        return path

    def _require_active_subscription(self, account_id: str) -> SubscriptionRow:
        subscription = self.store.get_active_subscription(account_id)
        if subscription is None:
            raise ProServiceError(403, "Dictate Pro subscription required.")
        # past_due is intentionally treated as an active grace state while Stripe retries payment.
        if subscription.status not in {"active", "trialing", "past_due"}:
            raise ProServiceError(403, "Dictate Pro subscription is not active.")
        return subscription

    def _owned_job(self, account_id: str, job_id: str) -> MeetingJobRow:
        job = self.store.get_meeting_job(job_id)
        if job is None or job.account_id != account_id:
            raise ProServiceError(404, "meeting job not found")
        return job

    def _subscription_payload(self, subscription: SubscriptionRow | None) -> dict[str, Any] | None:
        if subscription is None:
            return None
        return {
            "plan_id": subscription.plan_id,
            "status": subscription.status,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
            "cancel_at_period_end": subscription.cancel_at_period_end,
        }

    def _usage_payload(self, usage) -> dict[str, Any]:
        remaining = max(0, usage.included_seconds - usage.used_seconds)
        return {
            "plan_id": usage.plan_id,
            "period_start": usage.period_start,
            "period_end": usage.period_end,
            "included_seconds": usage.included_seconds,
            "used_seconds": usage.used_seconds,
            "remaining_seconds": remaining,
            "level": usage_level(usage.used_seconds, usage.included_seconds),
            "warnings": {
                "twenty_hours": usage.used_seconds >= USAGE_THRESHOLDS.warn_seconds[0],
                "twenty_four_hours": usage.used_seconds >= USAGE_THRESHOLDS.warn_seconds[1],
                "exhausted": usage.used_seconds >= USAGE_THRESHOLDS.hard_stop_seconds,
            },
        }

    def _meeting_payload(self, job: MeetingJobRow) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "mode": job.mode,
            "provider": job.provider,
            "provider_model": job.provider_model,
            "language": job.language,
            "requested_diarization": job.requested_diarization,
            "audio_duration_seconds": job.audio_duration_seconds,
            "billable_seconds": job.billable_seconds,
            "billing_period_start": job.billing_period_start,
            "billing_period_end": job.billing_period_end,
            "provider_request_id": job.provider_request_id,
            "error": job.error,
            "retry_count": job.retry_count,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
        }
