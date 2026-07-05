from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import __main__ as main_module


def _run_pro(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main_module._handle_pro_commands(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class _FakeProBackend:
    def __init__(self) -> None:
        self.deleted = False
        self.disabled: dict[str, bool] | None = None
        self.approved: str | None = None
        self.revoked: str | None = None

    def get_state(self) -> dict:
        return {
            "dictatePro": {
                "signedIn": True,
                "account": {"account_id": "acct_cli", "device_id": "device_cli"},
                "entitlements": {"active": True, "features": {"sync": True}},
            },
            "sync": {
                "enabled": True,
                "accountId": "acct_cli",
                "deviceId": "device_cli",
                "keyAvailable": True,
                "lastSeq": 7,
                "lastResult": None,
            },
        }

    def start_pro_sign_in(self, email: str) -> dict:
        return {"email": email, "challenge_id": "challenge_1", "dev_code": "123456"}

    def complete_pro_sign_in(self, *, challenge_id: str, code: str, device_label: str = "Desktop") -> dict:
        return {"account_id": "acct_cli", "device_id": "device_cli", "signedIn": True}

    def sign_out_pro(self) -> dict:
        return {"signedIn": False}

    def enable_sync(self, *, recovery_key: str | None = None) -> dict:
        payload = self.get_state()["sync"]
        result = {"sync": payload, "deviceId": "device_cli"}
        if recovery_key is None:
            result["recoveryKey"] = "dictate-rk-example"
        return result

    def run_sync(self) -> dict:
        return {
            "sync": self.get_state()["sync"],
            "result": {"pushed": 2, "pulled": 3, "applied": 3, "lastSeq": 10},
            "history": [],
        }

    def disable_sync(self, *, clear_key: bool = False) -> dict:
        self.disabled = {"clear_key": clear_key}
        sync = {**self.get_state()["sync"], "enabled": False, "keyAvailable": not clear_key}
        return {"sync": sync}

    def list_pro_devices(self) -> dict:
        return {
            "devices": [
                {"device_id": "device_cli", "label": "Workstation", "trusted_at": "now", "revoked_at": None},
                {"device_id": "device_pending", "label": "Laptop", "trusted_at": None, "revoked_at": None},
            ]
        }

    def approve_pro_device(self, device_id: str) -> dict:
        self.approved = device_id
        return {"approved": True, "device": {"device_id": device_id}}

    def revoke_pro_device(self, device_id: str) -> dict:
        self.revoked = device_id
        return {"revoked": True, "device_id": device_id}

    def export_pro_cloud_data(self) -> dict:
        return {
            "account": {"account_id": "acct_cli"},
            "sync_records": [{"collection": "history", "ciphertext": "opaque"}],
        }

    def delete_pro_cloud_data(self) -> dict:
        self.deleted = True
        return {"cloud": {"deleted": {"sync_records": 1}}, "sync": {"enabled": False}}


class ProCliTests(unittest.TestCase):
    def test_status_prints_account_and_sync_without_plaintext(self) -> None:
        with patch("dictate.ui_server.UiBackend", return_value=_FakeProBackend()):
            code, out, err = _run_pro(["status"])

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("signed_in: yes", out)
        self.assertIn("account_id: acct_cli", out)
        self.assertIn("sync_enabled: yes", out)

    def test_main_dispatches_pro_subcommand(self) -> None:
        with patch("dictate.ui_server.UiBackend", return_value=_FakeProBackend()):
            code = main_module.main(["pro", "status"])

        self.assertEqual(code, 0)

    def test_sign_in_and_verify_use_backend_flow(self) -> None:
        with patch("dictate.ui_server.UiBackend", return_value=_FakeProBackend()):
            code, out, _ = _run_pro(["sign-in", "person@example.com"])
            verify_code, verify_out, _ = _run_pro(
                ["verify", "--challenge-id", "challenge_1", "--code", "123456", "--device-label", "Laptop"]
            )

        self.assertEqual(code, 0)
        self.assertIn("challenge_id: challenge_1", out)
        self.assertEqual(verify_code, 0)
        self.assertIn("signed in account_id=acct_cli device_id=device_cli", verify_out)

    def test_sync_enable_prints_recovery_key_once(self) -> None:
        with patch("dictate.ui_server.UiBackend", return_value=_FakeProBackend()):
            code, out, _ = _run_pro(["sync", "enable"])

        self.assertEqual(code, 0)
        self.assertIn("sync_enabled: yes", out)
        self.assertIn("recovery_key: dictate-rk-example", out)
        self.assertIn("not shown again", out)

    def test_sync_run_and_disable(self) -> None:
        backend = _FakeProBackend()
        with patch("dictate.ui_server.UiBackend", return_value=backend):
            code, out, _ = _run_pro(["sync", "run"])
            disable_code, disable_out, _ = _run_pro(["sync", "disable", "--clear-key"])

        self.assertEqual(code, 0)
        self.assertIn("pushed=2", out)
        self.assertEqual(disable_code, 0)
        self.assertEqual(backend.disabled, {"clear_key": True})
        self.assertIn("sync_enabled: no", disable_out)

    def test_device_list_approve_and_revoke(self) -> None:
        backend = _FakeProBackend()
        with patch("dictate.ui_server.UiBackend", return_value=backend):
            code, out, _ = _run_pro(["devices", "list"])
            approve_code, approve_out, _ = _run_pro(["devices", "approve", "device_pending"])
            revoke_code, revoke_out, _ = _run_pro(["devices", "revoke", "device_pending"])

        self.assertEqual(code, 0)
        self.assertIn("device_cli\ttrusted\tWorkstation", out)
        self.assertIn("device_pending\tpending\tLaptop", out)
        self.assertEqual(approve_code, 0)
        self.assertEqual(backend.approved, "device_pending")
        self.assertIn("approved device_id=device_pending", approve_out)
        self.assertEqual(revoke_code, 0)
        self.assertEqual(backend.revoked, "device_pending")
        self.assertIn("revoked device_id=device_pending", revoke_out)

    def test_cloud_export_writes_json_and_delete_requires_confirmation(self) -> None:
        backend = _FakeProBackend()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "export.json"
            with patch("dictate.ui_server.UiBackend", return_value=backend):
                code, out, _ = _run_pro(["cloud", "export", "--output", str(output)])
                blocked_code, _, blocked_err = _run_pro(["cloud", "delete"])
                delete_code, delete_out, _ = _run_pro(["cloud", "delete", "--yes"])

            exported = json.loads(output.read_text())

        self.assertEqual(code, 0)
        self.assertIn("cloud export written", out)
        self.assertEqual(exported["account"]["account_id"], "acct_cli")
        self.assertEqual(blocked_code, 2)
        self.assertIn("--yes", blocked_err)
        self.assertEqual(delete_code, 0)
        self.assertTrue(backend.deleted)
        self.assertIn("sync_records", delete_out)


if __name__ == "__main__":
    unittest.main()
