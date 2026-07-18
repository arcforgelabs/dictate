from __future__ import annotations

import json
import re
import unittest
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag

from dictate.sync import (
    create_recovery_envelope,
    generate_account_key,
    generate_device_key_pair,
    generate_recovery_key,
    recover_account_key,
    unwrap_account_key_for_device,
    wrap_account_key_for_device,
)


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


def _schema_matches(contract: dict[str, Any], schema_or_ref: Any, value: Any) -> bool:
    """Small dependency-free validator for the contract's executable fixtures."""
    schema = _resolve(contract, schema_or_ref) if isinstance(schema_or_ref, str) else schema_or_ref
    if not isinstance(schema, dict):
        return False
    if "$ref" in schema and not _schema_matches(contract, schema["$ref"], value):
        return False
    if "oneOf" in schema and sum(_schema_matches(contract, option, value) for option in schema["oneOf"]) != 1:
        return False
    if "allOf" in schema and not all(_schema_matches(contract, option, value) for option in schema["allOf"]):
        return False
    if "not" in schema and _schema_matches(contract, schema["not"], value):
        return False
    expected_type = schema.get("type")
    if expected_type == "string" and not isinstance(value, str):
        return False
    if expected_type == "object" and not isinstance(value, dict):
        return False
    if expected_type == "array" and not isinstance(value, list):
        return False
    if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return False
    if expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return False
    if expected_type == "null" and value is not None:
        return False
    if isinstance(expected_type, list):
        type_matches = {
            "string": isinstance(value, str),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "null": value is None,
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        }
        if not any(type_matches.get(kind, False) for kind in expected_type):
            return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return False
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            return False
        if schema.get("format") == "rfc8252-loopback-redirect-uri":
            try:
                parsed = urlsplit(value)
                port = parsed.port
            except ValueError:
                return False
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "::1"}
                or port is None
                or not 1 <= port <= 65535
                or parsed.path != "/callback"
                or bool(parsed.query)
                or bool(parsed.fragment)
                or parsed.username is not None
                or parsed.password is not None
            ):
                return False
    if isinstance(value, (int, float)) and "minimum" in schema and value < schema["minimum"]:
        return False
    if isinstance(value, list):
        items_schema = schema.get("items")
        if items_schema is not None:
            for item in value:
                if not _schema_matches(contract, items_schema, item):
                    return False
    if isinstance(value, dict):
        if not set(schema.get("required", [])).issubset(value):
            return False
        if schema.get("additionalProperties") is False and set(value) - set(schema.get("properties", {})):
            return False
        for name, property_schema in schema.get("properties", {}).items():
            if name in value and not _schema_matches(contract, property_schema, value[name]):
                return False
    return True


def _usage_event(
    event_type: str,
    lifecycle: str,
    *,
    event_id: str,
    quantity: float = 10,
    idempotency_key: str = "idem-1",
    correlation_id: str = "corr-1",
    predecessor_event_id: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "event_id": event_id,
        "account_id": "acct-1",
        "product": "dictate",
        "entitlement": "dictate_pro",
        "capability": "dictate.transcribe",
        "event_type": event_type,
        "lifecycle": lifecycle,
        "amount": quantity,
        "quantity": quantity,
        "unit": "audio_seconds",
        "request_id": "request-1",
        "job_id": "job-1",
        "idempotency_key": idempotency_key,
        "period": {
            "period_id": "period-1",
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-08-01T00:00:00Z",
            "included_seconds": 100,
            "used_seconds": 0,
        },
        "correlation_id": correlation_id,
        "occurred_at": "2026-07-12T00:00:00Z",
    }
    if predecessor_event_id is not None:
        event["predecessor_event_id"] = predecessor_event_id
    return event


class _UsageLedgerModel:
    """Executable contract model for cross-event invariants, not backend code."""

    _LINKED_FIELDS = ("account_id", "request_id", "job_id", "idempotency_key", "period", "correlation_id")
    _CORRELATION_FIELDS = ("account_id", "request_id", "job_id", "idempotency_key", "correlation_id")
    _TERMINAL_EVENT_TYPES = frozenset({"settlement", "rollback", "rejection"})

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.by_retry_key: dict[tuple[str, str, str, str, str], str] = {}
        self.terminal_outcomes: dict[tuple[str, str, str, str, str], str] = {}
        self.reservations_by_correlation: dict[tuple[str, str, str, str, str], str] = {}

    def _retry_key(self, event: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return (
            event["account_id"],
            event["request_id"],
            event["job_id"],
            event["idempotency_key"],
            event["event_type"],
        )

    def _correlation_key(self, event: dict[str, Any]) -> tuple[str, str, str, str, str]:
        return tuple(event[field] for field in self._CORRELATION_FIELDS)

    def _assert_linked_fields(self, event: dict[str, Any], anchor: dict[str, Any]) -> None:
        for field in self._LINKED_FIELDS:
            if event[field] != anchor[field]:
                raise ValueError("linked field mismatch")

    def _reservation_for_correlation(self, event: dict[str, Any]) -> dict[str, Any]:
        reservation_id = self.reservations_by_correlation.get(self._correlation_key(event))
        if reservation_id is None:
            raise ValueError("missing reservation correlation")
        return self.events[reservation_id]

    def _apply_terminal_outcome(self, event: dict[str, Any], event_type: str) -> None:
        correlation_key = self._correlation_key(event)
        existing_terminal = self.terminal_outcomes.get(correlation_key)
        if existing_terminal is not None:
            if existing_terminal == event_type:
                raise ValueError(f"duplicate {event_type}")
            raise ValueError("terminal outcome conflict")
        reservation = self._reservation_for_correlation(event)
        if event_type in {"settlement", "rollback"}:
            predecessor = event.get("predecessor_event_id")
            if predecessor != reservation["event_id"]:
                raise ValueError("missing reservation predecessor")
        self._assert_linked_fields(event, reservation)
        if event_type == "settlement" and event["quantity"] > reservation["quantity"]:
            raise ValueError("settlement exceeds reservation")
        self.terminal_outcomes[correlation_key] = event_type

    def apply(self, event: dict[str, Any]) -> dict[str, Any]:
        retry_key = self._retry_key(event)
        existing_id = self.by_retry_key.get(retry_key)
        if existing_id is not None:
            if event["event_id"] == existing_id:
                return self.events[existing_id]
            raise ValueError("duplicate idempotency key")
        event_type = event["event_type"]
        if event_type == "reservation":
            self.reservations_by_correlation[self._correlation_key(event)] = event["event_id"]
        elif event_type in self._TERMINAL_EVENT_TYPES:
            self._apply_terminal_outcome(event, event_type)
        self.events[event["event_id"]] = event
        self.by_retry_key[retry_key] = event["event_id"]
        return event


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
        self.assertEqual(contract["status"], "p1_offline_candidate_implementation_not_deployed")
        self.assertEqual(contract["p1_source_evidence"]["deployment_state"], "not_deployed")
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
        origin = self.contract["surfaces"]["canonical_future_production"]["origin"]["proposed_origin"]
        operation_ids = [operation["operation_id"] for operation in operations.values()]
        route_methods = [(operation["route"], operation["method"]) for operation in operations.values()]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertEqual(len(route_methods), len(set(route_methods)))

        for operation in operations.values():
            self.assertIsInstance(_resolve(self.contract, operation["request_schema"]), dict)
            self.assertIsInstance(_resolve(self.contract, operation["response_schema"]), dict)
            if operation["transport"] == "public_https":
                rendered_url = operation["url_template"]
                self.assertEqual(rendered_url, origin + operation["route"])
                self.assertEqual(rendered_url.count("://"), 1)
                self.assertTrue(rendered_url.startswith(origin + "/"))
                self.assertNotIn("://", operation["route"])
                self.assertNotIn("{canonical_arc_forge_origin}", rendered_url)
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
        self.assertEqual(future["origin"]["proposed_origin"], "https://console.arcforge.au")
        self.assertEqual(future["origin"]["url_template"], future["origin"]["proposed_origin"])
        self.assertEqual(future["origin"]["url_template"].count("://"), 1)
        self.assertFalse(future["origin"]["requires_owner_confirmation"])
        self.assertIn("exactly one route path", future["origin"]["route_binding"])
        self.assertEqual(future["operations_ref"], "#/operations")

    def test_every_public_operation_url_rejects_double_scheme_rendering(self) -> None:
        origin = self.contract["surfaces"]["canonical_future_production"]["origin"]["rendering"]["origin"]
        self.assertEqual(origin, "https://console.arcforge.au")
        for operation in self.contract["operations"].values():
            if operation["transport"] != "public_https":
                continue
            rendered = f"{origin}{operation['route']}"
            self.assertEqual(rendered, operation["url_template"])
            self.assertFalse(rendered.startswith("https://https://"))
            self.assertEqual(rendered.count("://"), 1)

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

    def test_oauth_loopback_pkce_and_cancellation_semantics_are_executable(self) -> None:
        redirect_schema = "#/schemas/LoopbackRedirectURI"
        valid_redirects = [
            "http://127.0.0.1:1/callback",
            "http://127.0.0.1:0001/callback",
            "http://127.0.0.1:65535/callback",
            "http://[::1]:43123/callback",
        ]
        invalid_redirects = [
            "https://127.0.0.1:43123/callback",
            "http://localhost:43123/callback",
            "http://127.0.0.1:0/callback",
            "http://127.0.0.1:65536/callback",
            "http://127.0.0.1:43123/other",
            "http://user@127.0.0.1:43123/callback",
            "http://127.0.0.1:43123/callback?state=x",
            "http://[::1]:43123/callback#fragment",
        ]
        for redirect_uri in valid_redirects:
            self.assertTrue(_schema_matches(self.contract, redirect_schema, redirect_uri), redirect_uri)
        for redirect_uri in invalid_redirects:
            self.assertFalse(_schema_matches(self.contract, redirect_schema, redirect_uri), redirect_uri)

        challenge_schema = "#/schemas/PKCECodeChallenge"
        verifier_schema = "#/schemas/PKCECodeVerifier"
        self.assertTrue(_schema_matches(self.contract, challenge_schema, "A" * 43))
        self.assertFalse(_schema_matches(self.contract, challenge_schema, "A" * 42))
        self.assertFalse(_schema_matches(self.contract, challenge_schema, "A" * 42 + "+"))
        self.assertTrue(_schema_matches(self.contract, verifier_schema, "A" * 43))
        self.assertTrue(_schema_matches(self.contract, verifier_schema, "A" * 128))
        self.assertFalse(_schema_matches(self.contract, verifier_schema, "A" * 42))
        self.assertFalse(_schema_matches(self.contract, verifier_schema, "A" * 129))
        self.assertFalse(_schema_matches(self.contract, verifier_schema, "A" * 42 + "+"))

        success = {"code": "code-1", "state": "state-1"}
        denied = {"error": "access_denied", "state": "state-1"}
        malformed = {"error": "access_denied"}
        code_and_error = {"code": "code-1", "error": "access_denied", "state": "state-1"}
        self.assertTrue(_schema_matches(self.contract, "#/schemas/AuthorizationResponse", success))
        self.assertTrue(_schema_matches(self.contract, "#/schemas/AuthorizationResponse", denied))
        self.assertFalse(_schema_matches(self.contract, "#/schemas/AuthorizationResponse", malformed))
        self.assertFalse(_schema_matches(self.contract, "#/schemas/AuthorizationResponse", code_and_error))

        authorization_code = self.contract["schemas"]["AuthorizationCodeTokenRequest"]
        self.assertEqual(
            authorization_code["properties"]["redirect_uri"]["$ref"],
            "#/schemas/LoopbackRedirectURI",
        )
        self.assertEqual(
            authorization_code["properties"]["code_verifier"]["$ref"],
            "#/schemas/PKCECodeVerifier",
        )

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

    def test_key_envelope_variants_match_current_crypto_and_account_bound_aad(self) -> None:
        sync_flow = next(flow for flow in self.contract["source_flow_manifest"]["flows"] if flow["flow_id"] == "encrypted_sync")
        self.assertEqual(
            sync_flow["key_envelope_authority"],
            "dictate_client_encryption_with_arc_forge_envelope_storage",
        )
        self.assertIn("src/dictate/sync.py:76-89,166-278,627-638", sync_flow["source_refs"])
        key_envelope = self.contract["schemas"]["KeyEnvelope"]
        self.assertEqual(
            [entry["$ref"] for entry in key_envelope["oneOf"]],
            ["#/schemas/DeviceKeyEnvelope", "#/schemas/RecoveryKeyEnvelope"],
        )
        self.assertEqual(
            self.contract["requirements"]["sync_protocol"]["key_envelopes"]["account_bound_aad"],
            {
                "device": "dictate-sync-device-envelope:v1:{account_id}",
                "recovery": "dictate-sync-recovery:v1:{account_id}",
                "encoding": "exact UTF-8 bytes after trimming account_id; no alternate normalization or caller-supplied AAD",
            },
        )
        self.assertEqual(
            set(self.contract["schemas"]["DeviceKeyEnvelope"]["required"]),
            {"version", "algorithm", "ephemeral_public_key", "salt", "nonce", "ciphertext", "aad_hash"},
        )
        self.assertEqual(
            set(self.contract["schemas"]["RecoveryKeyEnvelope"]["required"]),
            {"version", "kdf", "iterations", "salt", "nonce", "ciphertext", "aad_hash"},
        )

        account_key = generate_account_key()
        recipient = generate_device_key_pair()
        device_envelope = wrap_account_key_for_device(
            account_id="acct-1",
            account_key=account_key,
            recipient_public_key=recipient.public_key,
        )
        self.assertTrue(_schema_matches(self.contract, "#/schemas/DeviceKeyEnvelope", device_envelope))
        self.assertEqual(
            unwrap_account_key_for_device(
                account_id="acct-1",
                private_key=recipient.private_key,
                envelope=device_envelope,
            ),
            account_key,
        )
        with self.assertRaises(InvalidTag):
            unwrap_account_key_for_device(
                account_id="acct-1",
                private_key=generate_device_key_pair().private_key,
                envelope=device_envelope,
            )

        recovery_key = generate_recovery_key()
        recovery_envelope = create_recovery_envelope(
            account_id="acct-1",
            account_key=account_key,
            recovery_key=recovery_key,
        )
        recovery_payload = asdict(recovery_envelope)
        self.assertTrue(_schema_matches(self.contract, "#/schemas/RecoveryKeyEnvelope", recovery_payload))
        self.assertEqual(
            recover_account_key(
                account_id="acct-1",
                recovery_key=recovery_key,
                envelope=recovery_envelope,
            ),
            account_key,
        )
        with self.assertRaises(ValueError):
            recover_account_key(
                account_id="acct-2",
                recovery_key=recovery_key,
                envelope=recovery_envelope,
            )

        request = {"device_id": "device-1", "envelope_kind": "device", "envelope": device_envelope}
        self.assertTrue(_schema_matches(self.contract, "#/schemas/KeyEnvelopeRequest", request))
        self.assertFalse(
            _schema_matches(
                self.contract,
                "#/schemas/KeyEnvelopeRequest",
                {**request, "envelope_kind": "recovery"},
            )
        )

    def test_key_envelope_record_and_list_fixtures_match_signature_bundle_shape(self) -> None:
        bundle = self.contract["schemas"]["MetadataSignatureBundle"]
        self.assertEqual(
            set(bundle["required"]),
            {"algorithm", "key_id", "public_key", "signature"},
        )
        self.assertEqual(bundle["properties"]["algorithm"]["const"], "Ed25519")

        fixtures = self.contract["contract_fixtures"]["key_envelopes"]
        save_response = fixtures["save_response"]
        list_response = fixtures["list_response"]
        legacy_unsigned = fixtures["legacy_unsigned"]

        self.assertTrue(_schema_matches(self.contract, "#/schemas/KeyEnvelopeRecord", save_response))
        self.assertTrue(_schema_matches(self.contract, "#/schemas/KeyEnvelopeList", list_response))
        for envelope in list_response["envelopes"]:
            self.assertTrue(_schema_matches(self.contract, "#/schemas/KeyEnvelopeRecord", envelope))
        self.assertTrue(_schema_matches(self.contract, "#/schemas/KeyEnvelopeRecord", legacy_unsigned))
        self.assertFalse(_schema_matches(self.contract, "#/schemas/KeyEnvelopeList", {"envelopes": [{}]}))
        self.assertIsInstance(save_response["server_signature"], dict)
        self.assertIsNone(legacy_unsigned["server_signature"])
        self.assertFalse(
            _schema_matches(
                self.contract,
                "#/schemas/KeyEnvelopeRecord",
                {**save_response, "server_signature": "legacy-string-signature"},
            )
        )

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
                "usage_event",
            }.issubset(set(invocation["required"]))
        )
        self.assertEqual(invocation["properties"]["audio_input"]["$ref"], "#/schemas/GatewayAudioInput")
        self.assertEqual(len(self.contract["schemas"]["GatewayAudioInput"]["oneOf"]), 2)
        self.assertEqual(invocation["properties"]["credential_mode"]["const"], "arc_forge_hosted")
        self.assertEqual(invocation["properties"]["usage_event"]["$ref"], "#/schemas/UsageReservationEvent")
        response = self.contract["schemas"]["GatewayResponse"]
        self.assertTrue({"request_id", "outcome", "usage_event", "provider_response_processing"}.issubset(response["required"]))
        self.assertEqual(response["properties"]["usage_event"]["$ref"], "#/schemas/GatewayUsageOutcome")
        self.assertEqual(
            response["properties"]["provider_response_processing"]["$ref"],
            "#/schemas/GatewayProviderResponseProcessing",
        )
        gateway_usage = self.contract["requirements"]["gateway_usage"]
        self.assertTrue(gateway_usage["reservation_durable_before_provider_request"])
        self.assertTrue(gateway_usage["response_must_link_settlement_rollback_or_rejection"])
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
        self.assertTrue(any("exactly-once" in invariant.lower() or "exactly one" in invariant.lower() for invariant in invariants))
        self.assertTrue(any("settlement" in invariant.lower() and "quantity" in invariant.lower() for invariant in invariants))
        idempotency_model = self.contract["usage_events"]["idempotency_model"]
        self.assertEqual(idempotency_model["gateway_correlation_key"], "idempotency_key")
        self.assertEqual(
            idempotency_model["retry_dedup_key"],
            ["account_id", "request_id", "job_id", "idempotency_key", "event_type"],
        )
        self.assertIn("idempotency_key", idempotency_model["shared_across_lifecycle"])

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

    def test_usage_ledger_model_rejects_duplicate_idempotency_over_settlement_and_rollback(self) -> None:
        shared_idempotency_key = self.contract["contract_fixtures"]["usage_events"]["lifecycle_shared_idempotency_key"]
        shared_correlation_id = self.contract["contract_fixtures"]["usage_events"]["lifecycle_correlation_id"]
        reservation = _usage_event(
            "reservation",
            "reserved",
            event_id="reserve-1",
            idempotency_key=shared_idempotency_key,
            correlation_id=shared_correlation_id,
        )
        settlement = _usage_event(
            "settlement",
            "settled",
            event_id="settle-1",
            quantity=8,
            idempotency_key=shared_idempotency_key,
            correlation_id=shared_correlation_id,
            predecessor_event_id="reserve-1",
        )
        rollback = _usage_event(
            "rollback",
            "rolled_back",
            event_id="rollback-1",
            quantity=10,
            idempotency_key=shared_idempotency_key,
            correlation_id=shared_correlation_id,
            predecessor_event_id="reserve-1",
        )
        self.assertTrue(_schema_matches(self.contract, "#/schemas/UsageEvent", reservation))
        self.assertTrue(_schema_matches(self.contract, "#/schemas/UsageEvent", settlement))
        self.assertTrue(_schema_matches(self.contract, "#/schemas/UsageEvent", rollback))

        ledger = _UsageLedgerModel()
        self.assertIs(ledger.apply(reservation), reservation)
        self.assertIs(ledger.apply(dict(reservation)), reservation)
        with self.assertRaisesRegex(ValueError, "duplicate idempotency"):
            ledger.apply({**reservation, "event_id": "reserve-duplicate"})
        with self.assertRaisesRegex(ValueError, "settlement exceeds"):
            ledger.apply(
                _usage_event(
                    "settlement",
                    "settled",
                    event_id="settle-over",
                    quantity=11,
                    idempotency_key=shared_idempotency_key,
                    correlation_id=shared_correlation_id,
                    predecessor_event_id="reserve-1",
                )
            )
        with self.assertRaisesRegex(ValueError, "linked field mismatch"):
            mismatched_period_settlement = _usage_event(
                "settlement",
                "settled",
                event_id="settle-mismatch",
                quantity=8,
                idempotency_key=shared_idempotency_key,
                correlation_id=shared_correlation_id,
                predecessor_event_id="reserve-1",
            )
            mismatched_period_settlement["period"] = {
                **mismatched_period_settlement["period"],
                "period_id": "period-2",
            }
            ledger.apply(mismatched_period_settlement)
        self.assertIs(ledger.apply(settlement), settlement)
        self.assertIs(ledger.apply(dict(settlement)), settlement)
        with self.assertRaisesRegex(ValueError, "duplicate idempotency"):
            ledger.apply(
                _usage_event(
                    "settlement",
                    "settled",
                    event_id="settle-duplicate",
                    quantity=8,
                    idempotency_key=shared_idempotency_key,
                    correlation_id=shared_correlation_id,
                    predecessor_event_id="reserve-1",
                )
            )
        with self.assertRaisesRegex(ValueError, "terminal outcome conflict"):
            ledger.apply(rollback)

        rollback_ledger = _UsageLedgerModel()
        rollback_ledger.apply(reservation)
        self.assertIs(rollback_ledger.apply(rollback), rollback)
        self.assertIs(rollback_ledger.apply(dict(rollback)), rollback)
        with self.assertRaisesRegex(ValueError, "duplicate idempotency"):
            rollback_ledger.apply(
                _usage_event(
                    "rollback",
                    "rolled_back",
                    event_id="rollback-duplicate",
                    quantity=10,
                    idempotency_key=shared_idempotency_key,
                    correlation_id=shared_correlation_id,
                    predecessor_event_id="reserve-1",
                )
            )
        with self.assertRaisesRegex(ValueError, "terminal outcome conflict"):
            rollback_ledger.apply(settlement)

    def test_usage_ledger_model_enforces_rejection_terminal_exclusivity(self) -> None:
        shared_idempotency_key = self.contract["contract_fixtures"]["usage_events"]["lifecycle_shared_idempotency_key"]
        shared_correlation_id = self.contract["contract_fixtures"]["usage_events"]["lifecycle_correlation_id"]
        reservation = _usage_event(
            "reservation",
            "reserved",
            event_id="reserve-1",
            idempotency_key=shared_idempotency_key,
            correlation_id=shared_correlation_id,
        )
        settlement = _usage_event(
            "settlement",
            "settled",
            event_id="settle-1",
            quantity=8,
            idempotency_key=shared_idempotency_key,
            correlation_id=shared_correlation_id,
            predecessor_event_id="reserve-1",
        )
        rollback = _usage_event(
            "rollback",
            "rolled_back",
            event_id="rollback-1",
            quantity=10,
            idempotency_key=shared_idempotency_key,
            correlation_id=shared_correlation_id,
            predecessor_event_id="reserve-1",
        )
        rejection = _usage_event(
            "rejection",
            "rejected",
            event_id="reject-1",
            idempotency_key=shared_idempotency_key,
            correlation_id=shared_correlation_id,
        )
        self.assertTrue(_schema_matches(self.contract, "#/schemas/UsageEvent", rejection))
        self.assertNotIn("predecessor_event_id", rejection)

        reject_then_settle = _UsageLedgerModel()
        reject_then_settle.apply(reservation)
        self.assertIs(reject_then_settle.apply(rejection), rejection)
        self.assertIs(reject_then_settle.apply(dict(rejection)), rejection)
        with self.assertRaisesRegex(ValueError, "terminal outcome conflict"):
            reject_then_settle.apply(settlement)

        settle_then_reject = _UsageLedgerModel()
        settle_then_reject.apply(reservation)
        settle_then_reject.apply(settlement)
        with self.assertRaisesRegex(ValueError, "terminal outcome conflict"):
            settle_then_reject.apply(rejection)

        reject_then_rollback = _UsageLedgerModel()
        reject_then_rollback.apply(reservation)
        reject_then_rollback.apply(rejection)
        with self.assertRaisesRegex(ValueError, "terminal outcome conflict"):
            reject_then_rollback.apply(rollback)

        rollback_then_reject = _UsageLedgerModel()
        rollback_then_reject.apply(reservation)
        rollback_then_reject.apply(rollback)
        with self.assertRaisesRegex(ValueError, "terminal outcome conflict"):
            rollback_then_reject.apply(rejection)

    def test_diarized_authorization_survives_hosted_lifecycle(self) -> None:
        for operation_id in ["hosted.upload", "hosted.status", "hosted.result", "hosted.ack", "hosted.cancel"]:
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
        provider_response = rows["governed_provider_response_processing"]
        self.assertTrue({"bounded_memory_gateway_worker", "immediate_server_managed_encryption"}.issubset(provider_response["allowed_surfaces"]))
        self.assertTrue({"persistence", "logs", "analytics", "support_exports", "normal_sync"}.issubset(provider_response["forbidden_surfaces"]))
        self.assertIn("memory only", provider_response["retention"])
        self.assertIn("delete readable provider response", provider_response["retention"])
        response_processing = self.contract["requirements"]["privacy"]["provider_response_processing"]
        self.assertTrue(response_processing["memory_only"])
        self.assertTrue(response_processing["immediate_server_managed_encryption"])
        self.assertTrue(response_processing["delete_after_encryption"])
        self.assertTrue(set(response_processing["forbidden_surfaces"]).issubset(provider_response["forbidden_surfaces"]))
        self.assertTrue(self.contract["schemas"]["GatewayProviderResponseProcessing"]["properties"]["persisted"]["const"] is False)
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
        inventory = (ROOT / "docs/platform/dictate-platform-inventory-v1.md").read_text(encoding="utf-8")
        handoff = (ROOT / "docs/platform/arc-forge-backend-handoff-v1.md").read_text(encoding="utf-8")
        self.assertIn("dashboard.py:12892-13123", inventory)
        self.assertIn("dashboard.py:12632-12802", inventory)
        self.assertIn("dashboard.py:12632-12802,12807-13123,13125-13127", handoff)


if __name__ == "__main__":
    unittest.main()
