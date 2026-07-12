"""Desktop convergence state for Local / Arc Forge / Dictate Pro."""

from __future__ import annotations

from typing import Any


def classify_pro_client_error(status: int, message: str = "") -> str:
    lowered = (message or "").strip().lower()
    if status in {502, 503, 504} or "unreachable" in lowered or "timeout" in lowered:
        return "gateway_outage"
    if status == 401 or "refresh token" in lowered or "access token" in lowered:
        return "auth_expired"
    if status == 403 and "revoked" in lowered:
        return "device_revoked"
    if status == 403 and ("entitlement" in lowered or "not trusted" in lowered or "inactive" in lowered):
        return "entitlement_inactive"
    if status == 402 or "quota" in lowered or "allowance exhausted" in lowered:
        return "quota_exhausted"
    if status in {500, 502} and "transcription" in lowered:
        return "provider_failure"
    if status == 409 and "sync" in lowered:
        return "sync_paused"
    return "unknown_error"


def should_clear_session_on_error(error_code: str) -> bool:
    return error_code in {"auth_expired", "device_revoked"}


def build_convergence_state(
    *,
    signed_in: bool,
    entitlements: dict[str, Any] | None,
    provider_mode: str,
    sync_enabled: bool,
    sync_state: str = "disabled",
    last_error: str | None = None,
) -> dict[str, Any]:
    active = bool(isinstance(entitlements, dict) and entitlements.get("active"))
    if not signed_in:
        account_state = "unsigned"
    elif active:
        account_state = "dictate_pro_active"
    else:
        account_state = "signed_in_arc_forge"
    execution = "cloud" if provider_mode == "online" else "local"
    return {
        "execution": execution,
        "accountState": account_state,
        "sync": {
            "state": sync_state if signed_in else "disabled",
            "enabled": sync_enabled and signed_in and active,
        },
        "lastError": last_error,
        "labels": {
            "unsigned": "Local only",
            "signed_in_arc_forge": "Signed in to Arc Forge",
            "dictate_pro_active": "Dictate Pro active",
            "local_execution": "Transcribing locally",
            "cloud_execution": "Transcribing in the cloud",
        },
    }
