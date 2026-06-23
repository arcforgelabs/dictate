"""Tests for provider-health state in UiBackend and DictationEngine."""

from __future__ import annotations

import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from dictate.api_keys import ApiKeyStatus
from dictate.history import HistoryStore
from dictate.ui_server import (
    EventBroker,
    UiBackend,
    UiPrefsStore,
    _ProviderHealthState,
)
from dictate.update_status import UpdateFlow, UpdateStatus
from dictate.version import RELEASE_VERSION


def _backend(temp_dir: str, **overrides) -> UiBackend:
    """UiBackend wired to temp paths and harmless fakes."""
    base = Path(temp_dir)
    kwargs = dict(
        config_path=base / "config.yaml",
        history_store=HistoryStore(base / "history.json"),
        prefs_store=UiPrefsStore(base / "ui-prefs.json"),
        save_api_key=lambda backend, key: None,
        clear_api_key=lambda backend: None,
        api_key_status=lambda backend, **kw: ApiKeyStatus(backend=backend, status="None"),
        validate_api_key_format=lambda backend, key: None,
        secret_store_description=lambda: "test-store",
        secret_store_available=lambda: True,
        check_update_status=lambda: UpdateStatus(
            current_version=RELEASE_VERSION,
            latest_version=RELEASE_VERSION,
            update_available=False,
            checked=True,
        ),
        start_update_flow=lambda: UpdateFlow(
            mode="release", started=False, url=None, message=None,
            platform="linux", install_kind="linux-package",
        ),
        startup_enabled=lambda: False,
        set_startup_enabled=lambda e: None,
    )
    kwargs.update(overrides)
    return UiBackend(**kwargs)


class ProviderHealthStateTests(unittest.TestCase):
    """Unit tests for the _ProviderHealthState class."""

    def test_defaults_healthy(self) -> None:
        ph = _ProviderHealthState()
        healthy, reason = ph.get()
        self.assertTrue(healthy)
        self.assertIsNone(reason)

    def test_report_changes_state(self) -> None:
        ph = _ProviderHealthState()
        changed = ph.report(False, "auth")
        self.assertTrue(changed)
        healthy, reason = ph.get()
        self.assertFalse(healthy)
        self.assertEqual(reason, "auth")

    def test_report_returns_false_when_unchanged(self) -> None:
        ph = _ProviderHealthState()
        ph.report(False, "auth")
        changed = ph.report(False, "auth")
        self.assertFalse(changed)

    def test_thread_safety(self) -> None:
        """Concurrent reads and writes must not raise."""
        ph = _ProviderHealthState()
        errors: list[Exception] = []

        def writer() -> None:
            for i in range(100):
                ph.report(i % 2 == 0, "auth" if i % 2 else None)

        def reader() -> None:
            for _ in range(100):
                ph.get()

        threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class ProviderHealthInGetStateTests(unittest.TestCase):
    """UiBackend.get_state() providerHealth field."""

    def _write_config(self, path: Path, stt_backend: str) -> None:
        import yaml
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump({"stt_backend": stt_backend}))

    def test_private_mode_always_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            self._write_config(cfg_path, "faster-whisper")
            backend = _backend(d, config_path=cfg_path)
            ph = backend.get_state()["providerHealth"]
        self.assertTrue(ph["healthy"])
        self.assertEqual(ph["mode"], "private")
        self.assertEqual(ph["status"], "ok")

    def test_online_no_key_unhealthy(self) -> None:
        import dictate.api_keys as ak_mod
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            self._write_config(cfg_path, "xai")
            backend = _backend(d, config_path=cfg_path)
            orig = ak_mod.has_stored_api_key
            try:
                ak_mod.has_stored_api_key = lambda b: False
                ph = backend.get_state()["providerHealth"]
            finally:
                ak_mod.has_stored_api_key = orig
        self.assertFalse(ph["healthy"])
        self.assertEqual(ph["mode"], "online")
        self.assertEqual(ph["status"], "no-key")

    def test_online_with_key_and_healthy_engine(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            self._write_config(cfg_path, "xai")
            backend = _backend(
                d,
                config_path=cfg_path,
                # Simulate a stored key being present
                api_key_status=lambda b, **kw: ApiKeyStatus(backend=b, status="Ready", source="secret-store"),
            )
            # Patch has_stored_api_key so it returns True for xai
            import dictate.api_keys as ak_mod
            orig = ak_mod.has_stored_api_key
            try:
                ak_mod.has_stored_api_key = lambda b: b == "xai"
                ph = backend.get_state()["providerHealth"]
            finally:
                ak_mod.has_stored_api_key = orig
        self.assertTrue(ph["healthy"])
        self.assertEqual(ph["mode"], "online")

    def test_online_with_key_engine_reports_auth_failure(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            self._write_config(cfg_path, "xai")
            backend = _backend(d, config_path=cfg_path)
            # Simulate a stored key
            import dictate.api_keys as ak_mod
            orig = ak_mod.has_stored_api_key
            try:
                ak_mod.has_stored_api_key = lambda b: b == "xai"
                # Simulate engine reporting an auth failure
                backend.provider_health.report(False, "auth")
                ph = backend.get_state()["providerHealth"]
            finally:
                ak_mod.has_stored_api_key = orig
        self.assertFalse(ph["healthy"])
        self.assertEqual(ph["status"], "auth")
        self.assertEqual(ph["mode"], "online")

    def test_no_stt_backend_defaults_to_private(self) -> None:
        """Unset stt_backend → faster-whisper → private/healthy."""
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.yaml"
            # No config file → Config defaults with stt_backend=None
            backend = _backend(d, config_path=cfg_path)
            ph = backend.get_state()["providerHealth"]
        self.assertTrue(ph["healthy"])
        self.assertEqual(ph["mode"], "private")


class ConnectEngineHealthTests(unittest.TestCase):
    """UiBackend.connect_engine_health wires the engine's health_sink."""

    def test_wires_health_sink(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            broker = EventBroker()
            backend = _backend(d, broker=broker)

            # Fake engine with a settable health_sink
            engine = MagicMock()
            engine.health_sink = None
            backend.connect_engine_health(engine)

            # The sink should have been set
            self.assertIsNotNone(engine.health_sink)

    def test_health_sink_updates_state_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            broker = EventBroker()
            events: list[dict] = []
            q = broker.subscribe()

            backend = _backend(d, broker=broker)
            engine = MagicMock()
            backend.connect_engine_health(engine)

            # Capture the installed sink
            sink = engine.health_sink

            # Simulate an auth failure
            sink(False, "auth")
            healthy, reason = backend.provider_health.get()
            self.assertFalse(healthy)
            self.assertEqual(reason, "auth")

            # An SSE event should have been published
            import queue as _q
            try:
                ev = q.get_nowait()
                self.assertEqual(ev["type"], "provider-health")
                self.assertFalse(ev["healthy"])
                self.assertEqual(ev["status"], "auth")
            except _q.Empty:
                self.fail("Expected provider-health SSE event but queue was empty")

    def test_health_sink_no_duplicate_event_on_same_state(self) -> None:
        """Publishing only fires when state changes."""
        with tempfile.TemporaryDirectory() as d:
            broker = EventBroker()
            q = broker.subscribe()
            backend = _backend(d, broker=broker)
            engine = MagicMock()
            backend.connect_engine_health(engine)
            sink = engine.health_sink

            sink(False, "auth")  # change → event
            sink(False, "auth")  # no change → no event

            import queue as _q
            ev1 = q.get_nowait()
            self.assertEqual(ev1["type"], "provider-health")
            with self.assertRaises(_q.Empty):
                q.get_nowait()


class EngineHealthSinkTests(unittest.TestCase):
    """DictationEngine calls health_sink on success/failure."""

    def _make_engine(self, backend_name: str, raises=None, returns: str = "hello"):
        from dictate.engine import DictationEngine
        stt = MagicMock()
        stt.backend_name = backend_name
        stt.capabilities = MagicMock(supports_hotwords=False, supports_prompt_bias=False)
        if raises:
            stt.transcribe.side_effect = raises
        else:
            stt.transcribe.return_value = returns
        engine = DictationEngine(stt=stt, sample_rate=16000)
        return engine

    def test_success_reports_healthy(self) -> None:
        import numpy as np
        health_calls: list[tuple] = []
        engine = self._make_engine("xai", returns="hello world")
        engine.health_sink = lambda h, r: health_calls.append((h, r))
        audio = np.zeros(16000, dtype=np.float32)  # 1 s
        engine.transcribe(audio)
        self.assertTrue(any(h and r is None for h, r in health_calls))

    def test_auth_error_reports_unhealthy_auth(self) -> None:
        import numpy as np
        health_calls: list[tuple] = []
        engine = self._make_engine("xai", raises=RuntimeError("HTTP 401 unauthorized"))
        engine.health_sink = lambda h, r: health_calls.append((h, r))
        audio = np.zeros(16000, dtype=np.float32)
        engine.transcribe(audio)
        self.assertTrue(any(not h and r == "auth" for h, r in health_calls))

    def test_connection_error_reports_unreachable(self) -> None:
        import numpy as np
        health_calls: list[tuple] = []
        engine = self._make_engine("xai", raises=ConnectionError("timeout"))
        engine.health_sink = lambda h, r: health_calls.append((h, r))
        audio = np.zeros(16000, dtype=np.float32)
        engine.transcribe(audio)
        self.assertTrue(any(not h and r == "unreachable" for h, r in health_calls))

    def test_private_backend_no_health_calls(self) -> None:
        """faster-whisper never calls health_sink."""
        import numpy as np
        health_calls: list[tuple] = []
        engine = self._make_engine("faster-whisper", returns="local result")
        engine.health_sink = lambda h, r: health_calls.append((h, r))
        audio = np.zeros(16000, dtype=np.float32)
        engine.transcribe(audio)
        self.assertEqual(health_calls, [])
