from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "contracts" / "dictate-platform-v1.json"

EXPECTED_ENUMS = {
    "auth_grant_state": ["pending", "approved", "denied", "consumed", "expired"],
    "commerce_state": [
        "incomplete",
        "trialing",
        "active",
        "past_due",
        "canceled",
        "unpaid",
        "paused",
        "expired",
        "refunded",
    ],
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
    "sync_record_outcome": ["accepted", "rejected", "current_winner", "conflict"],
    "hosted_result_ack_state": ["pending", "acknowledged", "expired", "deleted"],
    "gateway_outcome": ["completed", "failed"],
}


def _resolve(contract: dict[str, Any], reference: str) -> Any:
    current: Any = contract
    for part in reference.removeprefix("#/").split("/"):
        if not isinstance(current, dict) or part not in current:
            raise AssertionError(f"Cannot resolve {reference} at {part}")
        current = current[part]
    return current


def _refs(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            found.append(ref)
        for child in value.values():
            found.extend(_refs(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_refs(child))
    return found


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
        self.assertEqual(contract["status"], "wave_0_authority_locked_not_deployed")
        self.assertEqual(identity["subject_claim"], "account_id")
        self.assertEqual(identity["product"], "dictate")
        self.assertEqual(identity["entitlement"], "dictate_pro")
        self.assertNotEqual(identity["product"], identity["entitlement"])
        self.assertTrue(identity["local_mode_account_free"])
        self.assertIn("dictate.transcribe", identity["capabilities"])
        self.assertIn("dictate.transcribe_diarized", identity["capabilities"])

    def test_authority_map_is_locked_once_per_production_surface(self) -> None:
        authority_map = self.contract["authority_map"]
        self.assertEqual(authority_map["status"], "locked_for_waves_1_to_3")
        surfaces = authority_map["surfaces"]
        self.assertGreaterEqual(len(surfaces), 8)
        for surface, entry in surfaces.items():
            self.assertTrue(entry["proposed_authority"], surface)
            self.assertTrue(entry["owner_role"], surface)
            self.assertIn(
                entry["deployment_verification"],
                {"unknown", "not_applicable"},
                surface,
            )
            self.assertTrue(entry["disposition"], surface)

    def test_current_api_and_reference_v1_surfaces_are_separate(self) -> None:
        surfaces = self.contract["surfaces"]
        current_api = surfaces["current_api_compatibility"]
        reference = surfaces["current_v1_reference"]

        self.assertEqual(current_api["client_source"], "src/dictate/pro/client.py")
        self.assertEqual(current_api["non_loopback_gateway"]["path_prefix"], "/api")
        self.assertEqual(
            current_api["explicit_modes"]["arcforge_gateway_hosted"]["path_prefix"],
            "/api",
        )
        self.assertEqual(current_api["explicit_modes"]["local_or_legacy"]["path_prefix"], "/v1")
        self.assertEqual(current_api["released_client_counts"]["status"], "unknown")
        self.assertFalse(current_api["released_client_counts"]["claimed"])

        self.assertEqual(reference["status"], "test_reference_only")
        self.assertEqual(reference["base_path"], "/v1")
        self.assertEqual(reference["implementation"], "src/dictate/pro/server.py")
        self.assertFalse(reference["production_authority"])
        self.assertFalse(reference["canonical_for_production"])
        self.assertFalse(reference["released_client_counts"]["claimed"])

    def test_source_flow_manifest_drives_operation_completeness(self) -> None:
        operations = self.contract["operations"]
        manifest = self.contract["source_flow_manifest"]
        manifest_operation_ids: set[str] = set()

        self.assertEqual(manifest["version"], "1")
        for flow in manifest["flows"]:
            self.assertTrue(flow["source_refs"], flow["flow_id"])
            self.assertTrue(flow["proposed_authority"], flow["flow_id"])
            self.assertTrue(flow["source_status"], flow["flow_id"])
            self.assertIn(
                flow["deployment_verification"],
                {"unknown", "not_applicable"},
                flow["flow_id"],
            )
            self.assertTrue(flow["disposition"], flow["flow_id"])
            manifest_operation_ids.update(flow.get("operation_ids", []))
            for source_ref in flow["source_refs"]:
                if source_ref.startswith("arc-forge-deck@"):
                    self.assertIn("arc-forge-deck@2ee29c9:", source_ref)
                    self.assertIn("src/arc_forge_console/", source_ref)

        self.assertEqual(set(operations), manifest_operation_ids)
        for operation_name, operation in operations.items():
            self.assertEqual(operation_name, operation["operation_id"])
            self.assertEqual(operation["status"], "proposed_not_deployed")
            self.assertIn("request_schema", operation)
            self.assertIn("response_schema", operation)
            self.assertTrue(operation["idempotency"]["header"])

    def test_canonical_operations_are_unique_https_and_structurally_referenced(self) -> None:
        operations = self.contract["operations"]
        operation_ids = [operation["operation_id"] for operation in operations.values()]
        route_methods = [(operation["route"], operation["method"]) for operation in operations.values()]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertEqual(len(route_methods), len(set(route_methods)))

        for operation in operations.values():
            self.assertIsInstance(_resolve(self.contract, operation["request_schema"]), dict)
            self.assertIsInstance(_resolve(self.contract, operation["response_schema"]), dict)
            if operation["transport"] == "public_https":
                self.assertTrue(operation["url_template"].startswith("https://"))
                self.assertNotIn("http://", operation["url_template"])
            else:
                self.assertFalse(operation["public_client_access"])

        for reference in _refs(self.contract["schemas"]):
            self.assertTrue(reference.startswith("#/"), reference)
            self.assertIsNotNone(_resolve(self.contract, reference), reference)

        self.assertIn("account.email_code_start", operations)
        self.assertIn("account.email_code_verify", operations)
        self.assertIn("usage.read", operations)
        self.assertIn("device.recovery_approve", operations)
        self.assertIn("account.browser_consent", operations)
        self.assertIn("account.browser_consent_decision", operations)
        self.assertIn("account.device_approval", operations)

    def test_canonical_origin_is_https_and_not_deployed(self) -> None:
        future = self.contract["surfaces"]["canonical_future_production"]

        self.assertEqual(future["status"], "proposed_not_deployed")
        self.assertEqual(future["deployment_verification"], "unknown")
        self.assertEqual(future["origin"]["scheme"], "https")
        self.assertTrue(future["origin"]["url_template"].startswith("https://"))
        self.assertEqual(future["origin"]["proposed_origin"], "https://console.arcforge.au")
        self.assertFalse(future["origin"]["requires_owner_confirmation"])
        self.assertIn("proposed_origin", future["origin"]["route_binding"])
        self.assertEqual(future["operations_ref"], "#/operations")

    def test_reusable_state_enums_and_schema_references_are_exact(self) -> None:
        for enum_name, expected_values in EXPECTED_ENUMS.items():
            enum = self.contract["enums"][enum_name]
            self.assertEqual(enum["type"], "string")
            self.assertEqual(enum["enum"], expected_values, enum_name)

        state_properties = [
            ("Entitlement", "state", "entitlement_state"),
            ("CommerceSubscription", "state", "commerce_state"),
            ("Device", "state", "device_state"),
            ("SyncState", "state", "sync_state"),
            ("HostedJob", "state", "hosted_job_state"),
            ("HostedUpload", "state", "hosted_upload_state"),
            ("UsageEventBase", "lifecycle", "usage_event_lifecycle"),
            ("UsageEventBase", "event_type", "usage_event_type"),
        ]
        for schema_name, property_name, enum_name in state_properties:
            property_schema = self.contract["schemas"][schema_name]["properties"][property_name]
            self.assertEqual(property_schema["$ref"], f"#/enums/{enum_name}")

        for operation in self.contract["operations"].values():
            for reference in operation.get("state_refs", []):
                self.assertTrue(reference.startswith("#/enums/"))
                self.assertIsInstance(_resolve(self.contract, reference), dict)

    def test_oauth_token_variants_and_device_polling_errors_are_explicit(self) -> None:
        token = self.contract["schemas"]["TokenRequest"]
        variant_refs = [entry["$ref"] for entry in token["oneOf"]]
        self.assertEqual(
            set(variant_refs),
            {
                "#/schemas/AuthorizationCodeTokenRequest",
                "#/schemas/RefreshTokenRequest",
                "#/schemas/DeviceCodeTokenRequest",
            },
        )
        authorization = self.contract["schemas"]["AuthorizationCodeTokenRequest"]
        self.assertTrue(
            {"grant_type", "redirect_uri", "code", "code_verifier", "client_id"}.issubset(
                authorization["required"]
            )
        )
        self.assertEqual(
            self.contract["schemas"]["RefreshTokenRequest"]["properties"]["grant_type"]["const"],
            "refresh_token",
        )
        device = self.contract["schemas"]["DeviceCodeTokenRequest"]
        self.assertTrue({"grant_type", "device_code", "client_id"}.issubset(device["required"]))
        self.assertIn("device_code", self.contract["operations"]["account.token"]["grant_modes"])

        endpoint = self.contract["schemas"]["TokenEndpointResponse"]
        self.assertEqual(
            {entry["$ref"] for entry in endpoint["oneOf"]},
            {"#/schemas/TokenResponse", "#/schemas/DevicePollingError"},
        )
        self.assertIn("authorization_pending", self.contract["schemas"]["DevicePollingError"]["properties"]["error"]["enum"])
        self.assertIn("slow_down", self.contract["schemas"]["DevicePollingError"]["properties"]["error"]["enum"])

    def test_sync_protocol_is_encrypted_account_device_scoped_and_outbox_drivable(self) -> None:
        envelope = self.contract["schemas"]["SyncEnvelope"]
        required = set(envelope["required"])
        self.assertTrue(
            {
                "account_id",
                "device_id",
                "collection",
                "rev",
                "updated_at",
                "content_type",
                "ciphertext",
                "nonce",
                "aad",
                "authenticated_metadata_hash",
                "tombstone",
                "device_metadata",
            }.issubset(required)
        )
        self.assertEqual(envelope["properties"]["aad"]["$ref"], "#/schemas/SyncAuthenticatedMetadata")
        self.assertNotIn("plaintext", envelope["properties"])
        self.assertNotIn("payload", envelope["properties"])

        outcome = self.contract["schemas"]["SyncRecordOutcome"]
        self.assertEqual(outcome["properties"]["outcome"]["$ref"], "#/enums/sync_record_outcome")
        self.assertTrue({"results", "cursor"}.issubset(self.contract["schemas"]["SyncPushResponse"]["required"]))
        self.assertTrue(
            {"envelopes", "results", "next_cursor", "has_more"}.issubset(
                self.contract["schemas"]["SyncPullResponse"]["required"]
            )
        )
        self.assertTrue(self.contract["requirements"]["sync_protocol"]["client_side_encryption"])

    def test_hosted_result_artifact_has_authenticated_one_of_and_scope_fixtures(self) -> None:
        artifact = self.contract["schemas"]["HostedResultArtifact"]
        self.assertTrue(
            {
                "account_id",
                "device_id",
                "job_id",
                "version",
                "algorithm",
                "recipient_key_id",
                "nonce",
                "aad",
                "integrity_binding",
                "expires_at",
                "delete_after_ack",
                "ack_state",
            }.issubset(set(artifact["required"]))
        )
        self.assertEqual(len(artifact["oneOf"]), 2)
        payload_options = [set(entry["required"]) for entry in artifact["oneOf"]]
        self.assertEqual(payload_options, [{"ciphertext"}, {"artifact_reference"}])
        self.assertEqual(artifact["properties"]["aad"]["$ref"], "#/schemas/HostedArtifactAAD")
        self.assertEqual(artifact["properties"]["delete_after_ack"]["const"], True)

        fixtures = self.contract["contract_fixtures"]["hosted_result_artifact"]
        valid = fixtures["valid"]
        self.assertEqual(valid["account_id"], valid["aad"]["account_id"])
        self.assertEqual(valid["device_id"], valid["aad"]["device_id"])
        wrong_owner = dict(valid)
        wrong_owner.update(fixtures["wrong_owner"]["mutation"])
        self.assertNotEqual(wrong_owner["account_id"], wrong_owner["aad"]["account_id"])
        self.assertEqual(fixtures["wrong_owner"]["expected_rejection"], "account_scope_mismatch")
        tampered = dict(valid)
        tampered.update(fixtures["tampered"]["mutation"])
        self.assertNotEqual(tampered["integrity_binding"], valid["integrity_binding"])
        self.assertEqual(fixtures["tampered"]["expected_rejection"], "authenticated_integrity_mismatch")
        self.assertNotEqual(
            fixtures["tampered"]["mutation"]["integrity_binding"],
            valid["integrity_binding"],
        )
        handoff = self.contract["requirements"]["hosted_result_handoff"]
        self.assertTrue(handoff["retrieval_idempotent"])
        self.assertTrue(handoff["acknowledgement_idempotent"])
        self.assertTrue(handoff["expiry_required"])
        self.assertTrue(handoff["deletion_required"])

    def test_gateway_is_governed_provider_neutral_and_audio_scoped(self) -> None:
        invocation = self.contract["schemas"]["GatewayInvocation"]
        self.assertTrue(
            {
                "audio_input",
                "request_id",
                "job_id",
                "idempotency_key",
                "capability",
                "provider_alias",
                "model_alias",
                "credential_mode",
                "audit",
            }.issubset(set(invocation["required"]))
        )
        self.assertEqual(invocation["properties"]["audio_input"]["$ref"], "#/schemas/GatewayAudioInput")
        self.assertEqual(len(self.contract["schemas"]["GatewayAudioInput"]["oneOf"]), 2)
        self.assertEqual(invocation["properties"]["credential_mode"]["const"], "arc_forge_hosted")
        response = self.contract["schemas"]["GatewayResponse"]
        self.assertTrue({"request_id", "outcome"}.issubset(response["required"]))
        rows = {row["surface"]: row for row in self.contract["data_flow_matrix"]["rows"]}
        provider_audio = rows["governed_provider_request_audio"]
        self.assertIn("governed_provider_request", provider_audio["allowed_surfaces"])
        self.assertTrue({"logs", "sync", "support_exports", "analytics"}.issubset(provider_audio["forbidden_surfaces"]))

    def test_usage_one_of_binds_lifecycle_and_documents_ledger_invariants(self) -> None:
        usage = self.contract["schemas"]["UsageEvent"]
        variant_refs = [entry["$ref"] for entry in usage["oneOf"]]
        self.assertEqual(
            variant_refs,
            [
                "#/schemas/UsageReservationEvent",
                "#/schemas/UsageSettlementEvent",
                "#/schemas/UsageRollbackEvent",
                "#/schemas/UsageRejectionEvent",
            ],
        )
        for variant_ref in variant_refs:
            variant = _resolve(self.contract, variant_ref)
            binding = variant["allOf"][1]["properties"]
            event_type = binding["event_type"]["const"]
            lifecycle = binding["lifecycle"]["const"]
            self.assertEqual(
                self.contract["usage_events"]["lifecycle"][
                    {"reservation": "reserve", "settlement": "settle", "rollback": "rollback", "rejection": "reject"}[event_type]
                ]["lifecycle"],
                lifecycle,
            )

        base = self.contract["schemas"]["UsageEventBase"]
        self.assertTrue({"amount", "quantity", "unit", "period", "request_id", "job_id", "idempotency_key", "correlation_id"}.issubset(base["required"]))
        self.assertEqual(base["properties"]["event_type"]["$ref"], "#/enums/usage_event_type")
        self.assertEqual(base["properties"]["lifecycle"]["$ref"], "#/enums/usage_event_lifecycle")
        invariants = usage["invariants"] + self.contract["usage_events"]["cross_event_invariants"]
        self.assertTrue(any("duplicate" in invariant.lower() for invariant in invariants))
        self.assertTrue(any("exactly-once" in invariant.lower() for invariant in invariants))
        self.assertTrue(any("settlement" in invariant.lower() and "quantity" in invariant.lower() for invariant in invariants))

        mismatch = self.contract["contract_fixtures"]["usage_events"]["mismatched_pair"]
        valid_pairs = {
            (entry["allOf"][1]["properties"]["event_type"]["const"], entry["allOf"][1]["properties"]["lifecycle"]["const"])
            for entry in (self.contract["schemas"][name] for name in [
                "UsageReservationEvent",
                "UsageSettlementEvent",
                "UsageRollbackEvent",
                "UsageRejectionEvent",
            ])
        }
        self.assertNotIn((mismatch["event_type"], mismatch["lifecycle"]), valid_pairs)
        bound = self.contract["contract_fixtures"]["usage_events"]["settlement_over_bound"]
        self.assertGreater(bound["settlement_quantity"], bound["reservation_quantity"])
        rollback = self.contract["contract_fixtures"]["usage_events"]["duplicate_rollback"]
        self.assertEqual(rollback["expected_effective_reversals"], 1)

    def test_diarized_authorization_survives_hosted_lifecycle(self) -> None:
        for operation_id in ["hosted.status", "hosted.result", "hosted.ack", "hosted.cancel"]:
            operation = self.contract["operations"][operation_id]
            self.assertIn("dictate.transcribe_diarized", operation["capabilities"])
            self.assertEqual(operation["capability_authorization"]["mode"], "job_inherited")
            self.assertEqual(operation["capability_authorization"]["source"], "HostedJob.capability")

    def test_commerce_canceled_spelling_and_source_mappings_are_explicit(self) -> None:
        self.assertNotIn("cancelled", self.contract["enums"]["commerce_state"]["enum"])
        mapping = self.contract["state_mappings"]["commerce_state"]
        self.assertEqual(mapping["canonical_terminal_spelling"], "canceled")
        self.assertEqual(mapping["alternate_values"]["cancelled"], "canceled")
        backend = self.contract["state_mappings"]["current_backend"]
        ready = next(item for item in backend["job_status_to_canonical"] if item["source_status"] == "ready")
        self.assertEqual(ready["canonical_state"], "completed")
        self.assertEqual(self.contract["state_mappings"]["current_reference"]["status"], "test_reference_only")

    def test_privacy_matrix_and_document_status_do_not_claim_live_conformance(self) -> None:
        rows = {row["surface"]: row for row in self.contract["data_flow_matrix"]["rows"]}
        provider = rows["provider_credentials_and_client_secrets"]
        self.assertEqual(provider["allowed_surfaces"], ["server_runtime_secret_boundary"])
        self.assertTrue({"desktop_client", "browser_payload", "logs", "sync"}.issubset(provider["forbidden_surfaces"]))
        tokens = rows["auth_tokens"]
        self.assertEqual(set(tokens["allowed_surfaces"]), {"auth_protocol", "secure_native_storage"})
        self.assertTrue({"logs", "sync", "support_exports"}.issubset(tokens["forbidden_surfaces"]))
        transcript = rows["readable_transcript"]
        self.assertTrue({"logs", "analytics", "support_exports", "normal_sync"}.issubset(transcript["forbidden_surfaces"]))
        self.assertIn("ack", transcript["retention"])
        self.assertIn("TTL", transcript["retention"])
        self.assertTrue(self.contract["requirements"]["privacy"]["provider_credentials_never_client_visible"])
        self.assertFalse(self.contract["requirements"]["privacy"]["client_secret_for_public_native_clients"])

        inventory = (ROOT / "docs/platform/dictate-platform-inventory-v1.md").read_text(encoding="utf-8")
        handoff = (ROOT / "docs/platform/arc-forge-backend-handoff-v1.md").read_text(encoding="utf-8")
        goal = (ROOT / "docs/goal.md").read_text(encoding="utf-8")
        self.assertIn("PASSED — planning authority lock only", inventory)
        self.assertIn("PASSED — planning authority lock only", handoff)
        self.assertIn("PASSED — planning authority lock only", goal)
        self.assertIn("UNKNOWN", inventory)
        self.assertIn("UNKNOWN", handoff)

    def test_external_revision_and_deployment_status_are_explicit(self) -> None:
        evidence = self.contract["evidence"]["external_source_snapshot"]
        self.assertEqual(evidence["revision"], "2ee29c9dbefb5208aea331042f56b8fad7112b4f")
        self.assertEqual(evidence["deployment_verification"], "unknown")
        self.assertEqual(evidence["owner_confirmation"], "deployment_confirmation_later")
        self.assertEqual(self.contract["state_mappings"]["current_backend"]["deployment_verification"], "unknown")


if __name__ == "__main__":
    unittest.main()
