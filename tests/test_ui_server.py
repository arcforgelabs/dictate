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


def _write_legacy_meeting_note(
    notes_root: Path,
    note_id: str,
    segments: list[tuple[str, str, float, float]],
) -> str:
    """Write a transcript the way Meeting capture saved it in 2026.9.27.

    Meeting was removed in #140. Its saved transcripts are plain files under the
    notes directory, so an upgrade finds exactly these: mode "meeting",
    speaker_labels set, and speaker fields on every segment. ``segments`` is
    ``(speaker_label, text, t_start, t_end)``.
    """
    stamp = "2026-09-30T01:00:00+00:00"
    note_dir = notes_root / note_id
    note_dir.mkdir(parents=True)
    record = {
        "note_id": note_id,
        "mode": "meeting",
        "provider": "parakeet-pyannote",
        "model": "parakeet-tdt-0.6b-v2+pyannote/speaker-diarization-community-1",
        "started_at": stamp,
        "ended_at": stamp,
        "duration_s": None,
        "status": "ready",
        "speaker_labels": True,
        "archived": False,
        "recording_id": 1,
        "error": None,
        "rev": 3,
        "updated_at": stamp,
    }
    (note_dir / "note.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    lines = [
        json.dumps(
            {
                "seq": seq,
                "t_start": t_start,
                "t_end": t_end,
                "provider": "parakeet-pyannote",
                "model": record["model"],
                "text": text,
                "speaker_id": f"SPEAKER_{seq:02d}",
                "speaker_label": label,
            }
        )
        for seq, (label, text, t_start, t_end) in enumerate(segments)
    ]
    (note_dir / "segments.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return note_id


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

    @property
    def long_recording_active(self) -> bool:
        return self.note_recording_active

    def start_note_recording(self) -> bool:
        self.calls.append("start")
        self.note_recording_active = True
        self.note_recording_paused = False
        self.long_recording_mode = "note"
        return True

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

    def cancel_note_recording(self) -> bool:
        self.calls.append("discard")
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
                model["model"] for model in state["models"] if model["backend"] == "parakeet"
            ]
            self.assertEqual(local_models, ["parakeet-tdt-0.6b-v2", "parakeet-tdt-0.6b-v3"])
            backends = {m["backend"] for m in state["models"]}
            self.assertEqual(backends, {"parakeet"})
            # Meeting capture was removed (#140).
            self.assertNotIn("meetingModel", state)
            self.assertNotIn("meetingReadiness", state)
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

    def test_removed_cloud_backend_migrates_to_parakeet_on_state_load(self) -> None:
        # A saved hosted backend (xAI and the others removed in 2026.9.20) is
        # not what the daemon runs. Hydrating state must report Parakeet, not
        # the faster-whisper name the old fallback used.
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            config_mod.set_stt_selection(
                "xai", "grok-speech-to-text", path=backend.config_path
            )
            state = backend.get_state()
            cfg = config_mod.load_config(backend.config_path)
            self.assertEqual(state["model"]["id"], "parakeet/parakeet-tdt-0.6b-v2")
            self.assertEqual(state["model"]["backend"], "parakeet")
            self.assertEqual(cfg.stt_backend, "parakeet")
            self.assertEqual(cfg.stt_model, "parakeet-tdt-0.6b-v2")

    def test_removed_whisper_backends_migrate_to_parakeet_on_state_load(self) -> None:
        # faster-whisper / whisperx were removed; a saved selection is stale state
        # and is rewritten to the Parakeet default, never keeping a Whisper model.
        from dictate import config as config_mod

        for saved in (("faster-whisper", "turbo"), ("faster-whisper", "base"), ("whisperx", "large-v3")):
            with self.subTest(saved=saved), tempfile.TemporaryDirectory() as d:
                backend = _backend(d)
                config_mod.set_stt_selection(*saved, path=backend.config_path)
                state = backend.get_state()
                cfg = config_mod.load_config(backend.config_path)
                self.assertEqual(state["model"]["id"], "parakeet/parakeet-tdt-0.6b-v2")
                self.assertEqual(state["providerHealth"]["preferred"], "parakeet")
                self.assertEqual(cfg.stt_backend, "parakeet")
                self.assertEqual(cfg.stt_model, "parakeet-tdt-0.6b-v2")

    def test_unset_backend_with_legacy_whisper_model_reports_parakeet_default(self) -> None:
        # An unset backend used to mean faster-whisper, so a saved model is a
        # Whisper name that must not be carried into Parakeet.
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.config_path.write_text("stt_model: turbo\n", encoding="utf-8")
            state = backend.get_state()
            report = backend.run_doctor()
            model_check = next(c for c in report["checks"] if c["label"] == "Model loads")
            self.assertEqual(state["model"]["id"], "parakeet/parakeet-tdt-0.6b-v2")
            self.assertEqual(model_check["sub"], "parakeet · parakeet-tdt-0.6b-v2")
            self.assertIsNone(config_mod.load_config(backend.config_path).stt_backend)

    def test_unset_backend_with_parakeet_model_keeps_that_model(self) -> None:
        # config/default-config.yaml offers a model-only line for multilingual
        # dictation; it must not fall back to English v2.
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.config_path.write_text(
                "stt_model: parakeet-tdt-0.6b-v3\nmeeting_stt_model: parakeet-tdt-0.6b-v3\n",
                encoding="utf-8",
            )
            state = backend.get_state()
            report = backend.run_doctor()
            model_check = next(c for c in report["checks"] if c["label"] == "Model loads")
            cfg = config_mod.load_config(backend.config_path)
            self.assertEqual(state["model"]["id"], "parakeet/parakeet-tdt-0.6b-v3")
            self.assertNotIn("meetingModel", state)
            self.assertEqual(model_check["sub"], "parakeet · parakeet-tdt-0.6b-v3")
            self.assertIsNone(cfg.stt_backend)
            self.assertEqual(cfg.stt_model, "parakeet-tdt-0.6b-v3")
            # The saved Meeting model was dropped on load (#140).
            self.assertNotIn("meeting_stt_model", backend.config_path.read_text(encoding="utf-8"))

    def test_state_load_drops_saved_meeting_selection(self) -> None:
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.config_path.write_text(
                "stt_backend: parakeet-pyannote\n"
                "stt_model: parakeet-tdt-0.6b-v3\n"
                "meeting_stt_backend: parakeet-pyannote\n"
                "meeting_stt_model: parakeet-tdt-0.6b-v2\n",
                encoding="utf-8",
            )

            with self.assertLogs("dictate.config", level="WARNING"):
                state = backend.get_state()
            cfg = config_mod.load_config(backend.config_path)

            # A Meeting backend saved for dictation keeps its Parakeet model.
            self.assertEqual(state["model"]["id"], "parakeet/parakeet-tdt-0.6b-v3")
            self.assertNotIn("meetingModel", state)
            self.assertNotIn("meetingReadiness", state)
            self.assertEqual(cfg.stt_backend, "parakeet")
            self.assertEqual(cfg.stt_model, "parakeet-tdt-0.6b-v3")
            self.assertNotIn("meeting", backend.config_path.read_text(encoding="utf-8"))

    def test_whisper_selection_from_client_is_rejected(self) -> None:
        # A stale client sending the old hardcoded "faster-whisper/turbo" intent
        # must not persist a backend this build no longer ships.
        from dictate import config as config_mod

        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            with self.assertRaises(ApiError) as raised:
                backend.patch_config({"model": {"backend": "faster-whisper", "model": "turbo"}})
            self.assertEqual(raised.exception.status, 400)
            self.assertIsNone(config_mod.load_config(backend.config_path).stt_backend)

    def test_models_default_flag_marks_parakeet_default(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            state = _backend(d).get_state()
            defaults = [m["model"] for m in state["models"] if m["backend"] == "parakeet" and m["default"]]
            self.assertEqual(defaults, ["parakeet-tdt-0.6b-v2"])

    def test_run_doctor_reports_parakeet_default_model(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            report = _backend(d).run_doctor()
            model_check = next(c for c in report["checks"] if c["label"] == "Model loads")
            self.assertEqual(model_check["sub"], "parakeet · parakeet-tdt-0.6b-v2")


    def test_set_model_via_dict(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.patch_config({"model": {"backend": "parakeet", "model": "parakeet-tdt-0.6b-v3"}})
            self.assertEqual(backend.get_state()["model"]["id"], "parakeet/parakeet-tdt-0.6b-v3")

    def test_meeting_backend_selection_from_client_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            with self.assertRaises(ApiError) as raised:
                backend.patch_config(
                    {"model": {"backend": "parakeet-pyannote", "model": "parakeet-tdt-0.6b-v2"}}
                )
            self.assertEqual(raised.exception.status, 400)
            self.assertIsNone(config_mod.load_config(backend.config_path).stt_backend)


    def test_unknown_backend_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(Exception):
                _backend(d).patch_config({"model": "nope/x"})

















    def test_export_local_data_includes_history_and_notes_without_cloud_or_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            history_entry = backend.history_store.append("local export history")
            # A meeting transcript saved before Meeting was removed (#140)
            # still exports, speaker labels and all.
            note_id = _write_legacy_meeting_note(
                Path(d) / "notes",
                "note_legacymeeting",
                [("Speaker 1", "local export meeting segment", 1.0, 2.5)],
            )

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
            note_id = note_store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
            note_store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=1.0,
                    provider="parakeet",
                    model="parakeet-tdt-0.6b-v2",
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

    def test_ui_exposes_no_device_control(self) -> None:
        # Dictate runs on CPU only: no device in state, and a stale client's
        # device patch is ignored rather than written back to config.
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)

            self.assertNotIn("device", backend.get_state())

            backend.patch_config({"device": {"device": "cuda", "compute": "float16"}})

            config_path = Path(backend.config_path)
            saved = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
            self.assertNotIn("stt_device", saved)
            self.assertNotIn("stt_compute_type", saved)
            self.assertIsNone(config_mod.load_config(backend.config_path).stt_compute_type)


    def test_get_history_orders_by_when_it_was_spoken(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            note_store = NoteStore(Path(d) / "notes")
            history_store = HistoryStore(Path(d) / "history.json")
            note_id = note_store.create_note(provider="parakeet", model="parakeet-tdt-0.6b-v2")
            note_store.append_segment(
                note_id,
                NoteSegment(
                    seq=0,
                    t_start=0.0,
                    t_end=1.0,
                    provider="parakeet",
                    model="parakeet-tdt-0.6b-v2",
                    text="hosted final",
                ),
            )
            note_store.mark_interrupted(note_id)
            note_path = Path(d) / "notes" / note_id / "note.json"
            raw = json.loads(note_path.read_text(encoding="utf-8"))
            raw["started_at"] = "2026-07-18T03:30:27+00:00"
            raw["ended_at"] = "2026-08-04T02:30:14+00:00"
            note_path.write_text(json.dumps(raw), encoding="utf-8")
            history_store.append("Well, I guess we check to see if this works still.")
            backend = _backend(d, history_store=history_store, note_store=note_store)

            history = backend.get_history()

            self.assertEqual(
                [item["text"] for item in history],
                [
                    "Well, I guess we check to see if this works still.",
                    "hosted final",
                ],
            )

    def test_saved_meeting_transcript_stays_in_history_after_upgrade(self) -> None:
        # Meeting capture was removed (#140); a transcript it saved is a note
        # like any other: listed, readable with its speaker labels, archivable.
        with tempfile.TemporaryDirectory() as d:
            note_store = NoteStore(Path(d) / "notes")
            history_store = HistoryStore(Path(d) / "history.json")
            note_id = _write_legacy_meeting_note(
                Path(d) / "notes",
                "note_legacymeeting",
                [
                    ("Speaker 1", "hello", 0.0, 1.25),
                    ("Speaker 2", "hi there", 1.25, 2.0),
                ],
            )
            # The daemon also put the finished text on the rolling history.
            history_store.append("Speaker 1: hello Speaker 2: hi there")
            backend = _backend(d, history_store=history_store, note_store=note_store)

            history = backend.get_history()
            payload = UiBackend.note_payload(note_store, note_id)

            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["id"], note_id)
            self.assertEqual(history[0]["mode"], "meeting")
            self.assertEqual(history[0]["text"], "Speaker 1: hello Speaker 2: hi there")
            self.assertEqual(history[0]["segments"][0]["speakerLabel"], "Speaker 1")
            self.assertEqual(history[0]["segments"][0]["tStart"], 0.0)
            assert payload is not None
            self.assertTrue(payload["speakerLabels"])
            self.assertEqual(payload["segments"][1]["speakerLabel"], "Speaker 2")
            self.assertEqual(payload["segments"][1]["tEnd"], 2.0)
            # Archive and restore still work on it, and nothing deletes it.
            backend.archive_history_item(note_id)
            self.assertNotIn(note_id, [item["id"] for item in backend.get_history()])
            backend.unarchive_history_item(note_id)
            self.assertEqual(backend.get_history()[0]["id"], note_id)
            self.assertTrue((Path(d) / "notes" / note_id / "segments.jsonl").is_file())

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

    def test_patch_config_rejects_channel_switch(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            with self.assertRaises(ApiError) as raised:
                backend.patch_config({"updateChannel": "unstable"})
            self.assertEqual(raised.exception.status, 409)
            self.assertEqual(backend.get_state()["updateChannel"], "stable")



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

    def test_meeting_routes_are_gone(self) -> None:
        # Meeting capture was removed (#140).
        daemon = _FakeNoteDaemon()
        self.handle.backend.daemon = daemon
        for route in ("/api/meetings/start", "/api/meetings/stop", "/api/meetings/discard"):
            with self.subTest(route=route):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self._post(route)
                self.assertEqual(ctx.exception.code, 404)
                ctx.exception.close()
        self.assertEqual(daemon.calls, [])

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
