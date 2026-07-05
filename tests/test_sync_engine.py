from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from dictate import config as config_mod
from dictate.history import HistoryStore
from dictate.note_store import NoteSegment, NoteStore
from dictate.sync import PlainSyncRecord, SyncSettingsStore, encrypt_record, generate_account_key
from dictate.sync_engine import SyncEngine
from dictate.ui_server import UiPrefsStore


class _FakeProClient:
    def __init__(self, records=None) -> None:
        self.records = list(records or [])
        self.drained = False
        self.changes_since: list[int] = []
        self.cursor_updates: list[int] = []

    def drain_sync_outbox(self, outbox):  # noqa: ANN001
        self.drained = True
        pending = outbox.pending()
        outbox.replace_pending([])
        return {"pushed": len(pending), "remaining": 0, "results": []}

    def get_sync_changes(self, *, since: int = 0, limit: int = 500):
        self.changes_since.append(since)
        return {"next_seq": self.records[-1]["seq"] if self.records else since, "records": self.records}

    def update_sync_cursor(self, *, last_seq: int):
        self.cursor_updates.append(last_seq)
        return {"last_seq": last_seq}


class _FailingProClient(_FakeProClient):
    def __init__(self, *, fail_push: bool = False, fail_pull: bool = False, fail_cursor: bool = False) -> None:
        super().__init__()
        self.fail_push = fail_push
        self.fail_pull = fail_pull
        self.fail_cursor = fail_cursor

    def drain_sync_outbox(self, outbox):  # noqa: ANN001
        if self.fail_push:
            raise RuntimeError("offline")
        return super().drain_sync_outbox(outbox)

    def get_sync_changes(self, *, since: int = 0, limit: int = 500):
        if self.fail_pull:
            raise RuntimeError("offline")
        return super().get_sync_changes(since=since, limit=limit)

    def update_sync_cursor(self, *, last_seq: int):
        if self.fail_cursor:
            raise RuntimeError("offline")
        return super().update_sync_cursor(last_seq=last_seq)


class _SharedCloudClient:
    def __init__(self, cloud: list[dict], cursor_updates: list[int]) -> None:
        self.cloud = cloud
        self.cursor_updates = cursor_updates

    def drain_sync_outbox(self, outbox):  # noqa: ANN001
        pending = outbox.pending()
        for record in pending:
            self.cloud.append({**asdict(record), "seq": len(self.cloud) + 1})
        outbox.replace_pending([])
        return {"pushed": len(pending), "remaining": 0, "results": []}

    def get_sync_changes(self, *, since: int = 0, limit: int = 500):
        records = [record for record in self.cloud if int(record["seq"]) > since][:limit]
        next_seq = records[-1]["seq"] if records else since
        return {"next_seq": next_seq, "records": records}

    def update_sync_cursor(self, *, last_seq: int):
        self.cursor_updates.append(last_seq)
        return {"last_seq": last_seq}


class SyncEngineTests(unittest.TestCase):
    def _settings(
        self,
        tmp: str,
        account_id: str,
        key: bytes,
        *,
        device_id: str | None = None,
    ) -> SyncSettingsStore:
        saved: dict[str, str] = {}
        store = SyncSettingsStore(
            path=Path(tmp) / "state.json",
            device_path=Path(tmp) / "device.json",
            outbox_path=Path(tmp) / "outbox.jsonl",
            save_key=lambda account, encoded: saved.__setitem__(account, encoded),
            read_key=lambda account: saved.get(account),
            clear_key=lambda account: saved.pop(account, None),
        )
        store.enable(account_id, account_key=key, device_id=device_id)
        return store

    def test_disabled_sync_detaches_outboxes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = SyncSettingsStore(path=Path(tmp) / "state.json", device_path=Path(tmp) / "device.json")
            history = HistoryStore(Path(tmp) / "history.json")
            notes = NoteStore(Path(tmp) / "notes")
            engine = SyncEngine(settings=settings, pro_client=_FakeProClient(), history_store=history, note_store=notes)

            result = engine.run_once()

            self.assertFalse(result.enabled)
            self.assertIsNone(history._sync_outbox)
            self.assertIsNone(notes._sync_outbox)

    def test_pull_applies_history_and_advances_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            record = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="history",
                    record_id="hist_1",
                    rev=1,
                    updated_at="2026-07-05T12:00:00+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.history+json;v=1",
                    payload={
                        "id": "hist_1",
                        "created_at": "2026-07-05T12:00:00+00:00",
                        "updated_at": "2026-07-05T12:00:00+00:00",
                        "rev": 1,
                        "text": "synced private note",
                        "archived": False,
                    },
                ),
            )
            changes = [{**asdict(record), "seq": 11}]
            settings = self._settings(tmp, account_id, key)
            history = HistoryStore(Path(tmp) / "history.json")
            notes = NoteStore(Path(tmp) / "notes")
            client = _FakeProClient(changes)
            engine = SyncEngine(
                settings=settings,
                pro_client=client,
                history_store=history,
                note_store=notes,
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 1)
            self.assertEqual(settings.load().last_seq, 11)
            self.assertEqual(client.cursor_updates, [11])
            self.assertEqual(history.load()[0].text, "synced private note")

    def test_pull_tampered_record_returns_error_without_advancing_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            good = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="history",
                    record_id="hist_good",
                    rev=1,
                    updated_at="2026-07-05T12:00:00+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.history+json;v=1",
                    payload={
                        "id": "hist_good",
                        "created_at": "2026-07-05T12:00:00+00:00",
                        "updated_at": "2026-07-05T12:00:00+00:00",
                        "rev": 1,
                        "text": "valid private note",
                        "archived": False,
                    },
                ),
            )
            bad = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="history",
                    record_id="hist_bad",
                    rev=1,
                    updated_at="2026-07-05T12:00:01+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.history+json;v=1",
                    payload={"id": "hist_bad", "text": "tampered private note"},
                ),
            )
            tampered = {**asdict(bad), "seq": 2}
            tampered["ciphertext"] = tampered["ciphertext"][:-2] + "AA"
            settings = self._settings(tmp, account_id, key)
            history = HistoryStore(Path(tmp) / "history.json")
            client = _FakeProClient([{**asdict(good), "seq": 1}, tampered])
            engine = SyncEngine(
                settings=settings,
                pro_client=client,
                history_store=history,
                note_store=NoteStore(Path(tmp) / "notes"),
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 1)
            self.assertEqual(result.last_seq, 0)
            self.assertIn("invalid encrypted sync record at seq 2", result.error or "")
            self.assertEqual(settings.load().last_seq, 0)
            self.assertEqual(client.cursor_updates, [])
            self.assertEqual(history.load()[0].text, "valid private note")

    def test_pull_applies_realistic_history_volume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            records = []
            for idx in range(1000):
                seq = idx + 1
                record_id = f"hist_{seq}"
                encrypted = encrypt_record(
                    account_id,
                    key,
                    PlainSyncRecord(
                        collection="history",
                        record_id=record_id,
                        rev=1,
                        updated_at=f"2026-07-05T12:{idx // 60:02d}:{idx % 60:02d}+00:00",
                        device_id="device_remote",
                        deleted=False,
                        content_type="application/vnd.dictate.history+json;v=1",
                        payload={
                            "id": record_id,
                            "created_at": "2026-07-05T12:00:00+00:00",
                            "updated_at": f"2026-07-05T12:{idx // 60:02d}:{idx % 60:02d}+00:00",
                            "rev": 1,
                            "text": f"private synced note {seq}",
                            "archived": False,
                        },
                    ),
                )
                records.append({**asdict(encrypted), "seq": seq})
            settings = self._settings(tmp, account_id, key)
            history = HistoryStore(Path(tmp) / "history.json")
            client = _FakeProClient(records)
            engine = SyncEngine(
                settings=settings,
                pro_client=client,
                history_store=history,
                note_store=NoteStore(Path(tmp) / "notes"),
            )

            result = engine.run_once(limit=1000)

            self.assertEqual(result.pulled, 1000)
            self.assertEqual(result.applied, 1000)
            self.assertEqual(settings.load().last_seq, 1000)
            self.assertEqual(client.cursor_updates, [1000])
            loaded = history.load()
            self.assertEqual(len(loaded), 20)
            self.assertEqual(loaded[0].text, "private synced note 1000")
            self.assertEqual(loaded[-1].text, "private synced note 981")

    def test_pull_applies_note_and_segment_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            note = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="note",
                    record_id="note_1",
                    rev=1,
                    updated_at="2026-07-05T12:00:00+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.note+json;v=1",
                    payload={
                        "note_id": "note_1",
                        "mode": "meeting",
                        "provider": "parakeet",
                        "model": "parakeet-tdt-0.6b-v2",
                        "started_at": "2026-07-05T12:00:00+00:00",
                        "ended_at": "2026-07-05T12:00:10+00:00",
                        "duration_s": 10.0,
                        "status": "ready",
                        "speaker_labels": True,
                        "archived": False,
                    },
                ),
            )
            segment = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="segment",
                    record_id="note_1:0",
                    rev=1,
                    updated_at="2026-07-05T12:00:01+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.segment+json;v=1",
                    payload={
                        "note_id": "note_1",
                        "seq": 0,
                        "t_start": 0.0,
                        "t_end": 1.0,
                        "provider": "parakeet",
                        "model": "parakeet-tdt-0.6b-v2",
                        "text": "hello",
                        "speaker_label": "Speaker 1",
                    },
                ),
            )
            settings = self._settings(tmp, account_id, key)
            notes = NoteStore(Path(tmp) / "notes")
            engine = SyncEngine(
                settings=settings,
                pro_client=_FakeProClient([{**asdict(note), "seq": 1}, {**asdict(segment), "seq": 2}]),
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=notes,
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 2)
            self.assertEqual(notes.assembled_text("note_1"), "Speaker 1: hello")

    def test_push_drains_local_outbox_before_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            settings = self._settings(tmp, "acct_1", key)
            outbox = settings.outbox()
            assert outbox is not None
            outbox.enqueue(
                collection="history",
                record_id="hist_1",
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"id": "hist_1", "text": "private"},
            )
            client = _FakeProClient()
            engine = SyncEngine(
                settings=settings,
                pro_client=client,
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=NoteStore(Path(tmp) / "notes"),
            )

            result = engine.run_once()

            self.assertTrue(client.drained)
            self.assertEqual(result.pushed, 1)
            self.assertEqual(outbox.pending(), [])

    def test_offline_push_keeps_outbox_and_returns_sync_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            settings = self._settings(tmp, "acct_1", key)
            outbox = settings.outbox()
            assert outbox is not None
            outbox.enqueue(
                collection="history",
                record_id="hist_1",
                content_type="application/vnd.dictate.history+json;v=1",
                payload={"id": "hist_1", "text": "queued offline"},
            )
            engine = SyncEngine(
                settings=settings,
                pro_client=_FailingProClient(fail_push=True),
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=NoteStore(Path(tmp) / "notes"),
            )

            result = engine.run_once()

            self.assertEqual(result.pushed, 0)
            self.assertEqual(result.remaining, 1)
            self.assertEqual(result.last_seq, 0)
            self.assertIn("sync push failed", result.error or "")
            self.assertEqual([record.record_id for record in outbox.pending()], ["hist_1"])

    def test_offline_pull_returns_error_without_advancing_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            settings = self._settings(tmp, "acct_1", key)
            engine = SyncEngine(
                settings=settings,
                pro_client=_FailingProClient(fail_pull=True),
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=NoteStore(Path(tmp) / "notes"),
            )

            result = engine.run_once()

            self.assertEqual(result.pushed, 0)
            self.assertEqual(result.last_seq, 0)
            self.assertIn("sync pull failed", result.error or "")
            self.assertEqual(settings.load().last_seq, 0)

    def test_first_sync_keeps_local_and_remote_history_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            settings = self._settings(tmp, account_id, key)
            history = HistoryStore(Path(tmp) / "history.json")
            notes = NoteStore(Path(tmp) / "notes")
            engine = SyncEngine(
                settings=settings,
                pro_client=_FakeProClient([
                    {
                        **asdict(encrypt_record(
                            account_id,
                            key,
                            PlainSyncRecord(
                                collection="history",
                                record_id="hist_remote",
                                rev=1,
                                updated_at="2026-07-05T12:00:00+00:00",
                                device_id="device_remote",
                                deleted=False,
                                content_type="application/vnd.dictate.history+json;v=1",
                                payload={
                                    "id": "hist_remote",
                                    "created_at": "2026-07-05T12:00:00+00:00",
                                    "updated_at": "2026-07-05T12:00:00+00:00",
                                    "rev": 1,
                                    "text": "remote first-sync note",
                                    "archived": False,
                                },
                            ),
                        )),
                        "seq": 1,
                    }
                ]),
                history_store=history,
                note_store=notes,
            )
            engine.attach_outbox()
            history.append("local first-sync note")

            result = engine.run_once()

            self.assertEqual(result.pushed, 1)
            texts = {entry.text for entry in history.load()}
            self.assertEqual(texts, {"local first-sync note", "remote first-sync note"})

    def test_first_sync_remote_older_history_does_not_overwrite_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            history = HistoryStore(Path(tmp) / "history.json")
            self.assertTrue(
                history.apply_synced_entry(
                    {
                        "id": "hist_shared",
                        "created_at": "2026-07-05T12:00:00+00:00",
                        "updated_at": "2026-07-05T12:02:00+00:00",
                        "rev": 2,
                        "text": "newer local version",
                        "archived": False,
                    }
                )
            )
            older_remote = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="history",
                    record_id="hist_shared",
                    rev=1,
                    updated_at="2026-07-05T12:01:00+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.history+json;v=1",
                    payload={
                        "id": "hist_shared",
                        "created_at": "2026-07-05T12:00:00+00:00",
                        "updated_at": "2026-07-05T12:01:00+00:00",
                        "rev": 1,
                        "text": "older remote version",
                        "archived": False,
                    },
                ),
            )
            engine = SyncEngine(
                settings=self._settings(tmp, account_id, key),
                pro_client=_FakeProClient([{**asdict(older_remote), "seq": 2}]),
                history_store=history,
                note_store=NoteStore(Path(tmp) / "notes"),
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 1)
            entries = history.load()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].text, "newer local version")
            self.assertEqual(entries[0].rev, 2)

    def test_first_sync_two_populated_devices_converges_without_deleting_local_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = generate_account_key()
            account_id = "acct_1"
            cloud: list[dict] = []
            cursor_updates_a: list[int] = []
            cursor_updates_b: list[int] = []

            settings_a = self._settings(str(root / "device-a"), account_id, key, device_id="device_a")
            settings_b = self._settings(str(root / "device-b"), account_id, key, device_id="device_b")
            history_a = HistoryStore(root / "device-a" / "history.json")
            history_b = HistoryStore(root / "device-b" / "history.json")
            engine_a = SyncEngine(
                settings=settings_a,
                pro_client=_SharedCloudClient(cloud, cursor_updates_a),
                history_store=history_a,
                note_store=NoteStore(root / "device-a" / "notes"),
            )
            engine_b = SyncEngine(
                settings=settings_b,
                pro_client=_SharedCloudClient(cloud, cursor_updates_b),
                history_store=history_b,
                note_store=NoteStore(root / "device-b" / "notes"),
            )
            engine_a.attach_outbox()
            engine_b.attach_outbox()
            local_a = history_a.append("device A offline note")
            local_b = history_b.append("device B offline note")

            first_a = engine_a.run_once()
            first_b = engine_b.run_once()
            second_a = engine_a.run_once()

            self.assertEqual(first_a.pushed, 1)
            self.assertEqual(first_b.pushed, 1)
            self.assertEqual(second_a.pushed, 0)
            self.assertEqual({entry.text for entry in history_a.load()}, {"device A offline note", "device B offline note"})
            self.assertEqual({entry.text for entry in history_b.load()}, {"device A offline note", "device B offline note"})
            self.assertEqual([record["seq"] for record in cloud], [1, 2])
            self.assertFalse(any(record["deleted"] for record in cloud))
            self.assertEqual({record["record_id"] for record in cloud}, {local_a.id, local_b.id})
            self.assertEqual(settings_a.load().last_seq, 2)
            self.assertEqual(settings_b.load().last_seq, 2)
            self.assertEqual(cursor_updates_a, [1, 2])
            self.assertEqual(cursor_updates_b, [2])

    def test_pull_applies_portable_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            records = [
                encrypt_record(
                    account_id,
                    key,
                    PlainSyncRecord(
                        collection="settings",
                        record_id=f"prefs.{pref_key}",
                        rev=1,
                        updated_at="2026-07-05T12:00:00+00:00",
                        device_id="device_remote",
                        deleted=False,
                        content_type="application/vnd.dictate.setting+json;v=1",
                        payload={"key": pref_key, "value": value},
                    ),
                )
                for pref_key, value in (
                    ("theme", "dark"),
                    ("activation", "toggle"),
                    ("outputFormat", "markdown"),
                )
            ]
            prefs = UiPrefsStore(Path(tmp) / "prefs.json")
            engine = SyncEngine(
                settings=self._settings(tmp, account_id, key),
                pro_client=_FakeProClient([{**asdict(record), "seq": seq} for seq, record in enumerate(records, start=3)]),
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=NoteStore(Path(tmp) / "notes"),
                config_path=Path(tmp) / "config.yaml",
                prefs_store=prefs,
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 3)
            loaded = prefs.load()
            self.assertEqual(loaded["theme"], "dark")
            self.assertEqual(loaded["activation"], "toggle")
            self.assertEqual(loaded["outputFormat"], "markdown")

    def test_pull_skips_stale_portable_setting_and_advances_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            record = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="settings",
                    record_id="prefs.theme",
                    rev=1,
                    updated_at="2026-07-05T12:00:00+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.setting+json;v=1",
                    payload={"key": "theme", "value": "light"},
                ),
            )
            prefs = UiPrefsStore(Path(tmp) / "prefs.json")
            prefs.update({"theme": "dark"}, updated_at="2026-07-05T12:00:01+00:00")
            settings = self._settings(tmp, account_id, key)
            client = _FakeProClient([{**asdict(record), "seq": 3}])
            engine = SyncEngine(
                settings=settings,
                pro_client=client,
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=NoteStore(Path(tmp) / "notes"),
                config_path=Path(tmp) / "config.yaml",
                prefs_store=prefs,
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 0)
            self.assertEqual(result.last_seq, 3)
            self.assertEqual(settings.load().last_seq, 3)
            self.assertEqual(client.cursor_updates, [3])
            self.assertEqual(prefs.load()["theme"], "dark")

    def test_pull_applies_lexicon_hotword_and_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = generate_account_key()
            account_id = "acct_1"
            hotword = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="lexicon",
                    record_id="hotword_1",
                    rev=1,
                    updated_at="2026-07-05T12:00:00+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.lexicon+json;v=1",
                    payload={"kind": "hotword", "term": "OpenClaw"},
                ),
            )
            replacement = encrypt_record(
                account_id,
                key,
                PlainSyncRecord(
                    collection="lexicon",
                    record_id="replacement_1",
                    rev=1,
                    updated_at="2026-07-05T12:00:01+00:00",
                    device_id="device_remote",
                    deleted=False,
                    content_type="application/vnd.dictate.lexicon+json;v=1",
                    payload={"kind": "replacement", "wrong": "openc law", "right": "OpenClaw"},
                ),
            )
            config_path = Path(tmp) / "config.yaml"
            engine = SyncEngine(
                settings=self._settings(tmp, account_id, key),
                pro_client=_FakeProClient([{**asdict(hotword), "seq": 4}, {**asdict(replacement), "seq": 5}]),
                history_store=HistoryStore(Path(tmp) / "history.json"),
                note_store=NoteStore(Path(tmp) / "notes"),
                config_path=config_path,
            )

            result = engine.run_once()

            self.assertEqual(result.applied, 2)
            cfg = config_mod.load_config(config_path)
            self.assertIn("OpenClaw", cfg.hotwords)
            self.assertEqual(cfg.lexicon_replacements["openc law"], "OpenClaw")


if __name__ == "__main__":
    unittest.main()
