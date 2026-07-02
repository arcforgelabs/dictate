"""Dictate Pro plan definitions and usage thresholds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanDefinition:
    plan_id: str
    display_name: str
    included_batch_meeting_seconds: int
    included_streaming_seconds: int
    provider: str
    stt_mode: str
    provider_model: str
    diarization: bool


@dataclass(frozen=True, slots=True)
class UsageThresholds:
    warn_seconds: tuple[int, ...]
    hard_stop_seconds: int


DICTATE_PRO_PLAN = PlanDefinition(
    plan_id="dictate_pro_monthly",
    display_name="Dictate Pro",
    included_batch_meeting_seconds=90_000,
    included_streaming_seconds=0,
    provider="xai",
    stt_mode="rest_batch",
    provider_model="grok-speech-to-text",
    diarization=True,
)

USAGE_THRESHOLDS = UsageThresholds(
    warn_seconds=(72_000, 86_400),  # 20h, 24h
    hard_stop_seconds=90_000,  # 25h
)

STRIPE_PRICE_TO_PLAN: dict[str, str] = {}


def plan_for_id(plan_id: str) -> PlanDefinition | None:
    if plan_id == DICTATE_PRO_PLAN.plan_id:
        return DICTATE_PRO_PLAN
    return None


def plan_for_stripe_price(price_id: str) -> PlanDefinition | None:
    mapped = STRIPE_PRICE_TO_PLAN.get(price_id)
    if mapped:
        return plan_for_id(mapped)
    return None


def usage_level(used_seconds: int, included_seconds: int) -> str:
    if used_seconds >= USAGE_THRESHOLDS.hard_stop_seconds:
        return "exhausted"
    if used_seconds >= USAGE_THRESHOLDS.warn_seconds[-1]:
        return "critical"
    if any(used_seconds >= threshold for threshold in USAGE_THRESHOLDS.warn_seconds):
        return "warning"
    return "ok"
