"""Tests for Dictate product destination wiring."""

from __future__ import annotations

import unittest

from dictate.pro.product_destinations import ACCOUNT_PORTAL_BASE_URL, PRODUCT_DESTINATIONS


class ProductDestinationsTests(unittest.TestCase):
    def test_hub_and_subpaths_are_dictate_neutral(self) -> None:
        self.assertEqual(ACCOUNT_PORTAL_BASE_URL, "https://deck.arcforge.au/dictate")
        self.assertEqual(PRODUCT_DESTINATIONS["hub"], ACCOUNT_PORTAL_BASE_URL)
        self.assertEqual(PRODUCT_DESTINATIONS["plan"], f"{ACCOUNT_PORTAL_BASE_URL}/plan")
        self.assertEqual(PRODUCT_DESTINATIONS["sync_recovery"], f"{ACCOUNT_PORTAL_BASE_URL}/sync-recovery")

    def test_ui_product_destinations_js_stays_in_sync(self) -> None:
        js_path = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "ui"
            / "src"
            / "productDestinations.js"
        )
        text = js_path.read_text(encoding="utf-8")
        self.assertIn(ACCOUNT_PORTAL_BASE_URL, text)
        for suffix in ("plan", "usage", "billing", "devices", "sync-recovery"):
            self.assertIn(f"/{suffix}", text)


if __name__ == "__main__":
    unittest.main()
