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

from dictate import config as config_mod
from dictate.history import HistoryStore
from dictate.note_store import NoteSegment, NoteStore
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
            # local models only (parakeet English default leads)
            self.assertEqual(state["models"][0]["backend"], "parakeet")
            self.assertTrue(state["models"][0]["local"])
            local_models = [
                model["model"] for model in state["models"] if model["backend"] == "faster-whisper"
            ]
            self.assertEqual(
                local_models,
                [
                    "tiny",
                    "base",
                    "small",
                    "medium",
                    "large-v3",
                    "turbo",
                    "large-v3-turbo",
                    "distil-large-v3.5",
                ],
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
                },
            )
            # default shortcut + activation
            self.assertEqual(state["shortcut"]["combo"], "ctrl_r")
            self.assertEqual(state["shortcut"]["display"], ["Ctrl (R)"])
            self.assertEqual(state["shortcut"]["activation"], "hold")
            self.assertEqual(state["prefs"], DEFAULT_PREFS)
            # Transcription is local-only: every listed model runs on this machine.
            self.assertTrue(all(model["local"] for model in state["models"]))
            self.assertEqual(state["providerHealth"]["mode"], "private")
            self.assertEqual(state["providerHealth"]["status"], "ok")
            self.assertTrue(state["providerHealth"]["healthy"])

    def test_parakeet_provider_health_is_private(self) -> None:
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            config_mod.set_stt_selection("parakeet", "parakeet-tdt-0.6b-v2", path=backend.config_path)

            state = backend.get_state()

        self.assertEqual(state["providerHealth"]["mode"], "private")
        self.assertEqual(state["providerHealth"]["status"], "ok")
        self.assertTrue(state["providerHealth"]["healthy"])


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


    def test_set_model_via_dict(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.patch_config({"model": {"backend": "parakeet-pyannote", "model": "parakeet-tdt-0.6b-v2"}})
            self.assertEqual(backend.get_state()["model"]["backend"], "parakeet-pyannote")


    def test_unknown_backend_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                _backend(d).patch_config({"model": "nope/x"})

















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

    def test_patch_config_sets_stable_update_channel(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            state = backend.patch_config({"updateChannel": "stable"})

            self.assertEqual(state["updateChannel"], "stable")
            self.assertEqual(config_mod.load_config(backend.config_path).update_channel, "stable")

    def test_patch_config_sets_beta_update_channel(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
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
