from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from cryptography.exceptions import InvalidTag

from dictate.sync import (
    PlainSyncRecord,
    SyncSettingsStore,
    SyncOutbox,
    decrypt_record,
    encode_key,
    decode_key,
    encrypt_record,
    generate_account_key,
    load_or_create_device,
)


class SyncCryptoTests(unittest.TestCase):
    def test_device_id_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "device.json"
            first = load_or_create_device(path)
            second = load_or_create_device(path)

            self.assertEqual(first.device_id, second.device_id)
            self.assertTrue(first.device_id.startswith("device_"))

    def test_key_round_trips_as_base64(self) -> None:
        key = generate_account_key()

        self.assertEqual(decode_key(encode_key(key)), key)

    def test_encrypt_record_hides_plaintext_and_decrypts_locally(self) -> None:
        key = generate_account_key()
        record = PlainSyncRecord(
            collection="history",
            record_id="hist_1",
            rev=1,
            updated_at="2026-07-05T12:00:00+00:00",
            device_id="device_test",
            deleted=False,
            content_type="application/vnd.dictate.history+json;v=1",
            payload={"text": "private dictated text"},
        )

        encrypted = encrypt_record("acct_1", key, record)

        serialized = json.dumps(asdict(encrypted))
        self.assertNotIn("private dictated text", serialized)
        self.assertEqual(decrypt_record("acct_1", key, encrypted), record.payload)

    def test_wrong_key_cannot_decrypt_record(self) -> None:
        record = PlainSyncRecord(
            collection="history",
            record_id="hist_1",
            rev=1,
            updated_at="2026-07-05T12:00:00+00:00",
            device_id="device_test",
            deleted=False,
            content_type="application/vnd.dictate.history+json;v=1",
            payload={"text": "private dictated text"},
        )
        encrypted = encrypt_record("acct_1", generate_account_key(), record)

        with self.assertRaises(InvalidTag):
            decrypt_record("acct_1", generate_account_key(), encrypted)

    def test_metadata_tampering_fails_before_decrypt(self) -> None:
        record = PlainSyncRecord(
            collection="history",
            record_id="hist_1",
            rev=1,
            updated_at="2026-07-05T12:00:00+00:00",
            device_id="device_test",
            deleted=False,
            content_type="application/vnd.dictate.history+json;v=1",
            payload={"text": "private dictated text"},
        )
        key = generate_account_key()
        encrypted = encrypt_record("acct_1", key, record)
        tampered = encrypted.__class__(**{**asdict(encrypted), "record_id": "hist_2"})

        with self.assertRaisesRegex(ValueError, "metadata authentication hash"):
            decrypt_record("acct_1", key, tampered)


class SyncOutboxTests(unittest.TestCase):
    def test_outbox_persists_encrypted_records_without_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            outbox_path = Path(tmp) / "outbox.jsonl"
            outbox = SyncOutbox(
                path=outbox_path,
                account_id="acct_1",
                account_key=key,
                device_id="device_test",
            )

            outbox.enqueue(
                collection="history",
                record_id="hist_1",
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "private dictated text"},
            )

            self.assertNotIn("private dictated text", outbox_path.read_text())
            pending = outbox.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(decrypt_record("acct_1", key, pending[0])["text"], "private dictated text")

    def test_replace_pending_removes_acked_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            outbox = SyncOutbox(
                path=Path(tmp) / "outbox.jsonl",
                account_id="acct_1",
                account_key=key,
                device_id="device_test",
            )
            first = outbox.enqueue(
                collection="history",
                record_id="hist_1",
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "first"},
            )
            second = outbox.enqueue(
                collection="history",
                record_id="hist_2",
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"text": "second"},
            )

            outbox.replace_pending([second])

            self.assertEqual([record.record_id for record in outbox.pending()], ["hist_2"])
            self.assertEqual(first.record_id, "hist_1")


class SyncSettingsStoreTests(unittest.TestCase):
    def test_enable_sync_stores_only_non_secret_state_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saved: dict[str, str] = {}
            key = generate_account_key()
            store = SyncSettingsStore(
                path=Path(tmp) / "state.json",
                device_path=Path(tmp) / "device.json",
                outbox_path=Path(tmp) / "outbox.jsonl",
                save_key=lambda account_id, encoded: saved.__setitem__(account_id, encoded),
                read_key=lambda account_id: saved.get(account_id),
                clear_key=lambda account_id: saved.pop(account_id, None),
            )

            state, returned_key = store.enable("acct_1", account_key=key)

            self.assertTrue(state.enabled)
            self.assertEqual(returned_key, key)
            raw_state = (Path(tmp) / "state.json").read_text()
            self.assertIn("acct_1", raw_state)
            self.assertNotIn(encode_key(key), raw_state)
            self.assertEqual(store.account_key(), key)

    def test_disable_can_clear_secret_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saved: dict[str, str] = {}
            store = SyncSettingsStore(
                path=Path(tmp) / "state.json",
                device_path=Path(tmp) / "device.json",
                outbox_path=Path(tmp) / "outbox.jsonl",
                save_key=lambda account_id, encoded: saved.__setitem__(account_id, encoded),
                read_key=lambda account_id: saved.get(account_id),
                clear_key=lambda account_id: saved.pop(account_id, None),
            )
            store.enable("acct_1")

            state = store.disable(clear_key=True)

            self.assertFalse(state.enabled)
            self.assertEqual(saved, {})
            self.assertIsNone(store.account_key())


if __name__ == "__main__":
    unittest.main()
