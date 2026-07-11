from __future__ import annotations

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from dictate.api_keys import ApiKeyStatus
from dictate import config as config_mod
from dictate.history import HistoryStore
from dictate.note_store import NoteSegment, NoteStore
from dictate.pro.client import ProClientError, ProSession
from dictate.sync import SyncSettingsStore, decrypt_record, generate_device_key_pair
from dictate.update_status import UpdateFlow, UpdateStatus
from dictate.version import RELEASE_VERSION
from dictate.ui_server import (
    ApiError,
    DEFAULT_PREFS,
    EventBroker,
    UiBackend,
    UiPrefsStore,
    serve,
    write_runtime_handshake,
)


def _backend(temp_dir: str, **overrides) -> UiBackend:
    """A UiBackend wired to temp paths and harmless fakes (no keyring/autostart)."""
    base = Path(temp_dir)
    kwargs = dict(
        config_path=base / "config.yaml",
        history_store=HistoryStore(base / "history.json"),
        note_store=NoteStore(base / "notes"),
        prefs_store=UiPrefsStore(base / "ui-prefs.json"),
        save_api_key=lambda backend, key: None,
        clear_api_key=lambda backend: None,
        api_key_status=lambda backend, **kw: ApiKeyStatus(backend=backend, status="None"),
        validate_api_key_format=lambda backend, key: None,
        secret_store_description=lambda: "the desktop Secret Service keyring",
        secret_store_available=lambda: True,
        check_update_status=lambda: UpdateStatus(
            current_version=RELEASE_VERSION,
            latest_version=RELEASE_VERSION,
            update_available=True,
            checked=True,
            url="https://example.test/releases",
            platform="linux",
            install_kind="linux-package",
            phase="available",
            step="ready",
            progress=0,
            actions=["check", "open_release"],
            commands={"release": "https://example.test/releases"},
            missing_deps=[],
        ),
        start_update_flow=lambda: UpdateFlow(
            mode="release",
            started=False,
            url="https://example.test/releases",
            message="Open the latest Linux package.",
            platform="linux",
            install_kind="linux-package",
            phase="manual",
            step="release",
            progress=0,
            actions=["open_release"],
            commands={"release": "https://example.test/releases"},
            missing_deps=[],
        ),
        startup_enabled=lambda: True,
        set_startup_enabled=lambda enabled: None,
        # Structural safety net: UiBackend's real default is webbrowser.open, which would
        # otherwise launch an actual browser tab any time a test enables browser sign-in
        # and drives a "loopback" start result. No-op here; tests that need to assert
        # "did it open" pass their own recorder via **overrides (which wins below).
        open_browser=lambda url: None,
    )
    kwargs.update(overrides)
    return UiBackend(**kwargs)


class _FakeNoteDaemon:
    def __init__(self) -> None:
        self.note_recording_active = False
        self.note_recording_paused = False
        self.long_recording_mode = None
        self.calls: list[str] = []
        self.meeting_backend_model: tuple[str, str] | None = None

    @property
    def long_recording_active(self) -> bool:
        return self.note_recording_active

    def start_note_recording(self) -> bool:
        self.calls.append("start")
        self.note_recording_active = True
        self.note_recording_paused = False
        self.long_recording_mode = "note"
        return True

    def start_meeting_recording(self) -> bool:
        self.calls.append("start-meeting")
        self.note_recording_active = True
        self.note_recording_paused = False
        self.long_recording_mode = "meeting"
        return True

    def current_meeting_backend_model(self) -> tuple[str, str] | None:
        return self.meeting_backend_model

    def set_meeting_speech_to_text(self, stt, *, hotwords=None) -> None:  # noqa: ANN001, ANN201
        del hotwords
        self.calls.append("set-meeting")
        self.meeting_backend_model = (stt.backend_name, stt.model_name)

    def pause_note_recording(self) -> bool:
        self.calls.append("pause")
        if not self.note_recording_active:
            return False
        self.note_recording_paused = True
        return True

    def resume_note_recording(self) -> bool:
        self.calls.append("resume")
        if not self.note_recording_paused:
            return False
        self.note_recording_paused = False
        return True

    def stop_note_recording(self) -> bool:
        self.calls.append("stop")
        self.note_recording_active = False
        self.note_recording_paused = False
        return True

    def stop_meeting_recording(self) -> bool:
        self.calls.append("stop-meeting")
        self.note_recording_active = False
        self.note_recording_paused = False
        return True

    def cancel_note_recording(self) -> bool:
        self.calls.append("discard")
        self.note_recording_active = False
        self.note_recording_paused = False
        return True

    def cancel_meeting_recording(self) -> bool:
        self.calls.append("discard-meeting")
        self.note_recording_active = False
        self.note_recording_paused = False
        return True

    def toggle_note_recording(self) -> bool:
        self.calls.append("toggle")
        if self.note_recording_paused:
            self.note_recording_paused = False
            return True
        if self.note_recording_active:
            self.note_recording_active = False
            self.note_recording_paused = False
            return False
        self.note_recording_active = True
        return True


class _FakeProClient:
    def __init__(self) -> None:
        self.current_device_keys = generate_device_key_pair()
        self.create_calls: list[dict[str, object]] = []
        self.sync_drains = 0
        self.sync_pulls: list[dict[str, int]] = []
        self.drained_sync_records = []
        self.saved_key_envelopes = []
        self.revoked_devices: list[str] = []
        self.approved_devices: list[dict[str, object]] = []
        self.deleted_cloud = False
        self.session = ProSession(
            account_id="acct_test",
            device_id="device_test",
            access_token="access",
            refresh_token="refresh",
            access_expires_at="2027-01-01T00:00:00+00:00",
            refresh_expires_at="2028-01-01T00:00:00+00:00",
        )

    def get_state(self) -> dict[str, object]:
        return {
            "signedIn": True,
            "entitlements": {"active": True},
            "usage": None,
            "account": None,
            "commerce": {"subscriptions": []},
        }

    def create_meeting(
        self,
        *,
        language: str | None = None,
        audio_duration_seconds: float | None = None,
    ) -> dict[str, object]:
        call = {"language": language, "audio_duration_seconds": audio_duration_seconds}
        self.create_calls.append(call)
        return {"job_id": "job_test", **call}

    def refresh_if_needed(self) -> ProSession:
        return self.session

    def clear_session(self) -> None:
        self.session = None

    def drain_sync_outbox(self, outbox):  # noqa: ANN001
        self.sync_drains += 1
        pending = outbox.pending()
        self.drained_sync_records.extend(pending)
        outbox.replace_pending([])
        return {"pushed": len(pending), "remaining": 0, "results": []}

    def get_sync_changes(self, *, since: int = 0, limit: int = 500):
        self.sync_pulls.append({"since": since, "limit": limit})
        return {"records": [], "next_seq": since, "has_more": False}

    def update_sync_cursor(self, *, last_seq: int):
        return {"last_seq": last_seq}

    def save_key_envelope(self, *, envelope_kind: str, envelope: dict[str, object]) -> dict[str, object]:
        self.saved_key_envelopes.append({"envelope_kind": envelope_kind, "envelope": envelope})
        return {"envelope_kind": envelope_kind, "envelope": envelope}

    def list_key_envelopes(self, *, envelope_kind: str | None = None) -> dict[str, object]:
        envelopes = [
            item for item in self.saved_key_envelopes
            if envelope_kind is None or item["envelope_kind"] == envelope_kind
        ]
        return {"envelopes": envelopes}

    def list_devices(self) -> dict[str, object]:
        return {
            "devices": [
                {
                    "device_id": "device_test",
                    "label": "Test Desktop",
                    "public_key": self.current_device_keys.public_key,
                    "trusted_at": "2026-07-05T12:00:00+00:00",
                    "revoked_at": None,
                },
                {
                    "device_id": "device_other",
                    "label": "Other Desktop",
                    "trusted_at": "2026-07-05T12:00:00+00:00",
                    "revoked_at": None,
                },
                {
                    "device_id": "device_pending",
                    "label": "New laptop",
                    "public_key": "MoQq/Kdp1dGMzaBKnJ6bN1DRe4E9eKUGq9MfSi7vHEA=",
                    "trusted_at": None,
                    "revoked_at": None,
                },
            ]
        }

    def revoke_device(self, device_id: str) -> dict[str, object]:
        self.revoked_devices.append(device_id)
        return {"revoked": True, "device_id": device_id}

    def approve_device(self, device_id: str, *, envelope: dict[str, object] | None = None) -> dict[str, object]:
        self.approved_devices.append({"device_id": device_id, "envelope": envelope})
        return {"approved": True, "device": {"device_id": device_id, "trusted_at": "2026-07-05T12:00:00+00:00"}}

    def approve_current_device_with_recovery(self) -> dict[str, object]:
        self.approved_with_recovery = True
        return {"approved": True, "method": "recovery"}

    def export_cloud_data(self) -> dict[str, object]:
        return {"account": {"account_id": "acct_test"}, "sync_records": []}

    def delete_cloud_data(self) -> dict[str, object]:
        self.deleted_cloud = True
        return {"deleted": {"sync_records": 0}}


class _FakeBrowserProClient(_FakeProClient):
    """Adds the Episode 1/2 browser sign-in surface (start/poll/cancel) on top of
    _FakeProClient's existing email-code/sync/device methods."""

    def __init__(self, *, start_result=None, start_raises=None, poll_result=None) -> None:
        super().__init__()
        self._start_result = start_result or {
            "flow": "loopback",
            "authorize_url": "http://127.0.0.1:9/authorize?state=s",
            "expires_in": 300,
        }
        self._start_raises = start_raises
        self.poll_result = poll_result or {"status": "pending"}
        self.start_calls: list[dict[str, object]] = []
        self.poll_calls: list[dict[str, object]] = []
        self.cancel_calls = 0

    def start_browser_sign_in(self, *, device_label: str = "Desktop", prefer: str = "auto") -> dict[str, object]:
        self.start_calls.append({"device_label": device_label, "prefer": prefer})
        if self._start_raises is not None:
            raise self._start_raises
        return self._start_result

    def poll_browser_sign_in(self, *, device_public_key=None, device_label: str = "Desktop") -> dict[str, object]:
        self.poll_calls.append({"device_public_key": device_public_key, "device_label": device_label})
        return self.poll_result

    def cancel_browser_sign_in(self) -> None:
        self.cancel_calls += 1


def _sync_settings(base: Path) -> SyncSettingsStore:
    saved: dict[str, str] = {}
    return SyncSettingsStore(
        path=base / "sync-state.json",
        device_path=base / "sync-device.json",
        outbox_path=base / "sync-outbox.jsonl",
        save_key=lambda account, encoded: saved.__setitem__(account, encoded),
        read_key=lambda account: saved.get(account),
        clear_key=lambda account: saved.pop(account, None),
    )


class UiPrefsStoreTests(unittest.TestCase):
    def test_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = UiPrefsStore(Path(d) / "p.json")
            self.assertEqual(store.load(), DEFAULT_PREFS)

    def test_update_persists_and_coerces(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            store = UiPrefsStore(path)
            prefs = store.update({"theme": "dark", "overlay": False, "outputFormat": "markdown", "junk": 1})
            self.assertEqual(prefs["theme"], "dark")
            self.assertFalse(prefs["overlay"])
            self.assertEqual(prefs["outputFormat"], "markdown")
            self.assertNotIn("junk", prefs)
            # reload from disk
            self.assertEqual(UiPrefsStore(path).load()["theme"], "dark")

    def test_synced_pref_metadata_is_separate_from_prefs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            meta_path = Path(d) / "p-meta.json"
            store = UiPrefsStore(path, meta_path)
            store.update({"theme": "dark", "trayOnly": False}, updated_at="2026-07-05T12:00:00+00:00")

            self.assertEqual(store.load()["theme"], "dark")
            self.assertNotIn("2026-07-05T12:00:00+00:00", path.read_text())
            self.assertEqual(store.sync_updated_at("theme"), "2026-07-05T12:00:00+00:00")
            self.assertIsNone(store.sync_updated_at("trayOnly"))

    def test_apply_synced_setting_uses_last_writer_wins(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            meta_path = Path(d) / "p-meta.json"
            store = UiPrefsStore(path, meta_path)
            store.update({"theme": "dark"}, updated_at="2026-07-05T12:10:00+00:00")

            self.assertFalse(
                store.apply_synced_setting(
                    "theme",
                    "light",
                    updated_at="2026-07-05T12:09:59+00:00",
                )
            )
            self.assertEqual(store.load()["theme"], "dark")
            self.assertTrue(
                store.apply_synced_setting(
                    "theme",
                    "light",
                    updated_at="2026-07-05T12:11:00+00:00",
                )
            )
            self.assertEqual(store.load()["theme"], "light")

    def test_invalid_theme_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            path.write_text(json.dumps({"theme": "neon", "activation": "wat", "outputFormat": "html"}))
            prefs = UiPrefsStore(path).load()
            self.assertEqual(prefs["theme"], DEFAULT_PREFS["theme"])
            self.assertEqual(prefs["activation"], DEFAULT_PREFS["activation"])
            self.assertEqual(prefs["outputFormat"], DEFAULT_PREFS["outputFormat"])


class EventBrokerTests(unittest.TestCase):
    def test_publish_reaches_subscribers(self) -> None:
        broker = EventBroker()
        q = broker.subscribe()
        broker.publish("recording", active=True, elapsedMs=0)
        event = q.get_nowait()
        self.assertEqual(event["type"], "recording")
        self.assertTrue(event["active"])

    def test_publish_transcript_events(self) -> None:
        broker = EventBroker()
        q = broker.subscribe()
        broker.publish("transcript", phase="partial", text="hello", stale=False)
        event = q.get_nowait()
        self.assertEqual(event["type"], "transcript")
        self.assertEqual(event["phase"], "partial")
        self.assertEqual(event["text"], "hello")

    def test_unsubscribe_stops_delivery(self) -> None:
        broker = EventBroker()
        q = broker.subscribe()
        broker.unsubscribe(q)
        broker.publish("status", message="hi")
        self.assertEqual(broker.subscriber_count, 0)
        self.assertTrue(q.empty())


class UiBackendStateTests(unittest.TestCase):
    def test_default_state_shape(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            # Pin the hardware-aware default so the shape assertion is deterministic.
            with patch(
                "dictate.ui_server.resolve_default_local_backend",
                return_value=("parakeet", "parakeet-tdt-0.6b-v2"),
            ):
                state = _backend(d).get_state()
            self.assertIn("version", state)
            self.assertEqual(state["updateChannel"], "stable")
            self.assertIsNone(state["installedPackageVersion"])
            self.assertEqual(state["model"]["backend"], "parakeet")
            self.assertEqual(state["model"]["model"], "parakeet-tdt-0.6b-v2")
            self.assertEqual(state["model"]["id"], "parakeet/parakeet-tdt-0.6b-v2")
            # local models first (parakeet English default leads), hosted present
            self.assertEqual(state["models"][0]["backend"], "parakeet")
            self.assertTrue(state["models"][0]["local"])
            local_models = [
                model["model"] for model in state["models"] if model["backend"] == "faster-whisper"
            ]
            self.assertEqual(
                local_models,
                ["tiny", "base", "small", "medium", "large-v3", "turbo", "large-v3-turbo"],
            )
            backends = {m["backend"] for m in state["models"]}
            self.assertEqual(
                backends,
                {
                    "parakeet",
                    "parakeet-pyannote",
                    "parakeet-diarizen",
                    "parakeet-sortformer",
                    "faster-whisper",
                    "whisperx",
                    "openai",
                    "xai",
                    "gemini",
                },
            )
            # default shortcut + activation
            self.assertEqual(state["shortcut"]["combo"], "ctrl_r")
            self.assertEqual(state["shortcut"]["display"], ["Ctrl (R)"])
            self.assertEqual(state["shortcut"]["activation"], "hold")
            self.assertEqual(state["prefs"], DEFAULT_PREFS)
            self.assertEqual(state["providers"]["openai"]["status"], "None")
            self.assertEqual(state["providerHealth"]["mode"], "private")
            self.assertEqual(state["providerHealth"]["status"], "ok")
            self.assertTrue(state["providerHealth"]["healthy"])

    def test_parakeet_provider_health_is_private_without_api_key(self) -> None:
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            config_mod.set_stt_selection("parakeet", "parakeet-tdt-0.6b-v2", path=backend.config_path)

            state = backend.get_state()

        self.assertEqual(state["providerHealth"]["mode"], "private")
        self.assertEqual(state["providerHealth"]["status"], "ok")
        self.assertTrue(state["providerHealth"]["healthy"])

    def test_state_reflects_configured_model(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.patch_config({"model": "gemini/gemini-3-flash-preview"})
            state = backend.get_state()
            self.assertEqual(state["model"]["backend"], "gemini")
            self.assertEqual(state["model"]["model"], "gemini-3-flash-preview")

    def test_default_local_model_matches_backend_resolver(self) -> None:
        # Fresh config (no saved stt_model): the displayed local default must match
        # what the daemon would actually run, per the backend resolver.
        with tempfile.TemporaryDirectory() as d:
            with patch(
                "dictate.ui_server.resolve_default_local_backend",
                return_value=("parakeet", "parakeet-tdt-0.6b-v2"),
            ):
                capable = _backend(d).get_state()
            self.assertEqual(capable["model"]["backend"], "parakeet")
            self.assertEqual(capable["model"]["model"], "parakeet-tdt-0.6b-v2")
            self.assertEqual(capable["model"]["id"], "parakeet/parakeet-tdt-0.6b-v2")

        with tempfile.TemporaryDirectory() as d:
            with patch("dictate.ui_server.resolve_default_local_model", return_value="small"), \
                 patch("dictate.ui_server.resolve_default_local_backend", return_value=("faster-whisper", "small")):
                weak = _backend(d).get_state()
            self.assertEqual(weak["model"]["model"], "small")
            self.assertEqual(weak["model"]["id"], "faster-whisper/small")

    def test_stale_regular_local_model_migrates_to_parakeet_on_state_load(self) -> None:
        # Legacy regular dictation backends are UI-stale state and should be
        # rewritten to the shipped private default when the UI hydrates.
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            config_mod.set_stt_selection("faster-whisper", "base", path=backend.config_path)
            with patch("dictate.ui_server.resolve_default_local_model", return_value="turbo"):
                state = backend.get_state()
            cfg = config_mod.load_config(backend.config_path)
            self.assertEqual(state["model"]["backend"], "parakeet")
            self.assertEqual(state["model"]["model"], "parakeet-tdt-0.6b-v2")
            self.assertEqual(cfg.stt_backend, "parakeet")
            self.assertEqual(cfg.stt_model, "parakeet-tdt-0.6b-v2")

    def test_state_load_migration_leaves_meeting_selection_untouched(self) -> None:
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            config_mod.set_stt_selection("whisperx", "large-v3", path=backend.config_path)
            config_mod.set_meeting_stt_selection("whisperx", "large-v3", path=backend.config_path)

            state = backend.get_state()
            cfg = config_mod.load_config(backend.config_path)

            self.assertEqual(state["model"]["backend"], "parakeet")
            self.assertEqual(state["meetingModel"]["backend"], "whisperx")
            self.assertEqual(state["meetingModel"]["model"], "large-v3")
            self.assertEqual(cfg.stt_backend, "parakeet")
            self.assertEqual(cfg.stt_model, "parakeet-tdt-0.6b-v2")
            self.assertEqual(cfg.meeting_stt_backend, "whisperx")
            self.assertEqual(cfg.meeting_stt_model, "large-v3")

    def test_faster_whisper_selection_is_migrated_on_state_load(self) -> None:
        # Legacy regular dictation selections are normalized through the UI state
        # path before they can persist, so the config is corrected to Parakeet.
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            # Client sends the old hardcoded "faster-whisper/turbo" intent.
            backend.patch_config({"model": {"backend": "faster-whisper", "model": "turbo"}})
            cfg = config_mod.load_config(backend.config_path)
            self.assertEqual(cfg.stt_backend, "parakeet")
            self.assertEqual(cfg.stt_model, "parakeet-tdt-0.6b-v2")

    def test_models_default_flag_tracks_resolved_local_tier(self) -> None:
        # P3-1: the models list "default" flag for faster-whisper matches the
        # effective (resolved) tier, not the aspirational registry default.
        with tempfile.TemporaryDirectory() as d:
            with patch("dictate.ui_server.resolve_default_local_model", return_value="small"):
                state = _backend(d).get_state()
            fw = [m for m in state["models"] if m["backend"] == "faster-whisper"]
            defaults = [m["model"] for m in fw if m["default"]]
            self.assertEqual(defaults, ["small"])

    def test_run_doctor_reports_resolved_local_model(self) -> None:
        # P3-2: doctor's "Model loads" check reports the resolved tier on a fresh
        # weak-box config, matching what the daemon runs.
        with tempfile.TemporaryDirectory() as d:
            with patch("dictate.ui_server.resolve_default_local_model", return_value="small"):
                report = _backend(d).run_doctor()
            model_check = next(c for c in report["checks"] if c["label"] == "Model loads")
            self.assertIn("small", model_check["sub"])
            self.assertNotIn("turbo", model_check["sub"])

    def test_models_default_flag_ignores_hosted_saved_model(self) -> None:
        # P3-A: with a hosted backend saved (the normal state after a cloud
        # selection), the faster-whisper "default" flag must still track the
        # resolved local tier — not borrow the hosted model name.
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            config_mod.set_stt_selection("xai", "grok-speech-to-text", path=backend.config_path)
            with patch("dictate.ui_server.resolve_default_local_model", return_value="small"):
                state = backend.get_state()
            fw = [m for m in state["models"] if m["backend"] == "faster-whisper"]
            defaults = [m["model"] for m in fw if m["default"]]
            self.assertEqual(defaults, ["small"])

    def test_set_model_via_dict(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.patch_config({"model": {"backend": "openai", "model": "gpt-4o-mini-transcribe"}})
            self.assertEqual(backend.get_state()["model"]["backend"], "openai")

    def test_command_configured_provider_is_reported_ready(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(
                d,
                api_key_status=lambda backend, **kw: ApiKeyStatus(backend=backend, status="Ready"),
            )
            backend.patch_config({"model": {"backend": "xai", "model": "grok-speech-to-text"}})
            from dictate import config as config_mod

            config_mod.set_api_key_command(
                "xai",
                "/usr/bin/printf xai-validtokenvalidtoken",
                path=backend.config_path,
            )
            with patch(
                "dictate.ui_server.api_keys_mod._api_key_from_command",
                return_value="xai-validtokenvalidtoken",
            ):
                state = backend.get_state()
            self.assertTrue(state["providers"]["xai"]["configured"])
            xai_model = next(model for model in state["models"] if model["backend"] == "xai")
            self.assertTrue(xai_model["configured"])

    def test_unknown_backend_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                _backend(d).patch_config({"model": "nope/x"})

    def test_create_pro_meeting_passes_audio_duration_to_client(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeProClient()
            backend = _backend(d, pro_client=pro_client)
            result = backend.create_pro_meeting(language="en", audio_duration_seconds=12.5)
        self.assertEqual(result["job_id"], "job_test")
        self.assertEqual(
            pro_client.create_calls,
            [{"language": "en", "audio_duration_seconds": 12.5}],
        )

    def test_state_includes_disabled_sync_status(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, sync_settings=_sync_settings(Path(d)))
            state = backend.get_state()

        self.assertFalse(state["sync"]["enabled"])
        self.assertIsNone(state["sync"]["accountId"])
        self.assertFalse(state["sync"]["keyAvailable"])

    def test_enable_sync_requires_pro_sign_in(self) -> None:
        class _UnsignedClient(_FakeProClient):
            def refresh_if_needed(self):  # noqa: ANN201
                return None

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(
                d,
                pro_client=_UnsignedClient(),
                sync_settings=_sync_settings(Path(d)),
            )

            with self.assertRaisesRegex(ApiError, "Sign in to Dictate Pro"):
                backend.enable_sync()

    def test_enable_sync_requires_active_pro_entitlement(self) -> None:
        class _InactiveProClient(_FakeProClient):
            def get_state(self) -> dict[str, object]:
                state = super().get_state()
                state["entitlements"] = {"active": False, "status": "expired"}
                return state

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(
                d,
                pro_client=_InactiveProClient(),
                sync_settings=_sync_settings(Path(d)),
            )

            with self.assertRaises(ApiError) as ctx:
                backend.enable_sync()

            self.assertEqual(ctx.exception.status, 403)

    def test_enable_sync_attaches_outbox_and_runs_initial_sync(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeProClient()
            backend = _backend(
                d,
                pro_client=pro_client,
                sync_settings=_sync_settings(Path(d)),
            )

            result = backend.enable_sync()
            backend.history_store.append("private local text")

            self.assertTrue(result["sync"]["enabled"])
            self.assertEqual(result["sync"]["accountId"], "acct_test")
            self.assertTrue(result["sync"]["keyAvailable"])
            self.assertEqual(pro_client.sync_drains, 1)
            self.assertEqual(len(backend.history_store._sync_outbox.pending()), 1)

    def test_enable_sync_uploads_current_device_key_envelope(self) -> None:
        from dictate.sync import unwrap_account_key_for_device

        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeProClient()
            sync_settings = _sync_settings(Path(d))
            backend = _backend(
                d,
                pro_client=pro_client,
                sync_settings=sync_settings,
            )

            backend.enable_sync()

            device_envelopes = [
                item for item in pro_client.saved_key_envelopes
                if item["envelope_kind"] == "device"
            ]
            self.assertEqual(len(device_envelopes), 1)
            restored = unwrap_account_key_for_device(
                account_id="acct_test",
                private_key=pro_client.current_device_keys.private_key,
                envelope=device_envelopes[0]["envelope"],
            )
            self.assertEqual(restored, sync_settings.account_key())

    def test_enable_sync_requires_current_device_public_key(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeProClient()

            def list_devices() -> dict[str, object]:
                return {
                    "devices": [
                        {
                            "device_id": "device_test",
                            "label": "Test Desktop",
                            "trusted_at": "2026-07-05T12:00:00+00:00",
                            "revoked_at": None,
                        }
                    ]
                }

            pro_client.list_devices = list_devices  # type: ignore[method-assign]
            backend = _backend(
                d,
                pro_client=pro_client,
                sync_settings=_sync_settings(Path(d)),
            )

            with self.assertRaisesRegex(ApiError, "sync public key"):
                backend.enable_sync()

    def test_enable_sync_snapshots_portable_prefs_and_lexicon(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            pro_client = _FakeProClient()
            sync_settings = _sync_settings(base)
            backend = _backend(
                d,
                pro_client=pro_client,
                sync_settings=sync_settings,
            )
            backend.patch_config({"prefs": {"theme": "dark", "sound": True, "activation": "toggle", "outputFormat": "markdown"}})
            config_mod.add_hotwords(["OpenClaw"], path=backend.config_path)
            config_mod.add_lexicon_replacements({"openc law": "OpenClaw"}, path=backend.config_path)

            backend.enable_sync()

            key = sync_settings.account_key()
            self.assertIsNotNone(key)
            payloads = [decrypt_record("acct_test", key, record) for record in pro_client.drained_sync_records]
            self.assertTrue(any(payload.get("key") == "theme" and payload.get("value") == "dark" for payload in payloads))
            self.assertTrue(any(payload.get("key") == "activation" and payload.get("value") == "toggle" for payload in payloads))
            self.assertTrue(any(payload.get("key") == "outputFormat" and payload.get("value") == "markdown" for payload in payloads))
            self.assertTrue(any(payload.get("kind") == "hotword" and payload.get("term") == "OpenClaw" for payload in payloads))
            self.assertTrue(
                any(
                    payload.get("kind") == "replacement"
                    and payload.get("wrong") == "openc law"
                    and payload.get("right") == "OpenClaw"
                    for payload in payloads
                )
            )

    def test_enable_sync_snapshots_existing_local_history_notes_and_segments(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            pro_client = _FakeProClient()
            sync_settings = _sync_settings(base)
            backend = _backend(
                d,
                pro_client=pro_client,
                sync_settings=sync_settings,
            )
            history_entry = backend.history_store.append("private local history before sync")
            note_id = backend.note_store.create_note(
                provider="parakeet",
                model="parakeet-tdt-0.6b-v2",
                mode="meeting",
                speaker_labels=True,
            )
            backend.note_store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=2.0,
                    provider="parakeet",
                    model="parakeet-tdt-0.6b-v2",
                    text="private note segment before sync",
                    speaker_id="speaker_1",
                    speaker_label="Speaker 1",
                ),
            )
            backend.note_store.mark_ready(note_id, duration_s=2.0)

            # This test exercises the full snapshot (history + note + segment), so opt into
            # "everything" — enable_sync otherwise defaults new sync to meetings-only.
            config_mod.set_sync_scope("everything", backend.config_path)
            backend.enable_sync()

            key = sync_settings.account_key()
            self.assertIsNotNone(key)
            raw_outbox = (base / "sync-outbox.jsonl").read_text() if (base / "sync-outbox.jsonl").exists() else ""
            self.assertNotIn("private local history before sync", raw_outbox)
            self.assertNotIn("private note segment before sync", raw_outbox)
            records = pro_client.drained_sync_records
            self.assertTrue(any(record.collection == "history" and record.record_id == history_entry.id for record in records))
            self.assertTrue(any(record.collection == "note" and record.record_id == note_id for record in records))
            self.assertTrue(any(record.collection == "segment" and record.record_id == f"{note_id}:0" for record in records))
            payloads = [decrypt_record("acct_test", key, record) for record in records]
            self.assertTrue(any(payload.get("text") == "private local history before sync" for payload in payloads))
            self.assertTrue(any(payload.get("text") == "private note segment before sync" for payload in payloads))
            self.assertTrue(any(payload.get("mode") == "meeting" and payload.get("speaker_labels") is True for payload in payloads))

    def test_enable_sync_can_restore_existing_key_from_recovery_key(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            sync_settings = _sync_settings(base)
            pro_client = _FakeProClient()
            backend = _backend(d, sync_settings=sync_settings, pro_client=pro_client)
            created = backend.enable_sync()
            original_key = sync_settings.account_key()
            assert original_key is not None
            recovery_key = created["recoveryKey"]
            sync_settings.disable(clear_key=True)

            restored = backend.enable_sync(recovery_key=recovery_key)

            self.assertTrue(restored["sync"]["enabled"])
            self.assertNotIn("recoveryKey", restored)
            self.assertEqual(sync_settings.account_key(), original_key)
            self.assertTrue(pro_client.approved_with_recovery)

    def test_enable_sync_rejects_wrong_recovery_key(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            sync_settings = _sync_settings(base)
            pro_client = _FakeProClient()
            backend = _backend(d, sync_settings=sync_settings, pro_client=pro_client)
            backend.enable_sync()
            sync_settings.disable(clear_key=True)

            with self.assertRaisesRegex(ApiError, "Recovery key could not unlock"):
                backend.enable_sync(recovery_key="dictate-rk-wrong")

    def test_approve_pro_device_wraps_local_sync_key(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sync_settings = _sync_settings(Path(d))
            pro_client = _FakeProClient()
            backend = _backend(d, sync_settings=sync_settings, pro_client=pro_client)
            backend.enable_sync()

            result = backend.approve_pro_device("device_pending")

            self.assertTrue(result["approved"])
            self.assertEqual(pro_client.approved_devices[0]["device_id"], "device_pending")
            envelope = pro_client.approved_devices[0]["envelope"]
            self.assertIsInstance(envelope, dict)
            assert isinstance(envelope, dict)
            self.assertEqual(envelope["algorithm"], "x25519-aes-256-gcm")

    def test_enable_sync_can_restore_existing_key_from_device_approval(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pending_keys = generate_device_key_pair()
            sync_settings = _sync_settings(Path(d))
            pro_client = _FakeProClient()
            backend = _backend(d, sync_settings=sync_settings, pro_client=pro_client)
            backend.enable_sync()
            original_key = sync_settings.account_key()
            assert original_key is not None

            def list_devices() -> dict[str, object]:
                return {
                    "devices": [
                        {
                            "device_id": "device_test",
                            "label": "Test Desktop",
                            "trusted_at": "2026-07-05T12:00:00+00:00",
                            "revoked_at": None,
                        },
                        {
                            "device_id": "device_pending",
                            "label": "New laptop",
                            "public_key": pending_keys.public_key,
                            "trusted_at": None,
                            "revoked_at": None,
                        },
                    ]
                }

            pro_client.list_devices = list_devices  # type: ignore[method-assign]
            backend.approve_pro_device("device_pending")
            envelope = pro_client.approved_devices[0]["envelope"]
            assert isinstance(envelope, dict)
            pro_client.saved_key_envelopes.append({
                "envelope_kind": "device",
                "device_id": "device_pending",
                "envelope": envelope,
            })
            pro_client.session = ProSession(
                account_id="acct_test",
                device_id="device_pending",
                access_token="access",
                refresh_token="refresh",
                access_expires_at="2027-01-01T00:00:00+00:00",
                refresh_expires_at="2028-01-01T00:00:00+00:00",
            )
            sync_settings.disable(clear_key=True)

            with patch("dictate.ui_server.api_keys_mod.read_sync_device_private_key", return_value=pending_keys.private_key):
                restored = backend.enable_sync()

            self.assertTrue(restored["sync"]["enabled"])
            self.assertNotIn("recoveryKey", restored)
            self.assertEqual(sync_settings.account_key(), original_key)

    def test_run_sync_drains_outbox_and_returns_history(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeProClient()
            backend = _backend(
                d,
                pro_client=pro_client,
                sync_settings=_sync_settings(Path(d)),
            )
            backend.enable_sync()
            backend.history_store.append("private local text")

            result = backend.run_sync()

            self.assertEqual(result["result"]["pushed"], 1)
            self.assertEqual(result["result"]["remaining"], 0)
            self.assertEqual(result["history"][0]["text"], "private local text")
            self.assertEqual(backend.history_store._sync_outbox.pending(), [])

    def test_sign_out_disables_sync_without_deleting_local_history(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeProClient()
            backend = _backend(
                d,
                pro_client=pro_client,
                sync_settings=_sync_settings(Path(d)),
            )
            backend.enable_sync()
            backend.history_store.append("keep local")
            note_id = backend.note_store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
            backend.note_store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=1.0,
                    provider="parakeet",
                    model="parakeet-tdt-0.6b-v2",
                    text="keep local note",
                ),
            )
            backend.note_store.mark_ready(note_id, duration_s=1.0)

            backend.sign_out_pro()

            self.assertFalse(backend.get_state()["sync"]["enabled"])
            texts = [item["text"] for item in backend.get_history()]
            self.assertIn("keep local", texts)
            self.assertIn("keep local note", texts)

    def test_export_local_data_includes_history_and_notes_without_cloud_or_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            history_entry = backend.history_store.append("local export history")
            note_id = backend.note_store.create_note(
                provider="parakeet",
                model="parakeet-tdt-0.6b-v2",
                mode="meeting",
                speaker_labels=True,
            )
            backend.note_store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=1.0,
                    t_end=2.5,
                    provider="parakeet",
                    model="parakeet-tdt-0.6b-v2",
                    text="local export meeting segment",
                    speaker_id="speaker_1",
                    speaker_label="Speaker 1",
                ),
            )
            backend.note_store.mark_ready(note_id, duration_s=2.5)

            exported = backend.export_local_data()

            self.assertEqual(exported["schema"], "dictate.local-export.v1")
            self.assertEqual(exported["history"][0]["id"], history_entry.id)
            self.assertEqual(exported["history"][0]["text"], "local export history")
            self.assertEqual(exported["notes"][0]["id"], note_id)
            self.assertEqual(exported["notes"][0]["text"], "Speaker 1: local export meeting segment")
            self.assertEqual(exported["notes"][0]["segments"][0]["speakerLabel"], "Speaker 1")
            raw = json.dumps(exported)
            self.assertNotIn("access", raw)
            self.assertNotIn("refresh", raw)
            self.assertNotIn("apiKey", raw)
            self.assertNotIn("sync_records", raw)


class UiBackendBrowserSignInTests(unittest.TestCase):
    """Episode 3: start_pro_browser_sign_in / poll_pro_browser_sign_in / cancel_pro_browser_sign_in."""

    def test_flag_off_returns_email_fallback_without_touching_pro_client(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            # Exercise the real default while keeping the test independent from
            # the developer shell/CI environment.
            with patch.dict("os.environ", {"DICTATE_PRO_BROWSER_SIGNIN": ""}):
                backend = _backend(d, pro_client=_FakeBrowserProClient())
                self.assertEqual(backend.start_pro_browser_sign_in(), {"flow": "email"})
                self.assertEqual(backend.pro_client.start_calls, [])

    def test_start_happy_path_loopback_opens_browser(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            opened = []
            pro_client = _FakeBrowserProClient()
            backend = _backend(
                d,
                pro_client=pro_client,
                browser_signin_enabled=lambda: True,
                open_browser=lambda url: opened.append(url),
            )
            result = backend.start_pro_browser_sign_in(flow="auto", device_label="Test Desktop")
            self.assertEqual(result["flow"], "loopback")
            self.assertEqual(result["authorize_url"], "http://127.0.0.1:9/authorize?state=s")
            self.assertEqual(pro_client.start_calls, [{"device_label": "Test Desktop", "prefer": "auto"}])
            self.assertEqual(opened, ["http://127.0.0.1:9/authorize?state=s"])
            # A device keypair was generated up front, mirroring complete_pro_sign_in.
            self.assertIsNotNone(backend._pending_browser_device_key)

    def test_start_device_code_flow_does_not_open_a_browser(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            opened = []
            pro_client = _FakeBrowserProClient(
                start_result={
                    "flow": "device_code",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "http://127.0.0.1:9/device",
                    "verification_uri_complete": "http://127.0.0.1:9/device?user_code=ABCD-EFGH",
                    "expires_in": 900,
                    "interval": 5,
                }
            )
            backend = _backend(
                d,
                pro_client=pro_client,
                browser_signin_enabled=lambda: True,
                open_browser=lambda url: opened.append(url),
            )
            result = backend.start_pro_browser_sign_in(flow="device_code")
            self.assertEqual(result["flow"], "device_code")
            self.assertEqual(result["user_code"], "ABCD-EFGH")
            self.assertEqual(opened, [])

    def test_start_capability_501_returns_email_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeBrowserProClient(start_raises=ProClientError(501, "browser sign-in unavailable"))
            backend = _backend(d, pro_client=pro_client, browser_signin_enabled=lambda: True)
            self.assertEqual(backend.start_pro_browser_sign_in(), {"flow": "email"})

    def test_start_propagates_non_capability_errors(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeBrowserProClient(start_raises=ProClientError(503, "unreachable"))
            backend = _backend(d, pro_client=pro_client, browser_signin_enabled=lambda: True)
            with self.assertRaises(ApiError) as ctx:
                backend.start_pro_browser_sign_in()
            self.assertEqual(ctx.exception.status, 503)

    def test_poll_pending_leaves_device_key_and_session_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeBrowserProClient(poll_result={"status": "pending"})
            backend = _backend(d, pro_client=pro_client, browser_signin_enabled=lambda: True)
            backend.start_pro_browser_sign_in()
            result = backend.poll_pro_browser_sign_in()
            self.assertEqual(result, {"status": "pending"})
            self.assertIsNotNone(backend._pending_browser_device_key)

    def test_poll_complete_persists_device_key_and_returns_dictate_pro_state(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeBrowserProClient(
                poll_result={"status": "complete", "account_id": "acct_x", "device_id": "device_x"}
            )
            backend = _backend(d, pro_client=pro_client, browser_signin_enabled=lambda: True)
            backend.start_pro_browser_sign_in()
            pending_key = backend._pending_browser_device_key
            assert pending_key is not None

            with patch("dictate.ui_server.api_keys_mod.save_sync_device_private_key") as save_mock:
                result = backend.poll_pro_browser_sign_in()

            save_mock.assert_called_once_with("device_x", pending_key.private_key)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["account_id"], "acct_x")
            self.assertIn("dictatePro", result)
            self.assertTrue(result["dictatePro"]["signedIn"])
            # The device key is single-shot: cleared once persisted.
            self.assertIsNone(backend._pending_browser_device_key)

    def test_poll_error_clears_pending_device_key(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeBrowserProClient(poll_result={"status": "error", "reason": "expired_token"})
            backend = _backend(d, pro_client=pro_client, browser_signin_enabled=lambda: True)
            backend.start_pro_browser_sign_in()
            result = backend.poll_pro_browser_sign_in()
            self.assertEqual(result, {"status": "error", "reason": "expired_token"})
            self.assertIsNone(backend._pending_browser_device_key)

    def test_cancel_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            pro_client = _FakeBrowserProClient()
            backend = _backend(d, pro_client=pro_client, browser_signin_enabled=lambda: True)
            backend.start_pro_browser_sign_in()
            result = backend.cancel_pro_browser_sign_in()
            self.assertEqual(result, {"status": "cancelled"})
            self.assertEqual(pro_client.cancel_calls, 1)
            self.assertIsNone(backend._pending_browser_device_key)

    def test_cancel_when_disabled_is_a_harmless_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, pro_client=_FakeBrowserProClient())
            self.assertEqual(backend.cancel_pro_browser_sign_in(), {"status": "cancelled"})


class UiBackendShortcutPrefsTests(unittest.TestCase):
    def test_set_shortcut_and_activation(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.patch_config({"shortcut": {"combo": "ctrl+shift+r", "activation": "toggle"}})
            state = backend.get_state()
            self.assertEqual(state["shortcut"]["display"], ["Ctrl", "Shift", "R"])
            self.assertEqual(state["shortcut"]["activation"], "toggle")

    def test_set_prefs_theme(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.patch_config({"prefs": {"theme": "dark", "sound": True}})
            prefs = backend.get_state()["prefs"]
            self.assertEqual(prefs["theme"], "dark")
            self.assertTrue(prefs["sound"])

    def test_synced_prefs_enqueue_when_sync_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sync_settings = _sync_settings(Path(d))
            backend = _backend(d, sync_settings=sync_settings, pro_client=_FakeProClient())
            backend.enable_sync()

            backend.patch_config({"prefs": {"theme": "dark", "activation": "toggle", "outputFormat": "markdown", "trayOnly": False}})

            outbox = sync_settings.outbox()
            self.assertIsNotNone(outbox)
            pending = outbox.pending()
            payloads = [decrypt_record("acct_test", sync_settings.account_key(), record) for record in pending]
            values_by_key = {payload["key"]: payload["value"] for payload in payloads}
            self.assertEqual([record.collection for record in pending], ["settings", "settings", "settings"])
            self.assertEqual(values_by_key["theme"], "dark")
            self.assertEqual(values_by_key["activation"], "toggle")
            self.assertEqual(values_by_key["outputFormat"], "markdown")
            self.assertNotIn("trayOnly", values_by_key)

    def test_shortcut_activation_enqueues_when_sync_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sync_settings = _sync_settings(Path(d))
            backend = _backend(d, sync_settings=sync_settings, pro_client=_FakeProClient())
            backend.enable_sync()

            backend.patch_config({"shortcut": {"activation": "toggle"}})

            outbox = sync_settings.outbox()
            self.assertIsNotNone(outbox)
            pending = outbox.pending()
            self.assertEqual([record.collection for record in pending], ["settings"])
            payload = decrypt_record("acct_test", sync_settings.account_key(), pending[0])
            self.assertEqual(payload["key"], "activation")
            self.assertEqual(payload["value"], "toggle")

    def test_invalid_theme_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                _backend(d).patch_config({"prefs": {"theme": "neon"}})

    def test_startup_hook_invoked(self) -> None:
        calls: list[bool] = []
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, set_startup_enabled=lambda enabled: calls.append(enabled))
            backend.patch_config({"startup": False})
            self.assertEqual(calls, [False])


class UiBackendHotwordsHistoryTests(unittest.TestCase):
    def test_add_and_remove_hotwords(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            res = backend.add_hotwords(["AcmeWidget", "OpenClaw, Stalwart"])
            self.assertIn("AcmeWidget", res["hotwords"])
            self.assertIn("Stalwart", res["hotwords"])  # comma-split parsed
            res = backend.remove_hotword("AcmeWidget")
            self.assertNotIn("AcmeWidget", res["hotwords"])

    def test_hotwords_enqueue_lexicon_records_when_sync_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            sync_settings = _sync_settings(Path(d))
            backend = _backend(d, sync_settings=sync_settings, pro_client=_FakeProClient())
            backend.enable_sync()

            backend.add_hotwords(["OpenClaw"])
            backend.remove_hotword("OpenClaw")

            outbox = sync_settings.outbox()
            self.assertIsNotNone(outbox)
            pending = outbox.pending()
            self.assertEqual([record.collection for record in pending], ["lexicon", "lexicon"])
            self.assertFalse(pending[0].deleted)
            self.assertTrue(pending[1].deleted)
            payload = decrypt_record("acct_test", sync_settings.account_key(), pending[0])
            self.assertEqual(payload["kind"], "hotword")
            self.assertEqual(payload["term"], "OpenClaw")

    def test_history_label_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = HistoryStore(Path(d) / "h.json")
            store.append("hello world")
            fixed_now = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
            backend = _backend(d, history_store=store, now=lambda: fixed_now)
            history = backend.get_history()
            self.assertEqual(len(history), 1)
            self.assertTrue(history[0]["time"].endswith("just now") or "ago" in history[0]["time"])
            backend.clear_history()
            self.assertEqual(backend.get_history(), [])

    def test_archive_history_item_hides_note_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            history_store = HistoryStore(Path(d) / "history.json")
            note_store = NoteStore(Path(d) / "notes")
            note_id = note_store.create_note(provider="faster-whisper", model="turbo")
            note_store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=1.0,
                    provider="faster-whisper",
                    model="turbo",
                    text="saved note",
                ),
            )
            note_store.mark_ready(note_id, duration_s=1.0)
            history_store.append("quick dictation")
            backend = _backend(d, history_store=history_store, note_store=note_store)
            self.assertEqual(len(backend.get_history()), 2)

            result = backend.archive_history_item(note_id)
            self.assertEqual(len(result["history"]), 1)
            self.assertEqual(result["history"][0]["text"], "quick dictation")
            self.assertTrue(note_store.load_note(note_id).archived)

            history_id = history_store.load(include_archived=True)[0].id
            result = backend.archive_history_item(history_id)
            self.assertEqual(result["history"], [])
            self.assertTrue(history_store.load(include_archived=True)[0].archived)

    def test_note_controls_call_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            daemon = _FakeNoteDaemon()
            backend = _backend(d, daemon=daemon)
            self.assertFalse(backend.get_state()["notes"]["recording"])
            started = backend.start_note_recording()
            self.assertTrue(started["recording"])
            self.assertFalse(started["paused"])
            self.assertEqual(started["mode"], "note")
            paused = backend.pause_note_recording()
            self.assertTrue(paused["recording"])
            self.assertTrue(paused["paused"])
            resumed = backend.resume_note_recording()
            self.assertTrue(resumed["recording"])
            self.assertFalse(resumed["paused"])
            self.assertFalse(backend.stop_note_recording()["recording"])
            self.assertTrue(backend.toggle_note_recording()["recording"])
            discarded = backend.discard_note_recording()
            self.assertFalse(discarded["recording"])
            self.assertFalse(discarded["paused"])
            self.assertEqual(
                daemon.calls,
                ["start", "pause", "resume", "stop", "toggle", "discard"],
            )

    def test_meeting_discard_calls_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            daemon = _FakeNoteDaemon()
            backend = _backend(d, daemon=daemon)
            config_mod.set_stt_selection(
                "parakeet-pyannote",
                "parakeet-tdt-0.6b-v2",
                path=backend.config_path,
            )
            with patch("dictate.ui_server.check_backend_readiness") as check_backend_readiness:
                check_backend_readiness.return_value.errors = []
                check_backend_readiness.return_value.warnings = []
                backend.start_meeting_recording()
            daemon.note_recording_paused = True
            discarded = backend.discard_meeting_recording()
            self.assertFalse(discarded["recording"])
            self.assertFalse(discarded["paused"])
            self.assertEqual(daemon.calls, ["set-meeting", "start-meeting", "discard-meeting"])

    def test_meeting_controls_call_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            daemon = _FakeNoteDaemon()
            backend = _backend(d, daemon=daemon)
            config_mod.set_stt_selection(
                "parakeet-pyannote",
                "parakeet-tdt-0.6b-v2",
                path=backend.config_path,
            )
            with patch("dictate.ui_server.check_backend_readiness") as check_backend_readiness:
                check_backend_readiness.return_value.errors = []
                check_backend_readiness.return_value.warnings = []
                started = backend.start_meeting_recording()
            self.assertTrue(started["recording"])
            self.assertEqual(started["mode"], "meeting")
            stopped = backend.stop_meeting_recording()
            self.assertFalse(stopped["recording"])
            self.assertEqual(daemon.calls, ["set-meeting", "start-meeting", "stop-meeting"])
            self.assertEqual(daemon.meeting_backend_model, ("parakeet-pyannote", "parakeet-tdt-0.6b-v2"))

    def test_meeting_start_uses_default_meeting_backend_when_dictation_backend_is_plain_asr(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            daemon = _FakeNoteDaemon()
            backend = _backend(d, daemon=daemon)
            config_mod.set_stt_selection("parakeet", "parakeet-tdt-0.6b-v2", path=backend.config_path)

            with patch("dictate.ui_server.check_backend_readiness") as check_backend_readiness:
                check_backend_readiness.return_value.errors = []
                check_backend_readiness.return_value.warnings = []
                payload = backend.start_meeting_recording()

            self.assertTrue(payload["recording"])
            check_backend_readiness.assert_called_once_with(
                backend="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                device="auto",
            )
            self.assertEqual(daemon.calls, ["set-meeting", "start-meeting"])

    def test_meeting_start_blocks_when_pyannote_model_access_missing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            daemon = _FakeNoteDaemon()
            backend = _backend(d, daemon=daemon)
            config_mod.set_stt_selection(
                "parakeet-pyannote",
                "parakeet-tdt-0.6b-v2",
                path=backend.config_path,
            )
            with patch("dictate.ui_server.check_backend_readiness") as check_backend_readiness:
                check_backend_readiness.return_value.errors = []
                check_backend_readiness.return_value.warnings = [
                    "pyannote/speaker-diarization-community-1 is gated."
                ]
                with self.assertRaisesRegex(ApiError, "Meeting model is not ready"):
                    backend.start_meeting_recording()

            self.assertEqual(daemon.calls, [])

    def test_meeting_start_allows_non_blocking_backend_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            daemon = _FakeNoteDaemon()
            backend = _backend(d, daemon=daemon)
            config_mod.set_stt_selection(
                "parakeet-pyannote",
                "parakeet-tdt-0.6b-v2",
                path=backend.config_path,
            )
            with patch("dictate.ui_server.check_backend_readiness") as check_backend_readiness:
                check_backend_readiness.return_value.errors = []
                check_backend_readiness.return_value.warnings = [
                    "pyannote runs through PyTorch. On AMD, this requires a ROCm-enabled PyTorch build."
                ]
                payload = backend.start_meeting_recording()

            self.assertTrue(payload["recording"])
            self.assertEqual(daemon.calls, ["set-meeting", "start-meeting"])

    def test_note_payload_includes_speaker_segments(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = NoteStore(Path(d) / "notes")
            note_id = store.create_note(
                provider="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                speaker_labels=True,
                mode="meeting",
            )
            store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=1.25,
                    provider="parakeet-pyannote",
                    model="parakeet-tdt-0.6b-v2",
                    text="hello",
                    speaker_id="SPEAKER_A",
                    speaker_label="Speaker 1",
                ),
            )
            store.mark_ready(note_id, duration_s=1.25)

            payload = UiBackend.note_payload(store, note_id)

            assert payload is not None
            self.assertEqual(payload["mode"], "meeting")
            self.assertTrue(payload["speakerLabels"])
            self.assertEqual(payload["text"], "Speaker 1: hello")
            self.assertEqual(payload["segments"][0]["speakerLabel"], "Speaker 1")
            self.assertEqual(payload["segments"][0]["tStart"], 0.0)
            self.assertEqual(payload["segments"][0]["tEnd"], 1.25)

    def test_get_history_rehydrates_persisted_note_segments(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            note_store = NoteStore(Path(d) / "notes")
            history_store = HistoryStore(Path(d) / "history.json")
            note_id = note_store.create_note(
                provider="parakeet-pyannote",
                model="parakeet-tdt-0.6b-v2",
                speaker_labels=True,
                mode="meeting",
            )
            note_store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=2.0,
                    provider="parakeet-pyannote",
                    model="parakeet-tdt-0.6b-v2",
                    text="hello",
                    speaker_label="Speaker 1",
                ),
            )
            note_store.mark_ready(note_id, duration_s=2.0)
            history_store.append("Speaker 1: hello")
            backend = _backend(d, history_store=history_store, note_store=note_store)

            history = backend.get_history()

            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["id"], note_id)
            self.assertEqual(history[0]["mode"], "meeting")
            self.assertEqual(history[0]["segments"][0]["speakerLabel"], "Speaker 1")
            self.assertEqual(history[0]["segments"][0]["tStart"], 0.0)

    def test_note_pause_and_resume_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            daemon = _FakeNoteDaemon()
            backend = _backend(d, daemon=daemon)
            backend.start_note_recording()
            paused = backend.pause_note_recording()
            self.assertTrue(paused["recording"])
            self.assertTrue(paused["paused"])
            resumed = backend.resume_note_recording()
            self.assertTrue(resumed["recording"])
            self.assertFalse(resumed["paused"])

    def test_note_controls_require_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                _backend(d).start_note_recording()

    def test_relative_label_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            now = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
            backend = _backend(d, now=lambda: now)
            self.assertEqual(backend._relative(now - timedelta(seconds=5)), "just now")
            self.assertEqual(backend._relative(now - timedelta(minutes=3)), "3m ago")
            self.assertEqual(backend._relative(now - timedelta(hours=2)), "2h ago")
            self.assertEqual(backend._relative(now - timedelta(days=4)), "4d ago")


class UiBackendApiKeyTests(unittest.TestCase):
    def test_save_key_validates_format(self) -> None:
        saved: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(
                d,
                save_api_key=lambda b, k: saved.append((b, k)),
                validate_api_key_format=lambda b, k: None,
            )
            res = backend.save_provider_key("openai", "sk-abc123abc123abc123")
            self.assertEqual(saved, [("openai", "sk-abc123abc123abc123")])
            self.assertIn("backend", res)

    def test_save_key_rejects_bad_format(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, validate_api_key_format=lambda b, k: "looks wrong")
            with self.assertRaises(Exception):
                backend.save_provider_key("openai", "bad")

    def test_unknown_provider_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                _backend(d).save_provider_key("acme", "sk-xxxxxxxxxxxxxxxxxx")

    def test_clear_key(self) -> None:
        cleared: list[str] = []
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, clear_api_key=lambda b: cleared.append(b))
            res = backend.clear_provider_key("xai")
            self.assertEqual(cleared, ["xai"])
            self.assertFalse(res["configured"])


class UiBackendDoctorTests(unittest.TestCase):
    def test_doctor_checks(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            report = _backend(d).run_doctor()
            labels = [c["label"] for c in report["checks"]]
            self.assertIn("Microphone access", labels)
            self.assertIn("Shortcut registered", labels)
            self.assertTrue(report["ok"])


class UiBackendUpdateStatusTests(unittest.TestCase):
    def test_update_status_shape(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            status = _backend(d).get_update_status()
            self.assertEqual(status["currentVersion"], RELEASE_VERSION)
            self.assertEqual(status["latestVersion"], RELEASE_VERSION)
            self.assertTrue(status["updateAvailable"])
            self.assertTrue(status["checked"])
            self.assertEqual(status["url"], "https://example.test/releases")
            self.assertEqual(status["platform"], "linux")
            self.assertEqual(status["installKind"], "linux-package")
            self.assertEqual(status["phase"], "available")
            self.assertEqual(status["step"], "ready")
            self.assertEqual(status["progress"], 0)
            self.assertEqual(status["missingDeps"], [])
            self.assertEqual(status["currentVersion"], RELEASE_VERSION)
            self.assertEqual(status["commands"]["release"], "https://example.test/releases")

    def test_start_update_shape(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            flow = _backend(d).start_update()
            self.assertEqual(flow["mode"], "release")
            self.assertFalse(flow["started"])
            self.assertEqual(flow["url"], "https://example.test/releases")
            self.assertEqual(flow["message"], "Open the latest Linux package.")
            self.assertEqual(flow["platform"], "linux")
            self.assertEqual(flow["installKind"], "linux-package")
            self.assertEqual(flow["phase"], "manual")
            self.assertEqual(flow["step"], "release")
            self.assertEqual(flow["progress"], 0)
            self.assertEqual(flow["actions"], ["open_release"])

    def test_patch_config_sets_stable_update_channel_without_pro(self) -> None:
        class _SignedOutProClient(_FakeProClient):
            def get_state(self) -> dict[str, object]:
                state = super().get_state()
                state["signedIn"] = False
                state["account"] = None
                return state

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, pro_client=_SignedOutProClient())
            state = backend.patch_config({"updateChannel": "stable"})

            self.assertEqual(state["updateChannel"], "stable")
            self.assertEqual(config_mod.load_config(backend.config_path).update_channel, "stable")

    def test_patch_config_sets_beta_update_channel_without_pro(self) -> None:
        class _SignedOutProClient(_FakeProClient):
            def get_state(self) -> dict[str, object]:
                state = super().get_state()
                state["signedIn"] = False
                state["account"] = None
                return state

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, pro_client=_SignedOutProClient())
            state = backend.patch_config({"updateChannel": "unstable"})

            self.assertEqual(state["updateChannel"], "unstable")
            self.assertEqual(config_mod.load_config(backend.config_path).update_channel, "unstable")

    def test_patch_config_sets_beta_update_channel_for_inactive_pro(self) -> None:
        class _InactiveProClient(_FakeProClient):
            def get_state(self) -> dict[str, object]:
                state = super().get_state()
                state["entitlements"] = {"active": False, "status": "expired"}
                return state

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, pro_client=_InactiveProClient())
            state = backend.patch_config({"updateChannel": "unstable"})

            self.assertEqual(state["updateChannel"], "unstable")
            self.assertEqual(config_mod.load_config(backend.config_path).update_channel, "unstable")

    def test_patch_config_sets_beta_update_channel_for_pro(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d, pro_client=_FakeProClient())
            state = backend.patch_config({"updateChannel": "unstable"})

            self.assertEqual(state["updateChannel"], "unstable")
            self.assertEqual(config_mod.load_config(backend.config_path).update_channel, "unstable")


@unittest.skipIf(
    sys.platform == "win32",
    "Windows CI intermittently interrupts threaded localhost server startup.",
)
class HttpIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.handle = serve(
            backend=_backend(self._tmp.name),
            token="test-token",
            write_handshake=False,
        )
        self.addCleanup(self.handle.shutdown)
        self.base = self.handle.url

    def _get(self, path: str, token: str | None = "test-token"):
        req = urllib.request.Request(self.base + path)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        return urllib.request.urlopen(req, timeout=5)

    def _post(self, path: str, payload=None, token: str | None = "test-token"):
        data = json.dumps(payload or {}).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        return urllib.request.urlopen(req, timeout=5)

    def test_health_is_unauthenticated(self) -> None:
        with urllib.request.urlopen(self.base + "/api/health", timeout=5) as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["status"], "ok")

    def test_state_requires_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/state", token=None)
        self.assertEqual(ctx.exception.code, 401)

    def test_authorized_state(self) -> None:
        with patch(
            "dictate.ui_server.resolve_default_local_backend",
            return_value=("parakeet", "parakeet-tdt-0.6b-v2"),
        ):
            with self._get("/api/state") as resp:
                body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["model"]["backend"], "parakeet")

    def test_authorized_update_status(self) -> None:
        with self._get("/api/update-status") as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertTrue(body["updateAvailable"])
        self.assertEqual(body["latestVersion"], RELEASE_VERSION)

    def test_authorized_update_start(self) -> None:
        with self._post("/api/update") as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["mode"], "release")
        self.assertFalse(body["started"])
        self.assertEqual(body["url"], "https://example.test/releases")

    def test_note_toggle_over_http(self) -> None:
        self.handle.backend.daemon = _FakeNoteDaemon()
        with self._post("/api/notes/toggle") as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertTrue(body["recording"])

    def test_note_discard_over_http(self) -> None:
        daemon = _FakeNoteDaemon()
        daemon.note_recording_active = True
        daemon.note_recording_paused = True
        self.handle.backend.daemon = daemon
        with self._post("/api/notes/discard") as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertFalse(body["recording"])
        self.assertFalse(body["paused"])
        self.assertEqual(daemon.calls, ["discard"])

    def test_meeting_discard_over_http(self) -> None:
        daemon = _FakeNoteDaemon()
        daemon.note_recording_active = True
        daemon.note_recording_paused = True
        daemon.long_recording_mode = "meeting"
        self.handle.backend.daemon = daemon
        with self._post("/api/meetings/discard") as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertFalse(body["recording"])
        self.assertEqual(daemon.calls, ["discard-meeting"])

    def test_history_unarchive_over_http(self) -> None:
        backend = self.handle.backend
        history_id = backend.history_store.load()[0].id if backend.history_store.load() else None
        if history_id is None:
            backend.history_store.append("quick dictation")
            history_id = backend.history_store.load()[0].id
        backend.archive_history_item(history_id)
        with self._post("/api/history/unarchive", {"id": history_id}) as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        ids = [item["id"] for item in body["history"]]
        self.assertIn(history_id, ids)

    def test_create_pro_meeting_over_http_passes_audio_duration(self) -> None:
        pro_client = _FakeProClient()
        self.handle.backend.pro_client = pro_client
        with self._post(
            "/api/pro/meetings",
            {"language": "en", "audioDurationSeconds": 12.5},
        ) as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["job_id"], "job_test")
        self.assertEqual(
            pro_client.create_calls,
            [{"language": "en", "audio_duration_seconds": 12.5}],
        )

    def test_browser_signin_routes_over_http(self) -> None:
        opened = []
        pro_client = _FakeBrowserProClient(
            poll_result={"status": "complete", "account_id": "acct_x", "device_id": "device_x"}
        )
        self.handle.backend.pro_client = pro_client
        self.handle.backend.browser_signin_enabled = lambda: True
        self.handle.backend.open_browser = lambda url: opened.append(url)

        with self._post("/api/pro/auth/browser/start", {"flow": "auto"}) as resp:
            start_body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(start_body["flow"], "loopback")
        self.assertEqual(opened, [start_body["authorize_url"]])

        with self._get("/api/pro/auth/browser/status") as resp:
            status_body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(status_body["status"], "complete")
        self.assertTrue(status_body["dictatePro"]["signedIn"])

        with self._post("/api/pro/auth/browser/cancel") as resp:
            cancel_body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(cancel_body, {"status": "cancelled"})
        self.assertEqual(pro_client.cancel_calls, 1)

    def test_browser_signin_start_over_http_falls_back_to_email_when_disabled(self) -> None:
        self.handle.backend.pro_client = _FakeBrowserProClient()
        with patch.dict("os.environ", {"DICTATE_PRO_BROWSER_SIGNIN": ""}):
            with self._post("/api/pro/auth/browser/start") as resp:
                body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body, {"flow": "email"})

    def test_sync_enable_run_disable_over_http(self) -> None:
        base = Path(self._tmp.name)
        self.handle.backend.pro_client = _FakeProClient()
        self.handle.backend.sync_settings = _sync_settings(base)
        with self._post("/api/pro/sync/enable") as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertTrue(body["sync"]["enabled"])
        self.assertIn("recoveryKey", body)
        self.assertEqual(
            {item["envelope_kind"] for item in self.handle.backend.pro_client.saved_key_envelopes},
            {"device", "recovery"},
        )

        self.handle.backend.history_store.append("queued private")
        with self._post("/api/pro/sync/run") as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["result"]["pushed"], 1)

        with self._post("/api/pro/sync/disable", {"clearKey": True}) as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertFalse(body["sync"]["enabled"])

        req = urllib.request.Request(self.base + "/api/pro/devices", method="GET")
        req.add_header("Authorization", "Bearer test-token")
        with urllib.request.urlopen(req, timeout=5) as resp:
            devices = json.loads(resp.read())
        self.assertEqual(devices["devices"][0]["device_id"], "device_test")

        with self._post("/api/pro/devices/revoke", {"deviceId": "device_other"}) as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertTrue(body["revoked"])
        self.assertEqual(self.handle.backend.pro_client.revoked_devices, ["device_other"])

        req = urllib.request.Request(self.base + "/api/pro/cloud/export", method="GET")
        req.add_header("Authorization", "Bearer test-token")
        with urllib.request.urlopen(req, timeout=5) as resp:
            exported = json.loads(resp.read())
        self.assertEqual(exported["account"]["account_id"], "acct_test")

        req = urllib.request.Request(self.base + "/api/pro/cloud/delete", data=b"{}", method="DELETE")
        req.add_header("Authorization", "Bearer test-token")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            deleted = json.loads(resp.read())
        self.assertEqual(deleted["cloud"]["deleted"]["sync_records"], 0)
        self.assertTrue(self.handle.backend.pro_client.deleted_cloud)

    def test_patch_config_over_http(self) -> None:
        payload = json.dumps({"prefs": {"theme": "dark"}}).encode()
        req = urllib.request.Request(
            self.base + "/api/config", data=payload, method="PATCH"
        )
        req.add_header("Authorization", "Bearer test-token")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
        self.assertEqual(body["prefs"]["theme"], "dark")

    def test_options_preflight(self) -> None:
        req = urllib.request.Request(self.base + "/api/state", method="OPTIONS")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers["Access-Control-Allow-Origin"], "*")


class HandshakeTests(unittest.TestCase):
    def test_write_runtime_handshake(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ui-server.json"
            write_runtime_handshake("http://127.0.0.1:9", "tok", pid=42, path=path)
            data = json.loads(path.read_text())
            self.assertEqual(data["url"], "http://127.0.0.1:9")
            self.assertEqual(data["token"], "tok")
            self.assertEqual(data["pid"], 42)
            self.assertEqual(data["version"], RELEASE_VERSION)


if __name__ == "__main__":
    unittest.main()
