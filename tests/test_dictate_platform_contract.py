from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "contracts" / "dictate-platform-v1.json"

EXPECTED_OPERATIONS = {
    "account.discovery",
    "account.login_authorize",
    "account.token",
    "account.device_authorize",
    "entitlement.read",
    "commerce.read",
    "device.register",
    "device.list",
    "device.revoke",
    "device.approve",
    "sync.push",
    "sync.pull",
    "sync.cursor",
    "sync.key_envelopes.write",
    "sync.key_envelopes.read",
    "sync.export",
    "sync.delete",
    "hosted.create",
    "hosted.upload",
    "hosted.status",
    "hosted.result",
    "hosted.ack",
    "hosted.cancel",
    "gateway.invoke",
}

EXPECTED_ENUMS = {
    "auth_grant_state": ["pending", "approved", "denied", "consumed", "expired"],
    "device_state": ["pending", "trusted", "revoked", "expired"],
    "sync_state": ["disabled", "pending", "enabled", "paused", "revoked", "deleted"],
    "hosted_job_state": [
        "created",
        "awaiting_upload",
        "uploaded",
        "queued",
        "processing",
        "completed",
        "failed",
        "cancelled",
        "expired",
        "quota_rejected",
    ],
    "usage_event_lifecycle": ["reserved", "settled", "rolled_back", "rejected"],
    "usage_event_type": ["reservation", "settlement", "rollback", "rejection"],
}


def _resolve(contract: dict, reference: str) -> object:
    current: object = contract
    for part in reference.removeprefix("#/").split("/"):
        if not isinstance(current, dict):
            raise AssertionError(f"Cannot resolve {reference} at {part}")
        current = current[part]
    return current


class DictatePlatformContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_contract_is_custom_json_and_has_neutral_product_identity(self) -> None:
        contract = self.contract["contract"]
        identity = self.contract["identity"]

        self.assertNotIn("openapi", self.contract)
        self.assertNotIn("paths", self.contract)
        self.assertNotIn("components", self.contract)
        self.assertEqual(contract["version"], "v1")
        self.assertEqual(contract["schema_version"], "1.0.0")
        self.assertEqual(identity["subject_claim"], "account_id")
        self.assertEqual(identity["product"], "dictate")
        self.assertEqual(identity["entitlement"], "dictate_pro")
        self.assertNotEqual(identity["product"], identity["entitlement"])
        self.assertTrue(identity["local_mode_account_free"])
        self.assertIn("dictate.transcribe", identity["capabilities"])
        self.assertIn("dictate.transcribe_diarized", identity["capabilities"])

    def test_current_api_and_reference_v1_surfaces_are_separate(self) -> None:
        surfaces = self.contract["surfaces"]
        current_api = surfaces["current_api_compatibility"]
        reference = surfaces["current_v1_reference"]

        self.assertEqual(current_api["client_source"], "src/dictate/pro/client.py")
        self.assertEqual(current_api["non_loopback_gateway"]["path_prefix"], "/api")
        self.assertEqual(current_api["explicit_modes"]["arcforge_gateway_hosted"]["path_prefix"], "/api")
        self.assertEqual(current_api["explicit_modes"]["local_or_legacy"]["path_prefix"], "/v1")
        self.assertEqual(current_api["released_client_counts"]["status"], "unknown")
        self.assertFalse(current_api["released_client_counts"]["claimed"])

        self.assertEqual(reference["status"], "test_reference_only")
        self.assertEqual(reference["base_path"], "/v1")
        self.assertEqual(reference["implementation"], "src/dictate/pro/server.py")
        self.assertFalse(reference["production_authority"])
        self.assertFalse(reference["canonical_for_production"])
        self.assertFalse(reference["released_client_counts"]["claimed"])

    def test_canonical_operations_are_complete_and_unique(self) -> None:
        operations = self.contract["operations"]

        self.assertEqual(set(operations), EXPECTED_OPERATIONS)
        operation_ids = [operation["operation_id"] for operation in operations.values()]
        route_methods = [(operation["route"], operation["method"]) for operation in operations.values()]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertEqual(len(route_methods), len(set(route_methods)))

        for operation_name, operation in operations.items():
            self.assertEqual(operation_name, operation["operation_id"])
            self.assertEqual(operation["status"], "proposed_not_deployed")
            self.assertIn("request_schema", operation)
            self.assertIn("response_schema", operation)
            self.assertTrue(operation["idempotency"]["header"])
            if operation["transport"] == "public_https":
                self.assertTrue(operation["url_template"].startswith("https://"))
                self.assertNotIn("http://", operation["url_template"])
            else:
                self.assertEqual(operation_name, "gateway.invoke")
                self.assertFalse(operation["public_client_access"])

    def test_canonical_origin_is_https_and_not_deployed(self) -> None:
        future = self.contract["surfaces"]["canonical_future_production"]

        self.assertEqual(future["status"], "proposed_not_deployed")
        self.assertEqual(future["deployment_verification"], "unknown")
        self.assertEqual(future["origin"]["scheme"], "https")
        self.assertTrue(future["origin"]["url_template"].startswith("https://"))
        self.assertTrue(future["origin"]["requires_owner_confirmation"])
        self.assertEqual(future["operations_ref"], "#/operations")

    def test_reusable_state_enums_and_schema_references_are_exact(self) -> None:
        enums = self.contract["enums"]
        for enum_name, expected_values in EXPECTED_ENUMS.items():
            self.assertEqual(enums[enum_name]["type"], "string")
            self.assertEqual(enums[enum_name]["enum"], expected_values, enum_name)

        state_properties = [
            ("Entitlement", "state", "entitlement_state"),
            ("CommerceSubscription", "state", "commerce_state"),
            ("Device", "state", "device_state"),
            ("SyncState", "state", "sync_state"),
            ("HostedJob", "state", "hosted_job_state"),
            ("HostedUpload", "state", "hosted_upload_state"),
            ("UsageEvent", "lifecycle", "usage_event_lifecycle"),
            ("UsageEvent", "event_type", "usage_event_type"),
        ]
        for schema_name, property_name, enum_name in state_properties:
            property_schema = self.contract["schemas"][schema_name]["properties"][property_name]
            self.assertEqual(property_schema["$ref"], f"#/enums/{enum_name}")
        usage = self.contract["schemas"]["UsageEvent"]["properties"]
        self.assertEqual(usage["event_type"]["$ref"], "#/enums/usage_event_type")
        self.assertEqual(usage["lifecycle"]["$ref"], "#/enums/usage_event_lifecycle")

        for operation in self.contract["operations"].values():
            for reference in operation.get("state_refs", []):
                self.assertTrue(reference.startswith("#/enums/"))
                self.assertIsInstance(_resolve(self.contract, reference), dict)

    def test_usage_events_have_quantity_and_full_lifecycle_correlation(self) -> None:
        usage = self.contract["schemas"]["UsageEvent"]
        required = set(usage["required"])
        required_fields = {
            "event_id",
            "account_id",
            "product",
            "entitlement",
            "event_type",
            "lifecycle",
            "amount",
            "quantity",
            "unit",
            "request_id",
            "job_id",
            "idempotency_key",
            "period",
            "correlation_id",
        }
        self.assertTrue(required_fields.issubset(required))
        self.assertTrue(usage["properties"]["event_id"]["immutable"])
        self.assertEqual(usage["properties"]["amount"]["type"], "number")
        self.assertEqual(usage["properties"]["quantity"]["type"], "number")
        self.assertEqual(usage["properties"]["unit"]["const"], "audio_seconds")
        self.assertEqual(usage["properties"]["event_type"]["$ref"], "#/enums/usage_event_type")
        self.assertEqual(usage["properties"]["lifecycle"]["$ref"], "#/enums/usage_event_lifecycle")
        self.assertTrue(
            any(
                invariant.startswith("amount and quantity are numeric audio-second values")
                for invariant in usage["invariants"]
            )
        )
        self.assertEqual(self.contract["usage_events"]["schema_ref"], "#/schemas/UsageEvent")
        self.assertEqual(self.contract["usage_events"]["lifecycle"]["reserve"]["lifecycle"], "reserved")
        self.assertEqual(self.contract["usage_events"]["lifecycle"]["settle"]["lifecycle"], "settled")
        self.assertEqual(self.contract["usage_events"]["lifecycle"]["rollback"]["lifecycle"], "rolled_back")

    def test_privacy_matrix_is_surface_specific_and_forbids_client_leaks(self) -> None:
        rows = {row["surface"]: row for row in self.contract["data_flow_matrix"]["rows"]}

        provider = rows["provider_credentials_and_client_secrets"]
        self.assertEqual(provider["allowed_surfaces"], ["server_runtime_secret_boundary"])
        self.assertIn("desktop_client", provider["forbidden_surfaces"])
        self.assertIn("browser_payload", provider["forbidden_surfaces"])

        tokens = rows["auth_tokens"]
        self.assertEqual(set(tokens["allowed_surfaces"]), {"auth_protocol", "secure_native_storage"})
        self.assertTrue({"logs", "sync", "support_exports"}.issubset(tokens["forbidden_surfaces"]))

        audio = rows["hosted_audio"]
        self.assertEqual(set(audio["allowed_surfaces"]), {"explicit_hosted_upload", "bounded_processing_worker"})
        self.assertTrue({"normal_sync", "logs", "support_exports"}.issubset(audio["forbidden_surfaces"]))
        self.assertIn("TTL", audio["retention"])

        transcript = rows["readable_transcript"]
        self.assertEqual(
            set(transcript["allowed_surfaces"]),
            {"authenticated_client_delivery", "owner_bound_encrypted_result_artifact"},
        )
        self.assertTrue({"logs", "analytics", "support_exports"}.issubset(transcript["forbidden_surfaces"]))
        self.assertIn("ack", transcript["retention"])
        self.assertIn("TTL", transcript["retention"])

        privacy = self.contract["requirements"]["privacy"]
        self.assertTrue(privacy["provider_credentials_never_client_visible"])
        self.assertFalse(privacy["client_secret_for_public_native_clients"])
        self.assertTrue(privacy["tokens_only_auth_protocol_and_secure_native_storage"])

    def test_durable_result_handoff_and_error_shape_are_structured(self) -> None:
        handoff = self.contract["requirements"]["hosted_result_handoff"]
        self.assertEqual(handoff["artifact"], "owner_bound_encrypted_result_artifact")
        self.assertTrue(handoff["owner_bound"])
        self.assertTrue(handoff["retrieval_idempotent"])
        self.assertTrue(handoff["acknowledgement_idempotent"])
        self.assertTrue(handoff["expiry_required"])
        self.assertTrue(handoff["deletion_required"])
        self.assertTrue(handoff["plaintext_lifetime_bounded"])
        self.assertTrue(any("lost client response" in proof for proof in handoff["proofs_required"]))
        self.assertTrue(any("worker restart" in proof for proof in handoff["proofs_required"]))
        self.assertTrue(any("duplicate retrieval" in proof for proof in handoff["proofs_required"]))

        error_ref = self.contract["error_shape"]["schema_ref"]
        error = _resolve(self.contract, error_ref)
        self.assertIsInstance(error, dict)
        self.assertTrue({"error", "code", "message", "request_id", "retryable"}.issubset(error["required"]))

    def test_state_mappings_and_external_revision_are_not_deployment_claims(self) -> None:
        mappings = self.contract["state_mappings"]
        backend = mappings["current_backend"]
        self.assertEqual(backend["deployment_verification"], "unknown")
        ready = next(item for item in backend["job_status_to_canonical"] if item["source_status"] == "ready")
        self.assertEqual(ready["canonical_state"], "completed")
        self.assertEqual(mappings["current_reference"]["status"], "test_reference_only")
        self.assertEqual(mappings["current_api_client"]["api_prefix"], "/api")
        self.assertEqual(mappings["current_api_client"]["legacy_prefix"], "/v1")

        evidence = self.contract["evidence"]["external_source_snapshot"]
        self.assertEqual(evidence["revision"], "2ee29c9dbefb5208aea331042f56b8fad7112b4f")
        self.assertEqual(evidence["deployment_verification"], "unknown")
        self.assertEqual(evidence["owner_confirmation"], "pending")


if __name__ == "__main__":
    unittest.main()
