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
from dictate.history import HistoryStore
from dictate.update_status import UpdateFlow, UpdateStatus
from dictate.version import RELEASE_VERSION
from dictate.ui_server import (
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
    )
    kwargs.update(overrides)
    return UiBackend(**kwargs)


class _FakeNoteDaemon:
    def __init__(self) -> None:
        self.note_recording_active = False
        self.note_recording_paused = False
        self.calls: list[str] = []

    def start_note_recording(self) -> bool:
        self.calls.append("start")
        self.note_recording_active = True
        self.note_recording_paused = False
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
            prefs = store.update({"theme": "dark", "overlay": False, "junk": 1})
            self.assertEqual(prefs["theme"], "dark")
            self.assertFalse(prefs["overlay"])
            self.assertNotIn("junk", prefs)
            # reload from disk
            self.assertEqual(UiPrefsStore(path).load()["theme"], "dark")

    def test_invalid_theme_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            path.write_text(json.dumps({"theme": "neon", "activation": "wat"}))
            prefs = UiPrefsStore(path).load()
            self.assertEqual(prefs["theme"], DEFAULT_PREFS["theme"])
            self.assertEqual(prefs["activation"], DEFAULT_PREFS["activation"])


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
            state = _backend(d).get_state()
            self.assertIn("version", state)
            self.assertEqual(state["model"]["backend"], "faster-whisper")
            self.assertEqual(state["model"]["model"], "turbo")
            self.assertEqual(state["model"]["id"], "faster-whisper/turbo")
            # local models first, hosted providers present
            self.assertEqual(state["models"][0]["backend"], "faster-whisper")
            self.assertTrue(state["models"][0]["local"])
            backends = {m["backend"] for m in state["models"]}
            self.assertEqual(backends, {"faster-whisper", "whisperx", "openai", "xai", "gemini"})
            # default shortcut + activation
            self.assertEqual(state["shortcut"]["combo"], "ctrl_r")
            self.assertEqual(state["shortcut"]["display"], ["Ctrl (R)"])
            self.assertEqual(state["shortcut"]["activation"], "hold")
            self.assertEqual(state["prefs"], DEFAULT_PREFS)
            self.assertEqual(state["providers"]["openai"]["status"], "None")

    def test_state_reflects_configured_model(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend = _backend(d)
            backend.patch_config({"model": "gemini/gemini-3-flash-preview"})
            state = backend.get_state()
            self.assertEqual(state["model"]["backend"], "gemini")
            self.assertEqual(state["model"]["model"], "gemini-3-flash-preview")

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

    def test_note_controls_call_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            daemon = _FakeNoteDaemon()
            backend = _backend(d, daemon=daemon)
            self.assertFalse(backend.get_state()["notes"]["recording"])
            started = backend.start_note_recording()
            self.assertTrue(started["recording"])
            self.assertFalse(started["paused"])
            paused = backend.pause_note_recording()
            self.assertTrue(paused["recording"])
            self.assertTrue(paused["paused"])
            resumed = backend.resume_note_recording()
            self.assertTrue(resumed["recording"])
            self.assertFalse(resumed["paused"])
            self.assertFalse(backend.stop_note_recording()["recording"])
            self.assertTrue(backend.toggle_note_recording()["recording"])
            self.assertEqual(daemon.calls, ["start", "pause", "resume", "stop", "toggle"])

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
        with self._get("/api/state") as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["model"]["backend"], "faster-whisper")

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
