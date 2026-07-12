"""Tests for desktop Local / Arc Forge / Dictate Pro convergence state."""

from __future__ import annotations

import unittest

from dictate.pro.platform_state import (
    build_convergence_state,
    classify_pro_client_error,
    should_clear_session_on_error,
)


class PlatformStateTests(unittest.TestCase):
    def test_classify_gateway_outage(self) -> None:
        self.assertEqual(classify_pro_client_error(503), "gateway_outage")

    def test_classify_auth_expired(self) -> None:
        self.assertEqual(classify_pro_client_error(401, "refresh token expired"), "auth_expired")

    def test_classify_device_revoked(self) -> None:
        self.assertEqual(classify_pro_client_error(403, "Dictate device is revoked."), "device_revoked")

    def test_classify_entitlement_inactive(self) -> None:
        self.assertEqual(classify_pro_client_error(403, "entitlement inactive"), "entitlement_inactive")

    def test_classify_quota_exhausted(self) -> None:
        self.assertEqual(classify_pro_client_error(402, "allowance exhausted"), "quota_exhausted")

    def test_should_clear_session_only_for_auth_and_revoke(self) -> None:
        self.assertTrue(should_clear_session_on_error("auth_expired"))
        self.assertTrue(should_clear_session_on_error("device_revoked"))
        self.assertFalse(should_clear_session_on_error("gateway_outage"))

    def test_build_convergence_unsigned(self) -> None:
        state = build_convergence_state(
            signed_in=False,
            entitlements=None,
            provider_mode="private",
            sync_enabled=False,
        )
        self.assertEqual(state["accountState"], "unsigned")
        self.assertEqual(state["execution"], "local")
        self.assertEqual(state["sync"]["state"], "disabled")

    def test_build_convergence_signed_in_arc_forge(self) -> None:
        state = build_convergence_state(
            signed_in=True,
            entitlements={"active": False},
            provider_mode="private",
            sync_enabled=False,
        )
        self.assertEqual(state["accountState"], "signed_in_arc_forge")

    def test_build_convergence_dictate_pro_active(self) -> None:
        state = build_convergence_state(
            signed_in=True,
            entitlements={"active": True},
            provider_mode="online",
            sync_enabled=True,
            sync_state="enabled",
        )
        self.assertEqual(state["accountState"], "dictate_pro_active")
        self.assertEqual(state["execution"], "cloud")
        self.assertTrue(state["sync"]["enabled"])


if __name__ == "__main__":
    unittest.main()
