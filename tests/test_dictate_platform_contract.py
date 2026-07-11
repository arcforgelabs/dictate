from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "contracts" / "dictate-platform-v1.json"


class DictatePlatformContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_version_and_neutral_identity_are_structured(self) -> None:
        contract = self.contract["x-contract"]
        identity = self.contract["x-identity"]

        self.assertEqual(self.contract["info"]["version"], "1.0.0")
        self.assertEqual(contract["version"], "v1")
        self.assertEqual(identity["subject_claim"], "account_id")
        self.assertEqual(identity["product"], "dictate")
        self.assertEqual(identity["entitlement"], "dictate_pro")
        self.assertIn("dictate.transcribe", identity["capabilities"])
        self.assertIn("dictate.transcribe_diarized", identity["capabilities"])
        self.assertNotEqual(identity["product"], identity["entitlement"])

    def test_canonical_surface_is_https_and_not_claimed_deployed(self) -> None:
        future = self.contract["x-surfaces"]["canonical_future_production"]

        self.assertEqual(future["status"], "proposed_not_deployed")
        self.assertTrue(future["origin"]["requires_owner_confirmation"])
        self.assertEqual(future["origin"]["scheme"], "https")
        for route in future["routes"].values():
            self.assertEqual(route["status"], "proposed_not_deployed")
            if "url_template" in route:
                self.assertTrue(route["url_template"].startswith("https://"))
                self.assertNotIn("http://", route["url_template"])

    def test_reference_v1_is_explicitly_non_production(self) -> None:
        reference = self.contract["x-surfaces"]["current_reference_compatibility"]

        self.assertEqual(reference["status"], "test_reference_only")
        self.assertEqual(reference["base_path"], "/v1")
        self.assertFalse(reference["production_authority"])
        self.assertFalse(reference["canonical_for_production"])
        self.assertEqual(reference["implementation"], "src/dictate/pro/server.py")
        self.assertIn("reference", reference["label"])

    def test_state_sets_cover_the_phase_zero_contract(self) -> None:
        states = self.contract["x-state-sets"]
        expected = {
            "entitlement": {"active", "past_due", "grace", "cancelled", "expired", "revoked"},
            "device": {"pending", "trusted", "revoked"},
            "sync": {"disabled", "pending", "enabled", "paused", "revoked", "deleted"},
            "hosted_job": {"created", "queued", "processing", "completed", "failed", "cancelled", "expired"},
            "usage_event": {"reserved", "settled", "rolled_back", "rejected"},
        }

        for state_set, required_states in expected.items():
            self.assertTrue(required_states.issubset(states[state_set]), state_set)

    def test_idempotency_and_privacy_requirements_are_structured(self) -> None:
        requirements = self.contract["x-requirements"]
        idempotency = requirements["idempotency"]
        privacy = requirements["privacy"]

        required_operations = {
            "auth.authorization_code.consume",
            "auth.refresh.rotate",
            "hosted_jobs.create",
            "hosted_jobs.result_ack",
            "gateway.usage.reserve",
            "gateway.usage.settle",
            "gateway.usage.rollback",
        }
        self.assertEqual(idempotency["header"], "Idempotency-Key")
        self.assertTrue(required_operations.issubset(idempotency["required_for"]))
        self.assertEqual(privacy["provider_credentials"], "server_runtime_only")
        self.assertFalse(privacy["provider_keys_in_client"])
        self.assertFalse(privacy["client_secret_for_public_native_clients"])
        self.assertEqual(privacy["sync_payload"], "encrypted_client_side_before_upload")
        self.assertEqual(privacy["hosted_result"], "owner_bound_encrypted_artifact")
        self.assertFalse(privacy["readable_transcript_after_delivery"])

    def test_security_and_usage_envelopes_keep_product_boundaries(self) -> None:
        security = self.contract["security"]
        gateway = self.contract["x-gateway"]
        envelope = set(gateway["request_envelope_required"])

        self.assertFalse(security["public_native_client"]["client_secret_required"])
        self.assertFalse(security["provider_credentials"]["client_visible"])
        self.assertFalse(security["provider_credentials"]["browser_payload_visible"])
        self.assertTrue({"account_id", "product", "capability", "request_id", "idempotency_key"}.issubset(envelope))
        self.assertEqual(gateway["product"], "dictate")
        self.assertEqual(gateway["usage_unit"], "audio_seconds")
        self.assertTrue(gateway["provider_selection"].startswith("server_"))

    def test_error_shape_and_core_schema_constraints_are_present(self) -> None:
        schemas = self.contract["components"]["schemas"]
        error = schemas["Error"]

        self.assertEqual(error["type"], "object")
        self.assertTrue({"error", "code", "message", "request_id", "retryable"}.issubset(error["required"]))
        self.assertEqual(schemas["AccountContext"]["properties"]["product"]["const"], "dictate")
        self.assertEqual(schemas["AccountContext"]["properties"]["entitlement"]["const"], "dictate_pro")
        self.assertEqual(schemas["HostedJob"]["properties"]["result_contract"]["const"], "owner_bound_encrypted_artifact")
        self.assertEqual(schemas["GatewayUsageEvent"]["properties"]["unit"]["const"], "audio_seconds")


if __name__ == "__main__":
    unittest.main()
