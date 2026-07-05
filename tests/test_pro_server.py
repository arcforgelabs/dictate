"""HTTP tests for the Dictate Pro control plane server."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from dataclasses import asdict
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import numpy as np

from dictate.pro.relay import RelayResult
from dictate.pro.server import ProRequestHandler, _RateLimiter, _get_rate_limiter
from dictate.pro.service import ProService, ProSettings
from dictate.pro.store import TranscriptSegmentRow
from dictate.sync import PlainSyncRecord, decrypt_record, encrypt_record, generate_account_key


def _request(
    base_url: str,
    method: str,
    path: str,
    payload: dict | bytes | None = None,
    *,
    token: str | None = None,
    content_type: str = "application/json",
) -> tuple[int, dict]:
    url = f"{base_url}{path}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data: bytes | None
    if isinstance(payload, dict):
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = content_type
    elif isinstance(payload, (bytes, bytearray)):
        data = bytes(payload)
        headers["Content-Type"] = content_type
    else:
        data = None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return exc.code, body


class ProServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DICTATE_PRO_DEV_AUTH"] = "1"
        settings = ProSettings(data_dir=Path(self._tmp.name))
        self.service = ProService(settings)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), ProRequestHandler)
        self.httpd.service = self.service  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.service.grant_subscription_for_testing(email="server@example.com")

    def _sign_in(self) -> str:
        return str(self._sign_in_session()["access_token"])

    def _sign_in_session(self) -> dict:
        status, start = _request(self.base_url, "POST", "/v1/auth/start", {"email": "server@example.com"})
        self.assertEqual(status, 200)
        status, complete = _request(
            self.base_url,
            "POST",
            "/v1/auth/complete",
            {
                "challenge_id": start["challenge_id"],
                "code": start["dev_code"],
                "device_public_key": "public_key_1",
            },
        )
        self.assertEqual(status, 200)
        return complete

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self._tmp.cleanup()
        os.environ.pop("DICTATE_PRO_DEV_AUTH", None)

    def test_auth_and_meeting_flow(self) -> None:
        token = self._sign_in()

        status, entitlements = _request(self.base_url, "GET", "/v1/entitlements", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(entitlements["active"])

        status, meeting = _request(self.base_url, "POST", "/v1/meetings", {}, token=token)
        self.assertEqual(status, 200)
        job_id = meeting["job_id"]

        fake = RelayResult(
            text="Speaker 1: hi",
            segments=[
                TranscriptSegmentRow(
                    seq=0,
                    speaker_id="0",
                    speaker_label="Speaker 1",
                    text="hi",
                    t_start=0.0,
                    t_end=1.0,
                )
            ],
            audio_duration_seconds=5.0,
            billable_seconds=5,
            provider_request_id="req_1",
            raw_response={},
        )
        wav = self._write_wav(seconds=5)
        with patch.object(self.service._settings, "transcribe", return_value=fake):
            status, upload = _request(
                self.base_url,
                "POST",
                f"/v1/meetings/{job_id}/audio",
                wav.read_bytes(),
                token=token,
                content_type="audio/wav",
            )
        self.assertEqual(status, 200)
        self.assertEqual(upload["job"]["status"], "ready")
        self.assertEqual(upload["usage"]["used_seconds"], 5)

        status, transcript = _request(
            self.base_url,
            "GET",
            f"/v1/meetings/{job_id}/transcript",
            token=token,
        )
        self.assertEqual(status, 200)
        self.assertIn("hi", transcript["text"])

    def test_sync_push_pull_stores_only_encrypted_payload(self) -> None:
        session = self._sign_in_session()
        token = str(session["access_token"])
        device_id = str(session["device_id"])
        key = generate_account_key()
        encrypted = encrypt_record(
            "acct_local",
            key,
            PlainSyncRecord(
                collection="history",
                record_id="hist_1",
                rev=1,
                updated_at="2026-07-05T12:00:00+00:00",
                device_id=device_id,
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "private dictated text"},
            ),
        )

        status, pushed = _request(
            self.base_url,
            "POST",
            "/v1/sync/push",
            {"records": [asdict(encrypted)]},
            token=token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(pushed["results"][0]["status"], "accepted")
        self.assertNotIn("private dictated text", json.dumps(pushed))

        raw_db = (Path(self._tmp.name) / "pro-control-plane.sqlite3").read_bytes()
        self.assertNotIn(b"private dictated text", raw_db)

        status, changes = _request(self.base_url, "GET", "/v1/sync/changes?since=0&limit=10", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(len(changes["records"]), 1)
        self.assertNotIn("private dictated text", json.dumps(changes))
        pulled = changes["records"][0]
        decrypted = decrypt_record(
            "acct_local",
            key,
            encrypted.__class__(
                collection=pulled["collection"],
                record_id=pulled["record_id"],
                rev=pulled["rev"],
                updated_at=pulled["updated_at"],
                device_id=pulled["device_id"],
                deleted=pulled["deleted"],
                content_type=pulled["content_type"],
                ciphertext=pulled["ciphertext"],
                nonce=pulled["nonce"],
                aad_hash=pulled["aad_hash"],
                payload_bytes=pulled["payload_bytes"],
            ),
        )
        self.assertEqual(decrypted["text"], "private dictated text")

    def test_sync_push_drops_accidental_plaintext_fields(self) -> None:
        session = self._sign_in_session()
        token = str(session["access_token"])
        device_id = str(session["device_id"])
        encrypted = encrypt_record(
            "acct_local",
            generate_account_key(),
            PlainSyncRecord(
                collection="history",
                record_id="hist_plaintext_bug",
                rev=1,
                updated_at="2026-07-05T12:00:00+00:00",
                device_id=device_id,
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "encrypted private text"},
            ),
        )
        raw = {
            **asdict(encrypted),
            "payload": {"text": "plaintext should not be stored"},
            "text": "plaintext should not be echoed",
        }

        status, pushed = _request(self.base_url, "POST", "/v1/sync/push", {"records": [raw]}, token=token)

        self.assertEqual(status, 200)
        self.assertNotIn("plaintext should not", json.dumps(pushed))
        status, exported = _request(self.base_url, "GET", "/v1/account/export", token=token)
        self.assertEqual(status, 200)
        self.assertNotIn("plaintext should not", json.dumps(exported))
        raw_db = (Path(self._tmp.name) / "pro-control-plane.sqlite3").read_bytes()
        self.assertNotIn(b"plaintext should not", raw_db)

    def test_sync_push_rejects_oversized_payloads(self) -> None:
        session = self._sign_in_session()
        token = str(session["access_token"])
        device_id = str(session["device_id"])
        encrypted = encrypt_record(
            "acct_local",
            generate_account_key(),
            PlainSyncRecord(
                collection="history",
                record_id="hist_oversized",
                rev=1,
                updated_at="2026-07-05T12:00:00+00:00",
                device_id=device_id,
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "private"},
            ),
        )
        raw = {**asdict(encrypted), "payload_bytes": 6 * 1024 * 1024}

        status, body = _request(self.base_url, "POST", "/v1/sync/push", {"records": [raw]}, token=token)

        self.assertEqual(status, 413)
        self.assertIn("too large", body["error"])

    def test_sync_push_uses_metadata_lww(self) -> None:
        session = self._sign_in_session()
        token = str(session["access_token"])
        device_id = str(session["device_id"])
        key = generate_account_key()
        newer = encrypt_record(
            "acct_local",
            key,
            PlainSyncRecord(
                collection="history",
                record_id="hist_1",
                rev=2,
                updated_at="2026-07-05T12:02:00+00:00",
                device_id=device_id,
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "newer"},
            ),
        )
        older = encrypt_record(
            "acct_local",
            key,
            PlainSyncRecord(
                collection="history",
                record_id="hist_1",
                rev=1,
                updated_at="2026-07-05T12:01:00+00:00",
                device_id=device_id,
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "older"},
            ),
        )

        status, first = _request(self.base_url, "POST", "/v1/sync/push", {"records": [asdict(newer)]}, token=token)
        status, second = _request(self.base_url, "POST", "/v1/sync/push", {"records": [asdict(older)]}, token=token)

        self.assertEqual(status, 200)
        self.assertEqual(first["results"][0]["status"], "accepted")
        self.assertEqual(second["results"][0]["status"], "superseded")

    def test_key_envelopes_round_trip_without_plaintext_key(self) -> None:
        session = self._sign_in_session()
        token = str(session["access_token"])
        device_id = str(session["device_id"])
        payload = {"version": 1, "ciphertext": "opaque-wrapped-account-key"}

        status, saved = _request(
            self.base_url,
            "POST",
            "/v1/sync/key-envelopes",
            {"envelope_kind": "recovery", "envelope": payload},
            token=token,
        )

        self.assertEqual(status, 200)
        self.assertEqual(saved["device_id"], device_id)
        self.assertEqual(saved["envelope"], payload)

        status, listed = _request(
            self.base_url,
            "GET",
            "/v1/sync/key-envelopes?kind=recovery",
            token=token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(listed["envelopes"][0]["envelope"], payload)
        self.assertNotIn("account data key", json.dumps(listed).lower())

    def test_sync_cursor_acknowledges_applied_sequence(self) -> None:
        session = self._sign_in_session()
        token = str(session["access_token"])

        status, cursor = _request(
            self.base_url,
            "POST",
            "/v1/sync/cursor",
            {"last_seq": 12},
            token=token,
        )

        self.assertEqual(status, 200)
        self.assertEqual(cursor["last_seq"], 12)
        status, devices = _request(self.base_url, "GET", "/v1/devices", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(devices["devices"][0]["public_key"], "public_key_1")

    def test_device_revoke_blocks_future_sync(self) -> None:
        session = self._sign_in_session()
        token = str(session["access_token"])
        device_id = str(session["device_id"])

        status, devices = _request(self.base_url, "GET", "/v1/devices", token=token)
        self.assertEqual(status, 200)
        self.assertTrue(any(device["device_id"] == device_id for device in devices["devices"]))

        status, revoked = _request(self.base_url, "POST", f"/v1/devices/{device_id}/revoke", {}, token=token)
        self.assertEqual(status, 200)
        self.assertTrue(revoked["revoked"])

        status, body = _request(self.base_url, "GET", "/v1/sync/changes?since=0", token=token)
        self.assertEqual(status, 401)
        self.assertIn("unauthorized", body["error"])

    def test_account_export_and_delete_cloud_data(self) -> None:
        session = self._sign_in_session()
        token = str(session["access_token"])
        device_id = str(session["device_id"])
        key = generate_account_key()
        encrypted = encrypt_record(
            "acct_local",
            key,
            PlainSyncRecord(
                collection="history",
                record_id="hist_export",
                rev=1,
                updated_at="2026-07-05T12:00:00+00:00",
                device_id=device_id,
                deleted=False,
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "private export text"},
            ),
        )
        status, _ = _request(self.base_url, "POST", "/v1/sync/push", {"records": [asdict(encrypted)]}, token=token)
        self.assertEqual(status, 200)

        status, exported = _request(self.base_url, "GET", "/v1/account/export", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(len(exported["sync_records"]), 1)
        self.assertNotIn("private export text", json.dumps(exported))

        status, deleted = _request(self.base_url, "DELETE", "/v1/account/cloud-data", token=token)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(deleted["deleted"]["sync_records"], 1)

        status, changes = _request(self.base_url, "GET", "/v1/sync/changes?since=0", token=token)
        self.assertEqual(status, 401)
        self.assertIn("unauthorized", changes["error"])

    def test_stripe_webhook_and_healthz_bypass_rate_limiter(self) -> None:
        import dictate.pro.server as server_module

        original = server_module._rate_limiter
        try:
            server_module._rate_limiter = _RateLimiter(rpm=1)
            status, _ = _request(self.base_url, "GET", "/healthz")
            self.assertEqual(status, 200)
            status, _ = _request(self.base_url, "GET", "/healthz")
            self.assertEqual(status, 200)

            os.environ["DICTATE_PRO_STRIPE_DEV"] = "1"
            payload = {
                "id": "evt_rate",
                "type": "customer.subscription.created",
                "created": 1_700_000_000,
                "data": {
                    "object": {
                        "id": "sub_rate",
                        "customer": "cus_missing",
                        "status": "active",
                        "current_period_start": 1_700_000_000,
                        "current_period_end": 1_700_086_400,
                        "cancel_at_period_end": False,
                        "items": {"data": [{"price": {"id": "price_pro"}}]},
                    }
                },
            }
            status, _ = _request(
                self.base_url,
                "POST",
                "/v1/webhooks/stripe",
                payload,
            )
            self.assertEqual(status, 200)
            status, _ = _request(
                self.base_url,
                "POST",
                "/v1/webhooks/stripe",
                {"id": "evt_rate_2", "type": "ping", "created": 1, "data": {"object": {}}},
            )
            self.assertEqual(status, 200)
        finally:
            server_module._rate_limiter = original
            os.environ.pop("DICTATE_PRO_STRIPE_DEV", None)

    def test_stripe_webhook_rejects_oversized_body(self) -> None:
        os.environ["DICTATE_PRO_STRIPE_DEV"] = "1"
        os.environ["DICTATE_PRO_WEBHOOK_MAX_BYTES"] = "10"
        try:
            status, body = _request(
                self.base_url,
                "POST",
                "/v1/webhooks/stripe",
                {"id": "evt_big", "type": "ping", "created": 1, "data": {"object": {}}},
                content_type="application/json",
            )
            self.assertEqual(status, 413)
            self.assertIn("too large", body["error"])
        finally:
            os.environ.pop("DICTATE_PRO_STRIPE_DEV", None)
            os.environ.pop("DICTATE_PRO_WEBHOOK_MAX_BYTES", None)

    def test_audio_upload_rejects_oversized_content_length(self) -> None:
        status, start = _request(self.base_url, "POST", "/v1/auth/start", {"email": "server@example.com"})
        self.assertEqual(status, 200)
        status, complete = _request(
            self.base_url,
            "POST",
            "/v1/auth/complete",
            {"challenge_id": start["challenge_id"], "code": start["dev_code"]},
        )
        self.assertEqual(status, 200)
        token = complete["access_token"]
        status, meeting = _request(self.base_url, "POST", "/v1/meetings", {}, token=token)
        self.assertEqual(status, 200)
        job_id = meeting["job_id"]
        os.environ["DICTATE_PRO_UPLOAD_MAX_BYTES"] = "10"
        try:
            url = f"{self.base_url}/v1/meetings/{job_id}/audio"
            request = urllib.request.Request(
                url,
                data=b"x" * 20,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "audio/wav",
                    "Content-Length": "20",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=10)  # noqa: S310
            self.assertEqual(ctx.exception.code, 413)
            body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertIn("too large", body["error"])
        finally:
            os.environ.pop("DICTATE_PRO_UPLOAD_MAX_BYTES", None)

    def _write_wav(self, *, seconds: int) -> Path:
        path = Path(self._tmp.name) / "sample.wav"
        sample_rate = 16000
        samples = np.zeros(sample_rate * seconds, dtype=np.int16)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(samples.tobytes())
        return path


if __name__ == "__main__":
    unittest.main()
