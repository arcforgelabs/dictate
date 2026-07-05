from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dictate.history import HistoryStore, MAX_ENTRIES
from dictate.sync import SyncOutbox, decrypt_record, generate_account_key


class HistoryStoreTests(unittest.TestCase):
    def test_append_stores_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "h.json")
            store.append("first")
            store.append("second")
            entries = store.load()
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].text, "second")
            self.assertEqual(entries[1].text, "first")

    def test_trims_to_max_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "h.json")
            for i in range(MAX_ENTRIES + 2):
                store.append(f"text-{i}")
            entries = store.load()
            self.assertEqual(len(entries), MAX_ENTRIES)
            # Newest is first.
            self.assertEqual(entries[0].text, f"text-{MAX_ENTRIES + 1}")

    def test_corrupted_file_recovers_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.json"
            path.write_text("NOT VALID JSON!!!")
            store = HistoryStore(path=path)
            entries = store.load()
            self.assertEqual(entries, [])
            # Append still works after corrupt file.
            store.append("recovery")
            entries = store.load()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].text, "recovery")

    def test_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "does-not-exist.json")
            self.assertEqual(store.load(), [])

    def test_empty_json_object_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.json"
            path.write_text("{}")
            store = HistoryStore(path=path)
            self.assertEqual(store.load(), [])

    def test_preserves_duplicate_texts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "h.json")
            store.append("same")
            store.append("same")
            entries = store.load()
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].text, "same")
            self.assertEqual(entries[1].text, "same")
            # Separate events have different IDs.
            self.assertNotEqual(entries[0].id, entries[1].id)

    def test_entries_have_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.json"
            store = HistoryStore(path=path)
            store.append("hello world")
            raw = json.loads(path.read_text())
            self.assertEqual(raw["version"], 1)
            entry = raw["entries"][0]
            self.assertIn("id", entry)
            self.assertIn("created_at", entry)
            self.assertEqual(entry["text"], "hello world")

    def test_ignores_entries_with_missing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.json"
            path.write_text(json.dumps({
                "version": 1,
                "entries": [
                    {"id": "a", "created_at": "b"},  # missing text
                    {"id": "c", "created_at": "d", "text": "good"},
                ],
            }))
            store = HistoryStore(path=path)
            entries = store.load()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].text, "good")

    def test_archive_hides_entry_without_deleting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "h.json")
            store.append("keep me")
            entry_id = store.load()[0].id

            self.assertTrue(store.archive(entry_id))
            self.assertEqual(store.load(), [])
            archived = store.load(include_archived=True)
            self.assertEqual(len(archived), 1)
            self.assertTrue(archived[0].archived)

    def test_unarchive_restores_visible_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(path=Path(tmp) / "h.json")
            store.append("keep me")
            entry_id = store.load()[0].id
            store.archive(entry_id)
            self.assertEqual(store.load(), [])

            self.assertTrue(store.unarchive(entry_id))
            restored = store.load()
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0].text, "keep me")
            self.assertFalse(restored[0].archived)

    def test_append_enqueues_encrypted_sync_record_when_outbox_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            outbox = SyncOutbox(
                path=Path(tmp) / "outbox.jsonl",
                account_id="acct_1",
                account_key=key,
                device_id="device_test",
            )
            store = HistoryStore(path=Path(tmp) / "h.json", sync_outbox=outbox)

            entry = store.append("private dictated text")

            raw_outbox = (Path(tmp) / "outbox.jsonl").read_text()
            self.assertNotIn("private dictated text", raw_outbox)
            pending = outbox.pending()
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].collection, "history")
            self.assertEqual(pending[0].record_id, entry.id)
            self.assertEqual(decrypt_record("acct_1", key, pending[0])["text"], "private dictated text")

    def test_trimming_history_does_not_enqueue_delete_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            outbox = SyncOutbox(
                path=Path(tmp) / "outbox.jsonl",
                account_id="acct_1",
                account_key=key,
                device_id="device_test",
            )
            store = HistoryStore(path=Path(tmp) / "h.json", sync_outbox=outbox)

            for i in range(MAX_ENTRIES + 2):
                store.append(f"text-{i}")

            self.assertEqual(len(store.load()), MAX_ENTRIES)
            self.assertFalse(any(record.deleted for record in outbox.pending()))


if __name__ == "__main__":
    unittest.main()
