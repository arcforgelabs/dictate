"""Tests for Dictate Pro desktop client."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate.pro.client import ProClient, ProClientError, ProSession
from dictate.sync import PlainSyncRecord, encrypt_record, generate_account_key


def _unsigned_jwt(subject: str) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode("ascii").rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": subject}).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{header}.{payload}."


class CapturingProClient(ProClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls: list[dict[str, object]] = []
        self.responses: list[dict[str, object]] = []
        self.put_uploads: list[dict[str, object]] = []

    def _request(
        self,
        method: str,
        path: str,
        payload=None,
        *,
        auth: str | None = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "payload": payload,
                "auth": auth,
                "content_type": content_type,
                "headers": headers,
            }
        )
        return self.responses.pop(0) if self.responses else {}

    def _put_signed_upload(self, url: str, data: bytes, *, content_type: str) -> None:
        self.put_uploads.append({"url": url, "data": data, "content_type": content_type})


class ProClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.session_path = Path(self._tmp.name) / "pro-session.json"
        self.client = ProClient(session_path=self.session_path)

    def tearDown(self) -> None:
        os.environ.pop("DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS", None)
        os.environ.pop("DICTATE_PRO_API_MODE", None)
        self._tmp.cleanup()

    def test_save_session_warns_on_plaintext_refresh_token_fallback(self) -> None:
        os.environ["DICTATE_PRO_ALLOW_PLAINTEXT_TOKENS"] = "1"
        session = ProSession(
            account_id="acct_test",
            device_id="dev_test",
            access_token="access",
            refresh_token="refresh_secret",
            access_expires_at="2026-01-01T00:00:00+00:00",
            refresh_expires_at="2027-01-01T00:00:00+00:00",
        )
        with patch.object(self.client, "_save_refresh_token", return_value=False):
            with self.assertLogs("dictate.pro.client", level="WARNING") as logs:
                self.client.save_session(session)
        self.assertTrue(any("plaintext" in message for message in logs.output))
        payload = json.loads(self.session_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["refresh_token"], "refresh_secret")

    def test_save_session_rejects_plaintext_without_opt_in(self) -> None:
        session = ProSession(
            account_id="acct_test",
            device_id="dev_test",
            access_token="access",
            refresh_token="refresh_secret",
            access_expires_at="2026-01-01T00:00:00+00:00",
            refresh_expires_at="2027-01-01T00:00:00+00:00",
        )
        with patch.object(self.client, "_save_refresh_token", return_value=False):
            with self.assertRaises(ProClientError) as ctx:
                self.client.save_session(session)
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("plaintext token fallback is disabled", ctx.exception.message)
        self.assertFalse(self.session_path.exists())

    def test_default_api_url_is_arc_forge_gateway(self) -> None:
        client = ProClient(session_path=self.session_path)
        self.assertEqual(client.base_url, "https://console.arcforge.au")

    def test_local_api_url_keeps_legacy_v1_routes(self) -> None:
        client = CapturingProClient(base_url="http://127.0.0.1:18765", session_path=self.session_path)
        session = ProSession(
            account_id="acct_test",
            device_id="dev_test",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        with patch.object(client, "load_session", return_value=session):
            client.create_meeting(language="en")
            client.get_meeting("job_1")
            client.get_transcript("job_1")

        self.assertEqual(client.calls[0]["path"], "/v1/meetings")
        self.assertEqual(client.calls[0]["payload"], {"language": "en"})
        self.assertEqual(client.calls[1]["path"], "/v1/meetings/job_1")
        self.assertEqual(client.calls[2]["path"], "/v1/meetings/job_1/transcript")

    def test_explicit_legacy_mode_keeps_v1_routes_on_non_loopback_url(self) -> None:
        os.environ["DICTATE_PRO_API_MODE"] = "legacy"
        client = CapturingProClient(base_url="https://legacy.example", session_path=self.session_path)
        session = ProSession(
            account_id="acct_test",
            device_id="dev_test",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )

        with patch.object(client, "load_session", return_value=session):
            client.create_meeting(language="en")

        self.assertEqual(client.calls[0]["path"], "/v1/meetings")

    def test_local_api_url_uses_v1_sync_routes(self) -> None:
        client = CapturingProClient(base_url="http://127.0.0.1:18765", session_path=self.session_path)
        session = ProSession(
            account_id="acct_test",
            device_id="dev_test",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        record = encrypt_record(
            "acct_test",
            generate_account_key(),
            PlainSyncRecord(
                collection="history",
                record_id="hist_1",
                rev=1,
                updated_at="2026-07-05T12:00:00+00:00",
                device_id="dev_test",
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "private"},
            ),
        )

        with patch.object(client, "load_session", return_value=session):
            client.push_sync_records([record])
            client.get_sync_changes(since=7, limit=50)
            client.update_sync_cursor(last_seq=50)
            client.save_key_envelope(envelope_kind="recovery", envelope={"ciphertext": "opaque"})
            client.list_key_envelopes(envelope_kind="recovery")

        self.assertEqual(client.calls[0]["path"], "/v1/sync/push")
        self.assertEqual(client.calls[0]["payload"]["device_id"], "dev_test")
        self.assertEqual(client.calls[0]["payload"]["records"][0]["record_id"], "hist_1")
        self.assertEqual(client.calls[1]["path"], "/v1/sync/changes?since=7&limit=50")
        self.assertEqual(client.calls[2]["path"], "/v1/sync/cursor")
        self.assertEqual(client.calls[2]["payload"]["last_seq"], 50)
        self.assertEqual(client.calls[3]["path"], "/v1/sync/key-envelopes")
        self.assertEqual(client.calls[3]["payload"]["envelope_kind"], "recovery")
        self.assertEqual(client.calls[4]["path"], "/v1/sync/key-envelopes?kind=recovery")

    def test_local_api_url_uses_v1_account_device_routes(self) -> None:
        client = CapturingProClient(base_url="http://127.0.0.1:18765", session_path=self.session_path)
        session = ProSession(
            account_id="acct_test",
            device_id="dev_test",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )

        recovery_envelope = {
            "version": 1,
            "kdf": "pbkdf2-sha256",
            "iterations": 200_000,
            "salt": "c2FsdA==",
            "nonce": "bm9uY2U=",
            "ciphertext": "Y2lwaGVy",
            "aad_hash": "YWFk",
        }

        with patch.object(client, "load_session", return_value=session):
            client.list_devices()
            client.register_device(device_label="Desktop", device_public_key="public_key_1")
            client.revoke_device("dev_other")
            client.approve_device("dev_other", envelope={"algorithm": "test"})
            client.approve_current_device_with_recovery(
                recovery_key_envelope=recovery_envelope,
                account_key_commitment="commitment_test",
                idempotency_key="recovery-1",
            )
            client.export_cloud_data()
            client.delete_cloud_data(idempotency_key="delete-1")

        self.assertEqual([call["path"] for call in client.calls], [
            "/v1/devices",
            "/v1/devices/register",
            "/v1/devices/dev_other/revoke",
            "/v1/devices/dev_other/approve",
            "/v1/devices/current/approve-with-recovery",
            "/v1/account/export",
            "/v1/account/cloud-data",
        ])
        self.assertEqual([call["method"] for call in client.calls], ["GET", "POST", "POST", "POST", "POST", "GET", "DELETE"])
        self.assertEqual(client.calls[1]["payload"]["device_public_key"], "public_key_1")
        self.assertEqual(client.calls[3]["payload"], {"envelope": {"algorithm": "test"}})
        self.assertEqual(
            client.calls[4]["payload"],
            {
                "recovery_key_envelope": recovery_envelope,
                "account_key_commitment": "commitment_test",
            },
        )
        self.assertEqual(client.calls[6]["payload"], {"confirmation": "delete_cloud_data"})

    def test_local_sign_in_sends_device_public_key(self) -> None:
        client = CapturingProClient(base_url="http://127.0.0.1:18765", session_path=self.session_path)
        client.responses = [
            {
                "account_id": "acct_test",
                "device_id": "dev_test",
                "access_token": "access",
                "refresh_token": "refresh",
                "access_expires_at": "2027-01-01T00:00:00+00:00",
                "refresh_expires_at": "2028-01-01T00:00:00+00:00",
            },
        ]

        with patch.object(client, "_save_refresh_token", return_value=True):
            client.complete_sign_in(
                challenge_id="challenge",
                code="123456",
                device_label="Desktop",
                device_public_key="public_key_1",
            )

        self.assertEqual(client.calls[0]["path"], "/v1/auth/complete")
        self.assertEqual(client.calls[0]["payload"]["device_public_key"], "public_key_1")

    def test_arc_forge_sign_in_uses_shared_account_login_code_routes(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        client.responses = [
            {"message": "If an account exists, a login code has been sent."},
            {
                "access_token": _unsigned_jwt("arc_account_1"),
                "refresh_token": "refresh_1",
                "expires_in": 3600,
            },
        ]
        with patch.object(client, "_save_refresh_token", return_value=True):
            start = client.start_sign_in("USER@example.com")
            session = client.complete_sign_in(challenge_id=start["challenge_id"], code="12345678")

        self.assertEqual(start["challenge_id"], "user@example.com")
        self.assertEqual(client.calls[0]["path"], "/api/account/auth/login-code")
        self.assertEqual(client.calls[0]["payload"], {"email": "user@example.com"})
        self.assertEqual(client.calls[1]["path"], "/api/account/auth/verify-code")
        self.assertEqual(client.calls[1]["payload"], {"email": "user@example.com", "code": "12345678"})
        self.assertEqual(session.account_id, "arc_account_1")
        self.assertEqual(session.device_id, "dictate-desktop")

    def test_arc_forge_sign_in_registers_device_public_key_when_supplied(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        client.responses = [
            {"message": "If an account exists, a login code has been sent."},
            {
                "access_token": _unsigned_jwt("arc_account_1"),
                "refresh_token": "refresh_1",
                "expires_in": 3600,
            },
            {"device": {"account_id": "arc_account_1", "device_id": "device_registered"}},
        ]

        with patch.object(client, "_save_refresh_token", return_value=True):
            start = client.start_sign_in("user@example.com")
            session = client.complete_sign_in(
                challenge_id=start["challenge_id"],
                code="12345678",
                device_label="Workstation",
                device_public_key="public_key_1",
            )

        self.assertEqual(client.calls[2]["method"], "POST")
        self.assertEqual(client.calls[2]["path"], "/api/dictate/devices/register")
        self.assertEqual(
            client.calls[2]["payload"],
            {
                "device_id": "dictate-desktop",
                "device_label": "Workstation",
                "device_public_key": "public_key_1",
            },
        )
        self.assertEqual(client.calls[2]["auth"], _unsigned_jwt("arc_account_1"))
        self.assertEqual(session.device_id, "device_registered")

    def test_arc_forge_gateway_routes_hosted_jobs_under_api_dictate(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        audio = Path(self._tmp.name) / "meeting.wav"
        audio.write_bytes(b"wav")
        client.responses = [
            {},
            {
                "upload": {"upload_id": "upload_1", "status": "awaiting_upload"},
                "url": "https://objects.example.test/bucket/key?X-Amz-Signature=test",
            },
            {"job": {"job_id": "job_1", "status": "uploaded"}, "upload": {"upload_id": "upload_1", "status": "queued"}},
            {},
            {},
        ]

        with patch.object(client, "load_session", return_value=session):
            client.create_meeting(language="en", audio_duration_seconds=12.5)
            client.upload_meeting_audio("job_1", audio)
            client.get_meeting("job_1")
            client.get_transcript("job_1")

        self.assertEqual(client.calls[0]["path"], "/api/dictate/jobs")
        self.assertEqual(
            client.calls[0]["payload"],
            {"device_id": "device_1", "audio_duration_seconds": 12.5, "language": "en"},
        )
        self.assertEqual(client.calls[0]["auth"], "access")
        self.assertEqual(client.calls[1]["path"], "/api/dictate/jobs/job_1/audio-upload-url")
        self.assertEqual(client.calls[1]["payload"], {"byte_size": 3})
        self.assertEqual(client.put_uploads, [{"url": "https://objects.example.test/bucket/key?X-Amz-Signature=test", "data": b"wav", "content_type": "audio/wav"}])
        self.assertEqual(client.calls[2]["path"], "/api/dictate/jobs/job_1/audio-upload-complete")
        self.assertEqual(client.calls[2]["payload"], {"upload_id": "upload_1", "byte_size": 3})
        self.assertEqual(client.calls[3]["path"], "/api/dictate/jobs/job_1")
        self.assertEqual(client.calls[4]["path"], "/api/dictate/jobs/job_1/transcript")

    def test_arc_forge_gateway_routes_hosted_result_ack_and_cancel(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        with patch.object(client, "load_session", return_value=session):
            client.get_result("job_1")
            client.ack_result(
                "job_1",
                artifact_id="artifact_1",
                acknowledgement_id="ack_1",
                idempotency_key="idem_1",
            )
            client.cancel_job("job_1")

        self.assertEqual(client.calls[0]["path"], "/api/dictate/jobs/job_1/result")
        self.assertEqual(client.calls[1]["path"], "/api/dictate/jobs/job_1/result/ack")
        self.assertEqual(
            client.calls[1]["payload"],
            {
                "artifact_id": "artifact_1",
                "acknowledgement_id": "ack_1",
                "idempotency_key": "idem_1",
            },
        )
        self.assertEqual(client.calls[1]["headers"], {"Idempotency-Key": "idem_1"})
        self.assertEqual(client.calls[2]["path"], "/api/dictate/jobs/job_1/cancel")

    def test_arc_forge_gateway_routes_sync_under_api_dictate(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        record = encrypt_record(
            "arc_account_1",
            generate_account_key(),
            PlainSyncRecord(
                collection="history",
                record_id="hist_1",
                rev=1,
                updated_at="2026-07-05T12:00:00+00:00",
                device_id="device_1",
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "private"},
            ),
        )

        with patch.object(client, "load_session", return_value=session):
            client.push_sync_records([record])
            client.get_sync_changes(since=3, limit=10)
            client.update_sync_cursor(last_seq=10)
            client.save_key_envelope(envelope_kind="recovery", envelope={"ciphertext": "opaque"})
            client.list_key_envelopes(envelope_kind="recovery")

        self.assertEqual(client.calls[0]["path"], "/api/dictate/sync/push")
        self.assertEqual(client.calls[0]["auth"], "access")
        self.assertEqual(client.calls[1]["path"], "/api/dictate/sync/changes?since=3&limit=10")
        self.assertEqual(client.calls[2]["path"], "/api/dictate/sync/cursor")
        self.assertEqual(client.calls[3]["path"], "/api/dictate/sync/key-envelopes")
        self.assertEqual(client.calls[4]["path"], "/api/dictate/sync/key-envelopes?kind=recovery")

    def test_arc_forge_gateway_routes_account_device_actions_under_api_dictate(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )

        with patch.object(client, "load_session", return_value=session):
            client.list_devices()
            client.register_device(device_label="Desktop", device_public_key="public_key_1")
            client.revoke_device("device_2")
            client.export_cloud_data()
            client.delete_cloud_data(idempotency_key="delete-arc-1")

        self.assertEqual([call["path"] for call in client.calls], [
            "/api/dictate/devices",
            "/api/dictate/devices/register",
            "/api/dictate/devices/device_2/revoke",
            "/api/dictate/account/export",
            "/api/dictate/account/cloud-data",
        ])
        self.assertEqual(client.calls[1]["payload"]["device_public_key"], "public_key_1")
        self.assertEqual(client.calls[3]["headers"], {"X-Dictate-Device-Id": "device_1"})
        self.assertEqual(client.calls[4]["payload"], {"confirmation": "delete_cloud_data"})
        self.assertEqual(client.calls[4]["headers"]["Idempotency-Key"], "delete-arc-1")
        self.assertEqual(client.calls[4]["headers"]["X-Dictate-Device-Id"], "device_1")

    def test_drain_sync_outbox_removes_accepted_records(self) -> None:
        from dictate.sync import SyncOutbox

        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        outbox = SyncOutbox(
            path=Path(self._tmp.name) / "outbox.jsonl",
            account_id="arc_account_1",
            account_key=generate_account_key(),
            device_id="device_1",
        )
        outbox.enqueue(
            collection="history",
            record_id="hist_1",
            content_type="application/vnd.dictate.history+json;v=1",
            payload={"text": "private"},
        )
        client.responses = [
            {
                "results": [
                    {
                        "status": "accepted",
                        "record": {"collection": "history", "record_id": "hist_1"},
                    }
                ]
            }
        ]

        with patch.object(client, "load_session", return_value=session):
            result = client.drain_sync_outbox(outbox)

        self.assertEqual(result["pushed"], 1)
        self.assertEqual(outbox.pending(), [])

    def test_arc_forge_gateway_falls_back_to_raw_upload_when_signed_upload_disabled(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        audio = Path(self._tmp.name) / "meeting.wav"
        audio.write_bytes(b"wav")

        def fake_request(method, path, payload=None, *, auth=None, content_type="application/json"):
            client.calls.append(
                {
                    "method": method,
                    "path": path,
                    "payload": payload,
                    "auth": auth,
                    "content_type": content_type,
                }
            )
            if path.endswith("/audio-upload-url"):
                raise ProClientError(409, "Dictate signed object uploads are not enabled.")
            return {"job": {"job_id": "job_1", "status": "uploaded"}}

        with patch.object(client, "load_session", return_value=session), patch.object(client, "_request", side_effect=fake_request):
            result = client.upload_meeting_audio("job_1", audio)

        self.assertEqual(result["job"]["status"], "uploaded")
        self.assertEqual(client.calls[0]["path"], "/api/dictate/jobs/job_1/audio-upload-url")
        self.assertEqual(client.calls[1]["path"], "/api/dictate/jobs/job_1/audio")
        self.assertEqual(client.calls[1]["payload"], b"wav")
        self.assertEqual(client.calls[1]["content_type"], "audio/wav")
        self.assertEqual(client.put_uploads, [])

    def test_arc_forge_state_uses_shared_account_commerce_surface(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        client.responses = [
            {
                "account_id": "arc_account_1",
                "subscriptions": [{"product_line": "dictate", "status": "active"}],
                "entitlements": [{"entitlement_key": "dictate_pro", "status": "active"}],
            },
            {"active": True, "plan_id": "dictate_pro_monthly"},
            {"used_seconds": 120, "remaining_seconds": 89_880},
        ]

        with patch.object(client, "load_session", return_value=session):
            state = client.get_state()

        self.assertTrue(state["signedIn"])
        self.assertEqual(state["commerce"]["subscriptions"][0]["product_line"], "dictate")
        self.assertEqual(state["entitlements"]["plan_id"], "dictate_pro_monthly")
        self.assertEqual(state["usage"]["used_seconds"], 120)
        self.assertEqual(
            [call["path"] for call in client.calls],
            ["/api/account/commerce", "/api/dictate/entitlement", "/api/dictate/usage"],
        )
        self.assertEqual(client.calls[0]["auth"], "access")

    def test_get_state_gateway_outage_keeps_session(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )

        def fake_request(*args, **kwargs):
            raise ProClientError(503, "gateway unreachable")

        with patch.object(client, "load_session", return_value=session), patch.object(client, "_request", side_effect=fake_request), patch.object(client, "clear_session") as clear_session:
            state = client.get_state()

        self.assertTrue(state["signedIn"])
        self.assertEqual(state["lastError"], "gateway_outage")
        self.assertEqual(state["convergence"]["lastError"], "gateway_outage")
        clear_session.assert_not_called()

    def test_get_state_device_revoked_clears_session(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )

        def fake_request(*args, **kwargs):
            raise ProClientError(403, "Dictate device is revoked.")

        with patch.object(client, "load_session", return_value=session), patch.object(client, "_request", side_effect=fake_request):
            state = client.get_state()

        self.assertFalse(state["signedIn"])
        self.assertEqual(state["lastError"], "device_revoked")
        self.assertIsNone(client.load_session())

    def test_arc_forge_gateway_requires_duration_before_reserving_job(self) -> None:
        client = CapturingProClient(base_url="https://arcforge.au", session_path=self.session_path)
        session = ProSession(
            account_id="arc_account_1",
            device_id="device_1",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )
        with patch.object(client, "load_session", return_value=session):
            with self.assertRaises(ProClientError) as ctx:
                client.create_meeting()
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(client.calls, [])


class DeviceCodeVerificationUriClampTests(unittest.TestCase):
    """P2 regression: verification_uri(_complete) come verbatim from the gateway's
    device-code response -- unlike authorize_url (client-constructed), a compromised or
    MITM'd gateway could return a javascript:/file:/off-origin-http URI. _start_device_code
    must clamp both fields to https, or http on a loopback host, before they ever reach a
    caller that might window.open()/webbrowser.open() them.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.session_path = Path(self._tmp.name) / "pro-session.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _start(self, *, verification_uri: str, verification_uri_complete: str) -> dict[str, object]:
        client = CapturingProClient(base_url="http://127.0.0.1:18765", session_path=self.session_path)
        client.responses = [
            {
                "device_code": "dc_1",
                "user_code": "ABCD-EFGH",
                "expires_in": 900,
                "interval": 5,
                "verification_uri": verification_uri,
                "verification_uri_complete": verification_uri_complete,
            }
        ]
        return client._start_device_code("Desktop")  # noqa: SLF001

    def test_javascript_scheme_is_blanked(self) -> None:
        result = self._start(
            verification_uri="javascript:alert(1)",
            verification_uri_complete="javascript:alert(1)//ABCD-EFGH",
        )
        self.assertEqual(result["verification_uri"], "")
        self.assertEqual(result["verification_uri_complete"], "")

    def test_file_scheme_is_blanked(self) -> None:
        result = self._start(
            verification_uri="file:///etc/passwd",
            verification_uri_complete="file:///etc/passwd",
        )
        self.assertEqual(result["verification_uri"], "")
        self.assertEqual(result["verification_uri_complete"], "")

    def test_off_origin_http_is_blanked(self) -> None:
        result = self._start(
            verification_uri="http://evil.example.com/device",
            verification_uri_complete="http://evil.example.com/device?user_code=ABCD-EFGH",
        )
        self.assertEqual(result["verification_uri"], "")
        self.assertEqual(result["verification_uri_complete"], "")

    def test_https_uri_passes_through(self) -> None:
        result = self._start(
            verification_uri="https://console.arcforge.au/deck/link",
            verification_uri_complete="https://console.arcforge.au/deck/link?user_code=ABCD-EFGH",
        )
        self.assertEqual(result["verification_uri"], "https://console.arcforge.au/deck/link")
        self.assertEqual(
            result["verification_uri_complete"],
            "https://console.arcforge.au/deck/link?user_code=ABCD-EFGH",
        )

    def test_loopback_http_passes_through(self) -> None:
        # The local reference server itself replies over http://127.0.0.1:<port>/...
        result = self._start(
            verification_uri="http://127.0.0.1:18765/v1/auth/device",
            verification_uri_complete="http://127.0.0.1:18765/v1/auth/device?user_code=ABCD-EFGH",
        )
        self.assertEqual(result["verification_uri"], "http://127.0.0.1:18765/v1/auth/device")
        self.assertEqual(
            result["verification_uri_complete"],
            "http://127.0.0.1:18765/v1/auth/device?user_code=ABCD-EFGH",
        )


if __name__ == "__main__":
    unittest.main()
