"""Dictate Pro business logic: entitlements, usage, and meeting jobs."""

from __future__ import annotations

import json
import logging
import os
import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_PERIOD_GRACE_SECONDS = 259_200  # 3 days
MAX_SYNC_PAYLOAD_BYTES = 5 * 1024 * 1024

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
                "sync": False,
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
                "sync": True,
            },
        }

    def push_sync_records(self, account_id: str, device_id: str | None, records: list[dict[str, Any]]) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_active_device(account_id, device_id)
        if not isinstance(records, list):
            raise ProServiceError(400, "records must be a list")
        if len(records) > 500:
            raise ProServiceError(413, "too many sync records")
        for record in records:
            if isinstance(record, dict) and str(record.get("device_id") or "") != str(device_id or ""):
                raise ProServiceError(403, "sync record device mismatch")
            try:
                payload_bytes = int(record.get("payload_bytes") or 0) if isinstance(record, dict) else 0
            except (TypeError, ValueError) as exc:
                raise ProServiceError(400, "invalid sync payload size") from exc
            if payload_bytes > MAX_SYNC_PAYLOAD_BYTES:
                raise ProServiceError(413, "sync payload too large")
        try:
            results = self.store.upsert_sync_records(account_id=account_id, records=records)
        except ValueError as exc:
            raise ProServiceError(400, str(exc)) from exc
        return {"results": results}

    def get_sync_changes(self, account_id: str, device_id: str | None, *, since: int = 0, limit: int = 500) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_active_device(account_id, device_id)
        rows = self.store.list_sync_changes(account_id=account_id, since=since, limit=limit)
        records = [
            {
                "collection": row.collection,
                "record_id": row.record_id,
                "seq": row.seq,
                "rev": row.rev,
                "device_id": row.device_id,
                "updated_at": row.updated_at,
                "deleted": row.deleted,
                "content_type": row.content_type,
                "ciphertext": row.ciphertext,
                "nonce": row.nonce,
                "aad_hash": row.aad_hash,
                "payload_bytes": row.payload_bytes,
            }
            for row in rows
        ]
        next_seq = records[-1]["seq"] if records else max(0, since)
        return {"next_seq": next_seq, "has_more": len(records) >= max(1, min(limit, 1000)), "records": records}

    def update_sync_cursor(self, account_id: str, device_id: str | None, *, last_seq: int) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_active_device(account_id, device_id)
        try:
            row = self.store.set_sync_cursor(
                account_id=account_id,
                device_id=str(device_id),
                last_seq=last_seq,
            )
        except ValueError as exc:
            raise ProServiceError(400, str(exc)) from exc
        return {
            "account_id": row.account_id,
            "device_id": row.device_id,
            "last_seq": row.last_seq,
            "updated_at": row.updated_at,
        }

    def save_key_envelope(
        self,
        account_id: str,
        device_id: str | None,
        *,
        envelope_kind: str,
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_active_device(account_id, device_id)
        if not isinstance(envelope, dict) or not envelope:
            raise ProServiceError(400, "envelope must be a JSON object")
        try:
            row = self.store.save_key_envelope(
                account_id=account_id,
                device_id=str(device_id),
                envelope_kind=envelope_kind,
                envelope=envelope,
            )
        except ValueError as exc:
            raise ProServiceError(400, str(exc)) from exc
        return self._key_envelope_payload(row)

    def list_key_envelopes(
        self,
        account_id: str,
        device_id: str | None,
        *,
        envelope_kind: str | None = None,
    ) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        if envelope_kind == "recovery":
            self._require_known_device(account_id, device_id)
        else:
            self._require_active_device(account_id, device_id)
        envelopes = [
            self._key_envelope_payload(row)
            for row in self.store.list_key_envelopes(account_id=account_id, envelope_kind=envelope_kind)
        ]
        return {"envelopes": envelopes}

    def list_devices(self, account_id: str) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        return {
            "devices": [
                self._device_payload(device)
                for device in self.store.list_devices(account_id)
            ]
        }

    def register_device(
        self,
        account_id: str,
        current_device_id: str | None,
        *,
        device_id: str | None,
        device_label: str,
        device_public_key: str,
    ) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_known_device(account_id, current_device_id)
        target = (device_id or current_device_id or "").strip()
        current = (current_device_id or "").strip()
        if not target:
            raise ProServiceError(400, "device_id is required")
        if target != current:
            raise ProServiceError(403, "cannot register a different device from this session")
        public_key = device_public_key.strip()
        if not public_key:
            raise ProServiceError(400, "device_public_key is required")
        label = device_label.strip() or "Desktop"
        registered = self.store.register_device(
            account_id=account_id,
            device_id=target,
            label=label,
            public_key=public_key,
        )
        device = self.store.get_device(account_id=account_id, device_id=registered)
        return {"device": self._device_payload(device)}

    def revoke_device(self, account_id: str, current_device_id: str | None, device_id: str) -> dict[str, Any]:
        if not device_id.strip():
            raise ProServiceError(400, "device_id is required")
        self._require_active_subscription(account_id)
        self._require_active_device(account_id, current_device_id)
        if not self.store.revoke_device(account_id=account_id, device_id=device_id.strip()):
            raise ProServiceError(404, "device not found")
        return {"revoked": True, "device_id": device_id.strip()}

    def approve_device(
        self,
        account_id: str,
        approving_device_id: str | None,
        target_device_id: str,
        *,
        envelope: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_active_device(account_id, approving_device_id)
        target = target_device_id.strip()
        if not target:
            raise ProServiceError(400, "device_id is required")
        if envelope is not None:
            if not isinstance(envelope, dict) or not envelope:
                raise ProServiceError(400, "envelope must be a JSON object")
            try:
                self.store.save_key_envelope(
                    account_id=account_id,
                    device_id=target,
                    envelope_kind="device",
                    envelope=envelope,
                )
            except ValueError as exc:
                raise ProServiceError(400, str(exc)) from exc
        if not self.store.approve_device(account_id=account_id, device_id=target):
            raise ProServiceError(404, "device not found")
        device = self.store.get_device(account_id=account_id, device_id=target)
        return {"approved": True, "device": self._device_payload(device)}

    def approve_current_device_with_recovery(self, account_id: str, device_id: str | None) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_known_device(account_id, device_id)
        if not self.store.approve_device(account_id=account_id, device_id=str(device_id)):
            raise ProServiceError(404, "device not found")
        device = self.store.get_device(account_id=account_id, device_id=str(device_id))
        return {"approved": True, "device": self._device_payload(device), "method": "recovery"}

    def export_account_cloud_data(self, account_id: str, device_id: str | None) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_active_device(account_id, device_id)
        data = self.store.export_account_cloud_data(account_id)
        if not data:
            raise ProServiceError(404, "account not found")
        return data

    def delete_account_cloud_data(self, account_id: str, device_id: str | None) -> dict[str, Any]:
        self._require_active_subscription(account_id)
        self._require_active_device(account_id, device_id)
        return {"deleted": self.store.delete_account_cloud_data(account_id)}

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
        payload = self._usage_payload(usage)
        payload["sync"] = self.store.get_sync_storage_usage(account_id)
        return payload

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
        if job.status not in {"queued", "failed"}:
            raise ProServiceError(409, f"meeting job is not accepting audio in status {job.status}")

        subscription = self._require_active_subscription(account_id)
        plan = plan_for_id(subscription.plan_id) or DICTATE_PRO_PLAN
        self.store.ensure_usage_period(
            account_id=account_id,
            plan_id=plan.plan_id,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            included_seconds=plan.included_batch_meeting_seconds,
        )

        if not self.store.claim_meeting_job(job_id, from_statuses=("queued", "failed"), to="processing"):
            refreshed = self.store.get_meeting_job(job_id)
            status = refreshed.status if refreshed else job.status
            raise ProServiceError(409, f"meeting job is not accepting audio in status {status}")

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

        reserved_seconds = 0
        try:
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
            reserved_seconds = estimated_seconds
            result = self._settings.transcribe(
                audio_path,
                language=job.language,
                hotwords=hotwords,
                diarize=job.requested_diarization,
            )
        except ProServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            if reserved_seconds:
                self.store.release_usage_seconds(
                    account_id=account_id,
                    period_start=subscription.current_period_start,
                    seconds=reserved_seconds,
                )
            self.store.update_meeting_job(
                job_id,
                status="failed",
                error=str(exc),
                retry_count=job.retry_count + 1,
                completed_at=iso(),
            )
            if reserved_seconds:
                raise ProServiceError(502, f"transcription failed: {exc}") from exc
            raise ProServiceError(400, f"unreadable audio: {exc}") from exc

        usage_delta = result.billable_seconds - estimated_seconds
        usage_delta_applied = 0
        usage_event_id = f"usage_{job_id}"
        try:
            if usage_delta != 0:
                self.store.adjust_usage_seconds(
                    account_id=account_id,
                    period_start=subscription.current_period_start,
                    seconds=usage_delta,
                )
                usage_delta_applied = usage_delta

            self.store.record_usage_event(
                event_id=usage_event_id,
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
        except Exception as exc:  # noqa: BLE001
            self.store.delete_usage_event(usage_event_id)
            net_charged = reserved_seconds + usage_delta_applied
            if net_charged:
                self.store.release_usage_seconds(
                    account_id=account_id,
                    period_start=subscription.current_period_start,
                    seconds=net_charged,
                )
            self.store.update_meeting_job(
                job_id,
                status="failed",
                error=f"finalization failed: {exc}",
                retry_count=job.retry_count + 1,
                completed_at=iso(),
            )
            raise ProServiceError(502, f"transcription finalization failed: {exc}") from exc

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
        if self._subscription_period_expired(subscription):
            raise ProServiceError(403, "Dictate Pro subscription period has expired.")
        return subscription

    def _require_active_device(self, account_id: str, device_id: str | None) -> None:
        if not self.store.device_is_active(account_id=account_id, device_id=device_id):
            raise ProServiceError(403, "device is not trusted for sync")

    def _require_known_device(self, account_id: str, device_id: str | None) -> None:
        if not self.store.device_is_known(account_id=account_id, device_id=device_id):
            raise ProServiceError(403, "device is not registered")

    def _subscription_period_expired(self, subscription: SubscriptionRow) -> bool:
        grace_seconds = int(os.environ.get("DICTATE_PRO_PERIOD_GRACE_SECONDS", str(DEFAULT_PERIOD_GRACE_SECONDS)))
        period_end = self._parse_period_end(subscription.current_period_end)
        if period_end is None:
            return False
        deadline = period_end + timedelta(seconds=max(0, grace_seconds))
        return datetime.now(timezone.utc) > deadline

    @staticmethod
    def _parse_period_end(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("unable to parse subscription current_period_end: %r", value)
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

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

    def _device_payload(self, device) -> dict[str, Any] | None:
        if device is None:
            return None
        return {
            "account_id": device.account_id,
            "device_id": device.device_id,
            "label": device.label,
            "public_key": device.public_key,
            "created_at": device.created_at,
            "trusted_at": device.trusted_at,
            "revoked_at": device.revoked_at,
            "last_seen_at": device.last_seen_at,
            "signed_metadata": self._device_signed_metadata(device),
            "server_signature": device.signature,
        }

    def _device_signed_metadata(self, device) -> dict[str, Any]:
        return {
            "metadata_type": "dictate.pro.device",
            "account_id": device.account_id,
            "device_id": device.device_id,
            "label": device.label,
            "public_key": device.public_key,
            "created_at": device.created_at,
            "trusted_at": device.trusted_at,
            "revoked_at": device.revoked_at,
        }

    def _key_envelope_payload(self, row) -> dict[str, Any]:
        return {
            "account_id": row.account_id,
            "device_id": row.device_id,
            "envelope_kind": row.envelope_kind,
            "envelope": json.loads(row.envelope_json),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "signed_metadata": self._key_envelope_signed_metadata(row),
            "server_signature": row.signature,
        }

    def _key_envelope_signed_metadata(self, row) -> dict[str, Any]:
        return {
            "metadata_type": "dictate.pro.key_envelope",
            "account_id": row.account_id,
            "device_id": row.device_id,
            "envelope_kind": row.envelope_kind,
            "envelope_hash": hashlib.sha256(row.envelope_json.encode("utf-8")).hexdigest(),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
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
