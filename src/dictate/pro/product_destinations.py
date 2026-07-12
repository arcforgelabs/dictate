"""Dictate product destination paths on the Arc Forge account portal."""

from __future__ import annotations

ACCOUNT_PORTAL_BASE_URL = "https://deck.arcforge.au/dictate"
ACCOUNT_LOGIN_URL = "https://deck.arcforge.au/account/login"

PRODUCT_DESTINATIONS: dict[str, str] = {
    "hub": ACCOUNT_PORTAL_BASE_URL,
    "plan": f"{ACCOUNT_PORTAL_BASE_URL}/plan",
    "usage": f"{ACCOUNT_PORTAL_BASE_URL}/usage",
    "billing": f"{ACCOUNT_PORTAL_BASE_URL}/billing",
    "devices": f"{ACCOUNT_PORTAL_BASE_URL}/devices",
    "sync_recovery": f"{ACCOUNT_PORTAL_BASE_URL}/sync-recovery",
}
