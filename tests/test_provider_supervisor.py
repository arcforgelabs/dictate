"""Tests for ProviderSupervisor — error classification, fail-fast dictate,
long-recording retries, recovery scheduling, backoff, and the getState /
SSE contract wired through UiBackend.connect_supervisor().
"""

from __future__ import annotations

import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from dictate.engine import DictationEngine, _classify_health_error
from dictate.provider_supervisor import (
    FAIL_AUTH,
    FAIL_BUDGET,
    FAIL_RATE_LIMIT,
    FAIL_UNREACHABLE,
    ProviderSupervisor,
    _backoff_delay,
    _upgrade_failure_class,
)


def tearDownModule() -> None:
    """Cancel any probe Timers left alive by supervisors created in this module.

    A daemon Timer still alive at interpreter shutdown crashes the Windows test
    runner with STATUS_DLL_INIT_FAILED (0xC0000142). Most tests call
    ``supervisor.shutdown()``; this is a belt-and-suspenders sweep for the rest.
    """
    for t in threading.enumerate():
        if isinstance(t, threading.Timer) and t.is_alive():
            t.cancel()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _probe_always_fail() -> bool:
    return False


def _probe_always_ok() -> bool:
    return True


def _make_supervisor(
    preferred: str = "xai",
    probe_fn=_probe_always_fail,
    *,
    on_degraded=None,
    on_recovered=None,
) -> ProviderSupervisor:
    sup = ProviderSupervisor(
        preferred,
        probe_fn=probe_fn,
        on_degraded=on_degraded,
        on_recovered=on_recovered,
    )
    # Disable the D-Bus network trigger thread so tests don't block
    return sup


# --------------------------------------------------------------------------- #
# 1. Error classification tests
# --------------------------------------------------------------------------- #

class ClassifyHealthErrorTests(unittest.TestCase):
    """_classify_health_error maps exceptions to the 4 failure classes."""

    def _cls(self, msg: str) -> str:
        return _classify_health_error(RuntimeError(msg))

    # auth
    def test_401(self) -> None:
        self.assertEqual(self._cls("HTTP 401 unauthorized"), FAIL_AUTH)

    def test_403_forbidden(self) -> None:
        self.assertEqual(self._cls("HTTP 403 forbidden"), FAIL_AUTH)

    def test_invalid_api_key(self) -> None:
        self.assertEqual(self._cls("invalid api key provided"), FAIL_AUTH)

    def test_authentication_error(self) -> None:
        self.assertEqual(self._cls("authentication failed"), FAIL_AUTH)

    # rate-limit
    def test_429(self) -> None:
        self.assertEqual(self._cls("HTTP 429 too many requests"), FAIL_RATE_LIMIT)

    def test_rate_limit_text(self) -> None:
        self.assertEqual(self._cls("rate limit exceeded"), FAIL_RATE_LIMIT)

    def test_ratelimit_no_space(self) -> None:
        self.assertEqual(self._cls("ratelimit hit"), FAIL_RATE_LIMIT)

    # budget
    def test_insufficient_quota(self) -> None:
        self.assertEqual(self._cls("insufficient_quota for account"), FAIL_BUDGET)

    def test_quota_exceeded(self) -> None:
        self.assertEqual(self._cls("quota exceeded for this month"), FAIL_BUDGET)

    def test_billing_error(self) -> None:
        self.assertEqual(self._cls("billing issue detected"), FAIL_BUDGET)

    def test_credits_depleted(self) -> None:
        self.assertEqual(self._cls("credits balance is zero"), FAIL_BUDGET)

    # unreachable
    def test_connection_error(self) -> None:
        self.assertEqual(self._cls("connection refused"), FAIL_UNREACHABLE)

    def test_timeout(self) -> None:
        self.assertEqual(self._cls("request timed out"), FAIL_UNREACHABLE)

    def test_generic_500(self) -> None:
        self.assertEqual(self._cls("HTTP 500 internal server error"), FAIL_UNREACHABLE)

    def test_dns_failure(self) -> None:
        self.assertEqual(self._cls("name or service not known"), FAIL_UNREACHABLE)


# --------------------------------------------------------------------------- #
# 2. Supervisor state machine
# --------------------------------------------------------------------------- #

class SupervisorStateMachineTests(unittest.TestCase):
    """ProviderSupervisor transitions: healthy → degraded → recovered."""

    def test_initial_state_healthy(self) -> None:
        sup = _make_supervisor()
        try:
            state = sup.get_state()
            self.assertEqual(state["preferred"], "xai")
            self.assertEqual(state["active"], "xai")
            self.assertFalse(state["degraded"])
            self.assertIsNone(state["reason"])
            self.assertIsNone(state["since"])
        finally:
            sup.shutdown()

    def test_report_failure_marks_degraded(self) -> None:
        degraded_calls: list[dict] = []
        sup = _make_supervisor(on_degraded=degraded_calls.append)
        try:
            sup.report_failure(FAIL_UNREACHABLE)
            state = sup.get_state()
            self.assertTrue(state["degraded"])
            self.assertEqual(state["active"], "faster-whisper")
            self.assertEqual(state["reason"], FAIL_UNREACHABLE)
            self.assertIsNotNone(state["since"])
        finally:
            sup.shutdown()
        self.assertEqual(len(degraded_calls), 1)
        self.assertEqual(degraded_calls[0]["reason"], FAIL_UNREACHABLE)

    def test_report_failure_fires_on_degraded_only_once(self) -> None:
        degraded_calls: list[dict] = []
        sup = _make_supervisor(on_degraded=degraded_calls.append)
        try:
            sup.report_failure(FAIL_UNREACHABLE)
            sup.report_failure(FAIL_UNREACHABLE)  # second call — no new event
        finally:
            sup.shutdown()
        self.assertEqual(len(degraded_calls), 1)

    def test_report_success_recovers(self) -> None:
        recovered_calls: list[dict] = []
        sup = _make_supervisor(on_recovered=recovered_calls.append)
        try:
            sup.report_failure(FAIL_UNREACHABLE)
            sup.report_success()
            state = sup.get_state()
            self.assertFalse(state["degraded"])
            self.assertEqual(state["active"], "xai")
            self.assertIsNone(state["reason"])
        finally:
            sup.shutdown()
        self.assertEqual(len(recovered_calls), 1)

    def test_report_success_when_healthy_is_noop(self) -> None:
        recovered_calls: list[dict] = []
        sup = _make_supervisor(on_recovered=recovered_calls.append)
        try:
            sup.report_success()  # never degraded
        finally:
            sup.shutdown()
        self.assertEqual(recovered_calls, [])

    def test_is_degraded_reflects_state(self) -> None:
        sup = _make_supervisor()
        try:
            self.assertFalse(sup.is_degraded())
            sup.report_failure(FAIL_AUTH)
            self.assertTrue(sup.is_degraded())
            sup.report_success()
            self.assertFalse(sup.is_degraded())
        finally:
            sup.shutdown()

    def test_set_preferred_to_local_clears_degraded(self) -> None:
        sup = _make_supervisor()
        try:
            sup.report_failure(FAIL_UNREACHABLE)
            self.assertTrue(sup.is_degraded())
            sup.set_preferred("faster-whisper")
            self.assertFalse(sup.is_degraded())
            state = sup.get_state()
            self.assertEqual(state["active"], "faster-whisper")
        finally:
            sup.shutdown()

    def test_local_preferred_ignores_failure(self) -> None:
        sup = ProviderSupervisor("faster-whisper", probe_fn=_probe_always_fail)
        try:
            sup.report_failure(FAIL_AUTH)
            self.assertFalse(sup.is_degraded())  # local is always healthy
        finally:
            sup.shutdown()

    def test_failure_class_upgrade(self) -> None:
        sup = _make_supervisor()
        try:
            sup.report_failure(FAIL_UNREACHABLE)  # initial class
            sup.report_failure(FAIL_RATE_LIMIT)    # upgrade
            state = sup.get_state()
            self.assertEqual(state["reason"], FAIL_RATE_LIMIT)
        finally:
            sup.shutdown()

    def test_no_downgrade_on_repeated_failure(self) -> None:
        sup = _make_supervisor()
        try:
            sup.report_failure(FAIL_AUTH)        # most severe
            sup.report_failure(FAIL_UNREACHABLE) # should not downgrade
            self.assertEqual(sup.get_state()["reason"], FAIL_AUTH)
        finally:
            sup.shutdown()

    def test_thread_safety(self) -> None:
        """Concurrent report_failure / report_success must not raise."""
        errors: list[Exception] = []
        sup = _make_supervisor()
        try:
            def worker(i: int) -> None:
                try:
                    for _ in range(50):
                        if i % 2:
                            sup.report_failure(FAIL_UNREACHABLE)
                        else:
                            sup.report_success()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sup.shutdown()
        self.assertEqual(errors, [])


# --------------------------------------------------------------------------- #
# 3. Backoff schedule
# --------------------------------------------------------------------------- #

class BackoffTests(unittest.TestCase):
    """_backoff_delay returns correct delays per class and attempt."""

    def test_auth_returns_none(self) -> None:
        self.assertIsNone(_backoff_delay(FAIL_AUTH, 0))
        self.assertIsNone(_backoff_delay(FAIL_AUTH, 5))

    def test_unreachable_initial(self) -> None:
        self.assertAlmostEqual(_backoff_delay(FAIL_UNREACHABLE, 0), 5.0)

    def test_unreachable_grows(self) -> None:
        d0 = _backoff_delay(FAIL_UNREACHABLE, 0)
        d1 = _backoff_delay(FAIL_UNREACHABLE, 1)
        d2 = _backoff_delay(FAIL_UNREACHABLE, 2)
        self.assertGreater(d1, d0)
        self.assertGreater(d2, d1)

    def test_unreachable_caps_at_120(self) -> None:
        d = _backoff_delay(FAIL_UNREACHABLE, 100)
        self.assertLessEqual(d, 120.0)

    def test_rate_limit_starts_at_60(self) -> None:
        self.assertAlmostEqual(_backoff_delay(FAIL_RATE_LIMIT, 0), 60.0)

    def test_budget_caps_at_1800(self) -> None:
        d = _backoff_delay(FAIL_BUDGET, 100)
        self.assertLessEqual(d, 1800.0)

    def test_unknown_class_uses_unreachable_schedule(self) -> None:
        d = _backoff_delay("something-weird", 0)
        self.assertAlmostEqual(d, 5.0)  # falls back to unreachable


# --------------------------------------------------------------------------- #
# 4. Recovery probe and timer
# --------------------------------------------------------------------------- #

class RecoveryProbeTests(unittest.TestCase):
    """Probe fires after delay, clears degraded, fires on_recovered."""

    def test_probe_fires_on_schedule(self) -> None:
        probe_called = threading.Event()
        recovered_calls: list[dict] = []

        def _probe() -> bool:
            probe_called.set()
            return True  # immediately healthy

        sup = ProviderSupervisor(
            "xai",
            probe_fn=_probe,
            on_recovered=recovered_calls.append,
        )
        try:
            sup.report_failure(FAIL_UNREACHABLE)
            # first probe scheduled at 5s — too long for a test.
            # probe_now() cancels the timer and fires immediately.
            sup.probe_now()
            ok = probe_called.wait(timeout=3.0)
        finally:
            sup.shutdown()

        self.assertTrue(ok, "probe was never called")
        # Give callbacks a moment to fire
        time.sleep(0.05)
        self.assertEqual(len(recovered_calls), 1)
        self.assertFalse(recovered_calls[0]["degraded"])

    def test_probe_now_is_noop_when_healthy(self) -> None:
        probe_called = [False]

        def _probe() -> bool:
            probe_called[0] = True
            return True

        sup = ProviderSupervisor("xai", probe_fn=_probe)
        try:
            sup.probe_now()  # not degraded → noop
            time.sleep(0.1)
        finally:
            sup.shutdown()
        self.assertFalse(probe_called[0])

    def test_probe_now_noop_for_auth(self) -> None:
        """Auth failures don't trigger automatic probes."""
        probe_called = [False]

        def _probe() -> bool:
            probe_called[0] = True
            return True

        sup = ProviderSupervisor("xai", probe_fn=_probe)
        try:
            sup.report_failure(FAIL_AUTH)
            sup.probe_now()  # auth → skip
            time.sleep(0.1)
        finally:
            sup.shutdown()
        self.assertFalse(probe_called[0])

    def test_failing_probe_increments_attempt(self) -> None:
        """A failed probe reschedules with higher backoff."""
        probe_count = [0]
        done = threading.Event()

        def _probe() -> bool:
            probe_count[0] += 1
            if probe_count[0] >= 2:
                done.set()
            return False  # always fail

        # Patch _backoff_delay to return a tiny delay so the test is fast
        with patch(
            "dictate.provider_supervisor._backoff_delay",
            return_value=0.05,
        ):
            sup = ProviderSupervisor("xai", probe_fn=_probe)
            try:
                sup.report_failure(FAIL_UNREACHABLE)
                sup.probe_now()
                done.wait(timeout=2.0)
            finally:
                sup.shutdown()

        self.assertGreaterEqual(probe_count[0], 2)

    def test_shutdown_cancels_timer(self) -> None:
        probe_called = [False]

        def _slow_probe() -> bool:
            probe_called[0] = True
            return True

        with patch("dictate.provider_supervisor._backoff_delay", return_value=10.0):
            sup = ProviderSupervisor("xai", probe_fn=_slow_probe)
            sup.report_failure(FAIL_UNREACHABLE)
            sup.shutdown()  # cancels the timer
            time.sleep(0.1)  # give any leaked timer a chance to fire
        self.assertFalse(probe_called[0])


# --------------------------------------------------------------------------- #
# 5. Fail-fast dictate: engine falls back + marks degraded
# --------------------------------------------------------------------------- #

class FailFastDictateTests(unittest.TestCase):
    """Quick dictate: one remote attempt → local fallback → supervisor degraded."""

    def _make_online_engine(self, raises: Exception) -> DictationEngine:
        stt = MagicMock()
        stt.backend_name = "xai"
        stt.capabilities = MagicMock(
            supports_hotwords=False,
            supports_prompt_bias=False,
            supports_streaming_chunks=False,
        )
        stt.transcribe.side_effect = raises
        engine = DictationEngine(stt=stt, sample_rate=16000)
        engine.min_duration_s = 0
        return engine

    def test_auth_failure_reports_auth_to_supervisor(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)
        degraded_calls: list[dict] = []
        sup = _make_supervisor(on_degraded=degraded_calls.append)
        try:
            engine = self._make_online_engine(RuntimeError("HTTP 401 unauthorized"))
            engine.health_sink = lambda h, r: (
                sup.report_success() if h else sup.report_failure(r or FAIL_UNREACHABLE)
            )
            # Engine falls back to CPU but that's fine for this test —
            # we just want to confirm the supervisor is notified.
            # (CPU fallback will fail too since no faster-whisper in tests,
            #  but the health_sink is called before the fallback attempt.)
            try:
                engine.transcribe(audio)
            except Exception:  # noqa: BLE001
                pass
            self.assertTrue(sup.is_degraded())
            self.assertEqual(sup.get_state()["reason"], FAIL_AUTH)
        finally:
            sup.shutdown()
        self.assertEqual(len(degraded_calls), 1)

    def test_rate_limit_failure_marks_degraded(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)
        sup = _make_supervisor()
        try:
            engine = self._make_online_engine(RuntimeError("HTTP 429 too many requests"))
            engine.health_sink = lambda h, r: (
                sup.report_success() if h else sup.report_failure(r or FAIL_UNREACHABLE)
            )
            try:
                engine.transcribe(audio)
            except Exception:  # noqa: BLE001
                pass
            self.assertEqual(sup.get_state()["reason"], FAIL_RATE_LIMIT)
        finally:
            sup.shutdown()

    def test_unreachable_failure_marks_degraded(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)
        sup = _make_supervisor()
        try:
            engine = self._make_online_engine(ConnectionError("timeout"))
            engine.health_sink = lambda h, r: (
                sup.report_success() if h else sup.report_failure(r or FAIL_UNREACHABLE)
            )
            try:
                engine.transcribe(audio)
            except Exception:  # noqa: BLE001
                pass
            self.assertEqual(sup.get_state()["reason"], FAIL_UNREACHABLE)
        finally:
            sup.shutdown()

    def test_success_clears_degraded(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)
        recovered: list[dict] = []
        sup = _make_supervisor(on_recovered=recovered.append)
        try:
            # Degrade first
            sup.report_failure(FAIL_UNREACHABLE)
            # Now engine succeeds
            stt = MagicMock()
            stt.backend_name = "xai"
            stt.capabilities = MagicMock(supports_hotwords=False, supports_prompt_bias=False)
            stt.transcribe.return_value = "hello"
            engine = DictationEngine(stt=stt, sample_rate=16000)
            engine.min_duration_s = 0
            engine.health_sink = lambda h, r: (
                sup.report_success() if h else sup.report_failure(r or FAIL_UNREACHABLE)
            )
            engine.transcribe(audio)
            self.assertFalse(sup.is_degraded())
        finally:
            sup.shutdown()
        self.assertEqual(len(recovered), 1)


# --------------------------------------------------------------------------- #
# 6. Long-recording retry-then-degrade
# --------------------------------------------------------------------------- #

class LongRecordingRetryTests(unittest.TestCase):
    """Note recordings: retry remote before degrading to local."""

    def _make_daemon_with_supervisor(self, stt, supervisor=None):
        from dictate.daemon import Daemon
        output = MagicMock()
        output.name = "mock"
        return Daemon(
            stt,
            output=output,
            supervisor=supervisor,
        ), output

    def test_note_recording_retries_remote_before_degrading(self) -> None:
        """When remote fails for a note recording, daemon retries bounded times."""
        call_count = [0]

        stt = MagicMock()
        stt.backend_name = "xai"
        stt.capabilities = MagicMock(
            supports_hotwords=False,
            supports_prompt_bias=False,
            supports_streaming_chunks=False,
        )

        def _always_fail(*args, **kwargs) -> str:
            call_count[0] += 1
            raise RuntimeError("connection failed")

        # Note recordings use diarize=True → engine calls transcribe_diarized
        stt.transcribe.side_effect = _always_fail
        stt.transcribe_diarized.side_effect = _always_fail

        degraded_events: list[dict] = []
        sup = _make_supervisor(on_degraded=degraded_events.append)
        try:
            from dictate.daemon import _LONG_RECORDING_MAX_RETRIES
            daemon, _ = self._make_daemon_with_supervisor(stt, supervisor=sup)
            daemon.engine.min_duration_s = 0
            # Wire supervisor as health_sink
            daemon.engine.health_sink = lambda h, r: (
                sup.report_success() if h else sup.report_failure(r or FAIL_UNREACHABLE)
            )

            # Manually drive a note recording session
            recording_id = 1
            daemon._recording_stt_ids[recording_id] = id(daemon.engine.stt)
            daemon._recording_parts[recording_id] = []
            daemon._recording_modes[recording_id] = "note"

            audio = np.zeros(16000, dtype=np.float32)
            with patch("time.sleep"):  # skip actual backoff sleeps in tests
                result = daemon._transcribe_recording_audio(recording_id, audio)
        finally:
            sup.shutdown()

        # Should have been called MAX_RETRIES+1 times (initial + retries)
        self.assertGreaterEqual(call_count[0], _LONG_RECORDING_MAX_RETRIES + 1)
        # Supervisor should be degraded after all retries exhausted
        self.assertTrue(len(degraded_events) >= 1 or sup.is_degraded())

    def test_note_recording_succeeds_on_retry(self) -> None:
        """If first remote attempt fails but second succeeds, no degradation."""
        call_count = [0]

        stt = MagicMock()
        stt.backend_name = "xai"
        stt.capabilities = MagicMock(
            supports_hotwords=False,
            supports_prompt_bias=False,
            supports_streaming_chunks=False,
        )

        def _fail_then_succeed(*args, **kwargs) -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("transient error")
            return "hello from retry"

        # Note recordings use transcribe_diarized when available
        stt.transcribe_diarized.side_effect = _fail_then_succeed
        stt.transcribe.side_effect = _fail_then_succeed

        degraded_events: list[dict] = []
        sup = _make_supervisor(on_degraded=degraded_events.append)
        try:
            daemon, _ = self._make_daemon_with_supervisor(stt, supervisor=sup)
            daemon.engine.min_duration_s = 0
            daemon.engine.health_sink = lambda h, r: (
                sup.report_success() if h else sup.report_failure(r or FAIL_UNREACHABLE)
            )

            recording_id = 1
            daemon._recording_stt_ids[recording_id] = id(daemon.engine.stt)
            daemon._recording_parts[recording_id] = []
            daemon._recording_modes[recording_id] = "note"

            audio = np.zeros(16000, dtype=np.float32)
            with patch("time.sleep"):
                result = daemon._transcribe_recording_audio(recording_id, audio)
        finally:
            sup.shutdown()

        # Second call succeeded — no degradation
        self.assertEqual(degraded_events, [])
        self.assertFalse(sup.is_degraded())
        # Result should be ok
        self.assertEqual(result.status, "ok")
        self.assertIn("hello", str(result.text))

    def test_degraded_session_uses_local_transcription(self) -> None:
        """If supervisor is already degraded, recording goes straight to local."""
        remote_calls = [0]

        stt = MagicMock()
        stt.backend_name = "xai"
        stt.capabilities = MagicMock(
            supports_hotwords=False,
            supports_prompt_bias=False,
            supports_streaming_chunks=False,
        )

        def _remote_fail(*args, **kwargs) -> str:
            remote_calls[0] += 1
            raise RuntimeError("should not be called when degraded")

        stt.transcribe.side_effect = _remote_fail

        sup = _make_supervisor()
        try:
            sup.report_failure(FAIL_UNREACHABLE)  # Pre-degrade
            self.assertTrue(sup.is_degraded())

            daemon, _ = self._make_daemon_with_supervisor(stt, supervisor=sup)
            daemon.engine.min_duration_s = 0

            recording_id = 1
            daemon._recording_stt_ids[recording_id] = id(daemon.engine.stt)
            daemon._recording_parts[recording_id] = []
            daemon._recording_modes[recording_id] = "dictation"

            audio = np.zeros(16000, dtype=np.float32)
            # engine.transcribe_local() will try to load faster-whisper/base;
            # it will fail in the test environment (no model), returning status="error".
            result = daemon._transcribe_recording_audio(recording_id, audio)
        finally:
            sup.shutdown()

        # Remote STT was NOT called (degraded path goes straight to local)
        self.assertEqual(remote_calls[0], 0)


# --------------------------------------------------------------------------- #
# 7. getState / SSE contract via UiBackend
# --------------------------------------------------------------------------- #

class GetStateSseContractTests(unittest.TestCase):
    """connect_supervisor wires SSE events and enriches get_state providerHealth."""

    def _write_config(self, path: Path, stt_backend: str) -> None:
        import yaml
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump({"stt_backend": stt_backend}))

    def _backend(self, temp_dir: str, stt_backend: str = "xai"):
        from dictate.api_keys import ApiKeyStatus
        from dictate.history import HistoryStore
        from dictate.ui_server import EventBroker, UiBackend, UiPrefsStore
        from dictate.update_status import UpdateFlow, UpdateStatus
        from dictate.version import RELEASE_VERSION

        base = Path(temp_dir)
        cfg_path = base / "config.yaml"
        self._write_config(cfg_path, stt_backend)
        broker = EventBroker()
        backend = UiBackend(
            config_path=cfg_path,
            history_store=HistoryStore(base / "history.json"),
            prefs_store=UiPrefsStore(base / "prefs.json"),
            broker=broker,
            save_api_key=lambda b, k: None,
            clear_api_key=lambda b: None,
            api_key_status=lambda b, **kw: ApiKeyStatus(backend=b, status="None"),
            validate_api_key_format=lambda b, k: None,
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
        return backend, broker

    def test_get_state_includes_supervisor_fields_when_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self._backend(d, "xai")
            sup = ProviderSupervisor("xai", probe_fn=_probe_always_fail)
            try:
                backend.connect_supervisor(sup)
                import dictate.api_keys as ak_mod
                orig = ak_mod.has_stored_api_key
                try:
                    ak_mod.has_stored_api_key = lambda b: True
                    ph = backend.get_state()["providerHealth"]
                finally:
                    ak_mod.has_stored_api_key = orig
            finally:
                sup.shutdown()

        self.assertIn("preferred", ph)
        self.assertIn("active", ph)
        self.assertIn("degraded", ph)
        self.assertIn("reason", ph)
        self.assertIn("since", ph)
        # healthy initially
        self.assertTrue(ph["healthy"])
        self.assertFalse(ph["degraded"])
        self.assertEqual(ph["preferred"], "xai")
        self.assertEqual(ph["active"], "xai")

    def test_get_state_reflects_degraded_supervisor(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self._backend(d, "xai")
            sup = ProviderSupervisor("xai", probe_fn=_probe_always_fail)
            try:
                backend.connect_supervisor(sup)
                sup.report_failure(FAIL_AUTH)
                import dictate.api_keys as ak_mod
                orig = ak_mod.has_stored_api_key
                try:
                    ak_mod.has_stored_api_key = lambda b: True
                    ph = backend.get_state()["providerHealth"]
                finally:
                    ak_mod.has_stored_api_key = orig
            finally:
                sup.shutdown()

        self.assertFalse(ph["healthy"])
        self.assertTrue(ph["degraded"])
        self.assertEqual(ph["reason"], FAIL_AUTH)
        self.assertEqual(ph["active"], "faster-whisper")
        self.assertIsNotNone(ph["since"])

    def test_provider_degraded_sse_event_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend, broker = self._backend(d, "xai")
            q = broker.subscribe()
            sup = ProviderSupervisor("xai", probe_fn=_probe_always_fail)
            try:
                backend.connect_supervisor(sup)
                sup.report_failure(FAIL_RATE_LIMIT)
            finally:
                sup.shutdown()

        event = q.get_nowait()
        self.assertEqual(event["type"], "provider-degraded")
        self.assertEqual(event["reason"], FAIL_RATE_LIMIT)
        self.assertEqual(event["active"], "faster-whisper")
        self.assertEqual(event["preferred"], "xai")
        self.assertIsNotNone(event["since"])

    def test_provider_recovered_sse_event_emitted(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            backend, broker = self._backend(d, "xai")
            q = broker.subscribe()
            sup = ProviderSupervisor("xai", probe_fn=_probe_always_fail)
            try:
                backend.connect_supervisor(sup)
                sup.report_failure(FAIL_UNREACHABLE)
                # Drain the degraded event
                q.get_nowait()
                # Now recover
                sup.report_success()
            finally:
                sup.shutdown()

        event = q.get_nowait()
        self.assertEqual(event["type"], "provider-recovered")
        self.assertEqual(event["preferred"], "xai")
        self.assertEqual(event["active"], "xai")

    def test_get_state_backward_compat_fields_present(self) -> None:
        """The legacy healthy/status/mode fields must still be present."""
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self._backend(d, "xai")
            sup = ProviderSupervisor("xai", probe_fn=_probe_always_fail)
            try:
                backend.connect_supervisor(sup)
                import dictate.api_keys as ak_mod
                orig = ak_mod.has_stored_api_key
                try:
                    ak_mod.has_stored_api_key = lambda b: True
                    ph = backend.get_state()["providerHealth"]
                finally:
                    ak_mod.has_stored_api_key = orig
            finally:
                sup.shutdown()

        self.assertIn("healthy", ph)
        self.assertIn("status", ph)
        self.assertIn("mode", ph)

    def test_get_state_no_supervisor_still_has_new_fields(self) -> None:
        """get_state always returns preferred/active/degraded/reason/since."""
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self._backend(d, "xai")
            import dictate.api_keys as ak_mod
            orig = ak_mod.has_stored_api_key
            try:
                ak_mod.has_stored_api_key = lambda b: True
                ph = backend.get_state()["providerHealth"]
            finally:
                ak_mod.has_stored_api_key = orig

        self.assertIn("preferred", ph)
        self.assertIn("active", ph)
        self.assertIn("degraded", ph)
        self.assertIn("reason", ph)
        self.assertIn("since", ph)

    def test_private_mode_always_healthy_with_supervisor(self) -> None:
        """faster-whisper preferred → always healthy, supervisor not degraded."""
        with tempfile.TemporaryDirectory() as d:
            backend, _ = self._backend(d, "faster-whisper")
            sup = ProviderSupervisor("faster-whisper", probe_fn=_probe_always_fail)
            try:
                backend.connect_supervisor(sup)
                ph = backend.get_state()["providerHealth"]
            finally:
                sup.shutdown()

        self.assertTrue(ph["healthy"])
        self.assertEqual(ph["mode"], "private")


# --------------------------------------------------------------------------- #
# 8. upgrade_failure_class utility
# --------------------------------------------------------------------------- #

class UpgradeFailureClassTests(unittest.TestCase):
    def test_upgrades_from_none(self) -> None:
        self.assertEqual(_upgrade_failure_class(None, FAIL_AUTH), FAIL_AUTH)

    def test_upgrades_unreachable_to_rate_limit(self) -> None:
        self.assertEqual(
            _upgrade_failure_class(FAIL_UNREACHABLE, FAIL_RATE_LIMIT), FAIL_RATE_LIMIT
        )

    def test_does_not_downgrade_auth(self) -> None:
        self.assertEqual(
            _upgrade_failure_class(FAIL_AUTH, FAIL_UNREACHABLE), FAIL_AUTH
        )

    def test_same_class_stays(self) -> None:
        self.assertEqual(
            _upgrade_failure_class(FAIL_RATE_LIMIT, FAIL_RATE_LIMIT), FAIL_RATE_LIMIT
        )


if __name__ == "__main__":
    unittest.main()
