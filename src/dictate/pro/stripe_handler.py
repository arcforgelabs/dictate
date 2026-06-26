"""Stripe webhook handling for Dictate Pro subscription mirroring."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from dictate.pro.plans import DICTATE_PRO_PLAN, STRIPE_PRICE_TO_PLAN, plan_for_stripe_price
from dictate.pro.store import ProStore, SubscriptionRow, iso


@dataclass(slots=True)
class StripeSettings:
    webhook_secret: str
    price_to_plan: dict[str, str]


def load_stripe_settings() -> StripeSettings:
    secret = os.environ.get("DICTATE_PRO_STRIPE_WEBHOOK_SECRET", "").strip()
    mapping = dict(STRIPE_PRICE_TO_PLAN)
    raw = os.environ.get("DICTATE_PRO_STRIPE_PRICE_TO_PLAN_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                mapping.update({str(k): str(v) for k, v in parsed.items()})
        except json.JSONDecodeError:
            pass
    return StripeSettings(webhook_secret=secret, price_to_plan=mapping)


def verify_stripe_signature(payload: bytes, signature_header: str, secret: str, *, tolerance: int = 300) -> bool:
    if not secret:
        return False
    parts: dict[str, str] = {}
    for item in signature_header.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts[key.strip()] = value.strip()
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > tolerance:
        return False
    signed = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class StripeWebhookHandler:
    def __init__(self, store: ProStore, settings: StripeSettings | None = None) -> None:
        self._store = store
        self._settings = settings or load_stripe_settings()

    def handle(self, *, event_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._store.record_billing_event(
            event_id=event_id,
            provider="stripe",
            event_type=event_type,
            payload=payload,
        ):
            return {"status": "duplicate", "event_id": event_id}

        if event_type.startswith("customer.subscription."):
            return self._handle_subscription_event(payload)
        if event_type == "checkout.session.completed":
            return self._handle_checkout_completed(payload)
        return {"status": "ignored", "event_type": event_type}

    def _handle_checkout_completed(self, payload: dict[str, Any]) -> dict[str, Any]:
        customer_id = _string(payload.get("customer"))
        email = _string(payload.get("customer_details", {}).get("email") if isinstance(payload.get("customer_details"), dict) else None)
        if not customer_id:
            return {"status": "ignored", "reason": "missing customer"}
        account = None
        if email:
            account = self._store.get_or_create_account(email)
            self._store.link_stripe_customer(account_id=account.account_id, stripe_customer_id=customer_id)
        return {"status": "ok", "linked_customer": customer_id, "account_id": account.account_id if account else None}

    def _handle_subscription_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        subscription_id = _string(payload.get("id"))
        customer_id = _string(payload.get("customer"))
        status = _string(payload.get("status")) or "unknown"
        if not subscription_id or not customer_id:
            return {"status": "ignored", "reason": "missing subscription or customer"}

        account = self._store.get_account_by_stripe_customer(customer_id)
        if account is None:
            email = _extract_customer_email(payload)
            if email:
                account = self._store.get_or_create_account(email)
                self._store.link_stripe_customer(account_id=account.account_id, stripe_customer_id=customer_id)
        if account is None:
            return {"status": "ignored", "reason": "account not found"}

        plan_id = self._resolve_plan_id(payload)
        period_start, period_end = _period_bounds(payload)
        row = SubscriptionRow(
            account_id=account.account_id,
            stripe_subscription_id=subscription_id,
            stripe_customer_id=customer_id,
            plan_id=plan_id,
            status=status,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=bool(payload.get("cancel_at_period_end")),
        )
        self._store.upsert_subscription(row)
        if status in {"active", "trialing", "past_due"}:
            plan = plan_for_stripe_price(self._price_id(payload)) or DICTATE_PRO_PLAN
            self._store.ensure_usage_period(
                account_id=account.account_id,
                plan_id=plan.plan_id,
                period_start=period_start,
                period_end=period_end,
                included_seconds=plan.included_batch_meeting_seconds,
            )
        return {"status": "ok", "account_id": account.account_id, "plan_id": plan_id, "subscription_status": status}

    def _resolve_plan_id(self, payload: dict[str, Any]) -> str:
        price_id = self._price_id(payload)
        if price_id:
            mapped = self._settings.price_to_plan.get(price_id) or (
                plan_for_stripe_price(price_id).plan_id if plan_for_stripe_price(price_id) else None
            )
            if mapped:
                return mapped
        return DICTATE_PRO_PLAN.plan_id

    def _price_id(self, payload: dict[str, Any]) -> str | None:
        items = payload.get("items")
        if not isinstance(items, dict):
            return None
        data = items.get("data")
        if not isinstance(data, list) or not data:
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        price = first.get("price")
        if isinstance(price, dict):
            return _string(price.get("id"))
        return None


def _extract_customer_email(payload: dict[str, Any]) -> str | None:
    customer = payload.get("customer_details")
    if isinstance(customer, dict):
        email = _string(customer.get("email"))
        if email:
            return email
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        return _string(metadata.get("email"))
    return None


def _period_bounds(payload: dict[str, Any]) -> tuple[str, str]:
    start = payload.get("current_period_start")
    end = payload.get("current_period_end")
    if isinstance(start, int) and isinstance(end, int):
        return iso_from_epoch(start), iso_from_epoch(end)
    return iso(), iso()


def iso_from_epoch(value: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat()


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
