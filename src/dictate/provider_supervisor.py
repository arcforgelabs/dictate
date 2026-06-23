"""Provider resilience supervisor.

Tracks the preferred vs active STT backend, handles graceful degradation
when the remote fails, and schedules automatic recovery probes using
class-aware exponential backoff.

Design principles:
- On-device (faster-whisper) is the always-available floor.
- Remote (preferred) is the goal; switches are surfaced as SSE events.
- Recording is never hard-blocked — the supervisor only affects routing.
- No busy polling: a single timer, only while degraded, cancelled on recovery.
- Thread-safe: all mutable state is guarded by a single lock.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

# Failure reason constants (public — used in tests and the UI contract)
FAIL_AUTH = "auth"
FAIL_RATE_LIMIT = "rate-limit"
FAIL_BUDGET = "budget"
FAIL_UNREACHABLE = "unreachable"

_REMOTE_BACKENDS = {"xai", "openai", "gemini"}
_LOCAL_BACKEND = "faster-whisper"

# Class-aware backoff parameters: (initial_delay_s, multiplier, cap_s)
_BACKOFF: dict[str, tuple[float, float, float]] = {
    FAIL_UNREACHABLE: (5.0,   3.0,  120.0),   # 5 → 15 → 45 → 120 → 120 …
    FAIL_RATE_LIMIT:  (60.0,  2.0, 1800.0),   # 60 → 120 → 240 → … → 1800
    FAIL_BUDGET:      (120.0, 2.0, 1800.0),   # 120 → 240 → … → 1800
    # FAIL_AUTH: no automatic probing (key must be reconfigured)
}

_PROBE_MIN_DELAY = 0.05  # seconds — floor so threading.Timer is always used


def _backoff_delay(reason: str, attempt: int) -> float | None:
    """Return probe delay in seconds, or None if probing is paused for this class.

    ``attempt`` is 0-based (first probe after failure is attempt 0).
    """
    if reason == FAIL_AUTH:
        return None  # Don't probe until the key changes
    initial, mult, cap = _BACKOFF.get(reason, _BACKOFF[FAIL_UNREACHABLE])
    return min(initial * (mult ** attempt), cap)


class ProviderSupervisor:
    """Thread-safe supervisor for remote STT provider health.

    Owns the ``preferred`` / ``active`` pair, degradation state, and the
    recovery probe timer. Notify callbacks are called **outside** the lock
    to avoid deadlock with callers that also hold other locks.

    Parameters
    ----------
    preferred:
        The configured ``stt_backend`` (e.g. ``"xai"``).
    probe_fn:
        Lightweight callable that returns ``True`` if the remote is healthy.
        Must not block for more than a few seconds; called in a daemon thread.
    on_degraded:
        Optional callback fired once when the supervisor first degrades.
        Receives a state dict ``{preferred, active, degraded, reason, since}``.
    on_recovered:
        Optional callback fired when the supervisor recovers.
        Receives the same state dict.
    """

    def __init__(
        self,
        preferred: str,
        *,
        probe_fn: Callable[[], bool],
        on_degraded: Callable[[dict], None] | None = None,
        on_recovered: Callable[[dict], None] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._preferred = preferred
        self._active = preferred
        self._degraded = False
        self._reason: str | None = None
        self._since: str | None = None
        self._probe_fn = probe_fn
        self._on_degraded = on_degraded
        self._on_recovered = on_recovered
        self._timer: threading.Timer | None = None
        self._probe_attempt = 0
        self._stopped = False

        # Optional network-up trigger (D-Bus / NetworkManager)
        self._start_network_trigger()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def set_preferred(self, preferred: str) -> None:
        """Update the preferred backend (e.g. after a model switch in config).

        If switching to on-device, cancels any pending probe and clears
        degraded state silently (no recovery event).
        """
        with self._lock:
            old = self._preferred
            self._preferred = preferred
            if preferred == old:
                return
            if preferred == _LOCAL_BACKEND:
                # Switched to on-device: cancel probe, clear degradation
                self._cancel_timer_locked()
                self._degraded = False
                self._active = preferred
                self._reason = None
                self._since = None
                self._probe_attempt = 0

    def report_failure(self, reason: str) -> None:
        """Record a remote transcription failure.

        If this is the first failure (transition to degraded), fires
        ``on_degraded`` and schedules the first recovery probe.
        Subsequent failures while already degraded upgrade the class if
        more severe (``unreachable`` < ``rate-limit``/``budget`` < ``auth``).
        """
        notify_fn: Callable[[dict], None] | None = None
        state: dict | None = None
        delay: float | None = None

        with self._lock:
            if self._stopped or self._preferred == _LOCAL_BACKEND:
                return
            already_degraded = self._degraded
            self._degraded = True
            self._active = _LOCAL_BACKEND

            if not already_degraded:
                self._reason = reason
                self._since = datetime.now(timezone.utc).isoformat()
                self._probe_attempt = 0
                state = self._state_locked()
                notify_fn = self._on_degraded
                delay = _backoff_delay(reason, 0)
            else:
                # Upgrade to a more-severe failure class if warranted
                self._reason = _upgrade_failure_class(self._reason, reason)
                # Don't reschedule the existing probe or bump the attempt counter

        if notify_fn is not None and state is not None:
            _fire_callback(notify_fn, state)

        if delay is not None:
            self._schedule_probe(delay)

    def report_success(self) -> None:
        """Record a successful remote transcription; clear degradation.

        If recovering from degraded state, fires ``on_recovered``.
        """
        notify_fn: Callable[[dict], None] | None = None
        state: dict | None = None

        with self._lock:
            if not self._degraded:
                return
            self._degraded = False
            self._active = self._preferred
            self._reason = None
            self._since = None
            self._probe_attempt = 0
            self._cancel_timer_locked()
            state = self._state_locked()
            notify_fn = self._on_recovered

        if notify_fn is not None and state is not None:
            _fire_callback(notify_fn, state)

    def probe_now(self) -> None:
        """Trigger an immediate recovery probe (opportunistic, e.g. at capture-start).

        No-op if not degraded, preferred is on-device, or reason is ``auth``.
        Cancels any pending scheduled probe and fires immediately.
        """
        with self._lock:
            if self._stopped or not self._degraded:
                return
            if self._preferred == _LOCAL_BACKEND:
                return
            if self._reason == FAIL_AUTH:
                return  # Auth failures don't auto-recover
            self._cancel_timer_locked()

        self._schedule_probe(0.0)

    def get_state(self) -> dict:
        """Thread-safe snapshot of current supervisor state.

        Returns a dict with keys: ``preferred``, ``active``, ``degraded``,
        ``reason``, ``since``.
        """
        with self._lock:
            return self._state_locked()

    def is_degraded(self) -> bool:
        """Return whether the supervisor is currently in degraded state."""
        with self._lock:
            return self._degraded

    def shutdown(self) -> None:
        """Stop the supervisor: cancel pending timers and refuse new work."""
        with self._lock:
            self._stopped = True
            self._cancel_timer_locked()

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _state_locked(self) -> dict:
        """Build a state snapshot; must be called while holding ``_lock``."""
        return {
            "preferred": self._preferred,
            "active": self._active,
            "degraded": self._degraded,
            "reason": self._reason,
            "since": self._since,
        }

    def _cancel_timer_locked(self) -> None:
        """Cancel the pending probe timer; must be called while holding ``_lock``."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule_probe(self, delay: float) -> None:
        """Schedule a recovery probe after ``delay`` seconds.

        Must be called **without** holding ``_lock``.
        """
        actual_delay = max(_PROBE_MIN_DELAY, delay)
        timer: threading.Timer | None = None
        with self._lock:
            if self._stopped:
                return
            self._cancel_timer_locked()
            timer = threading.Timer(actual_delay, self._do_probe)
            timer.daemon = True
            self._timer = timer
        if timer is not None:
            timer.start()

    def _do_probe(self) -> None:
        """Execute the probe and handle the result."""
        with self._lock:
            if self._stopped or not self._degraded:
                self._timer = None
                return
            attempt = self._probe_attempt
            reason = self._reason or FAIL_UNREACHABLE
            self._timer = None

        # Call probe outside the lock
        try:
            ok = self._probe_fn()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Provider probe raised: %s", exc)
            ok = False

        if ok:
            self.report_success()
        else:
            next_delay: float | None = None
            with self._lock:
                if self._stopped or not self._degraded:
                    return
                self._probe_attempt = attempt + 1
                reason = self._reason or FAIL_UNREACHABLE
                next_delay = _backoff_delay(reason, attempt + 1)
            if next_delay is not None:
                self._schedule_probe(next_delay)

    def _start_network_trigger(self) -> None:
        """Spawn a background thread for the D-Bus network-up listener.

        Skip cleanly if D-Bus or GLib is not available (non-Linux, headless).
        """
        try:
            t = threading.Thread(target=self._run_network_trigger, daemon=True)
            t.start()
        except Exception:  # noqa: BLE001
            pass

    def _run_network_trigger(self) -> None:
        """Listen for NetworkManager StateChanged via D-Bus.

        Fires ``probe_now()`` when the device connects to a network
        (NM_STATE_CONNECTED_GLOBAL = 70).  Silently exits if D-Bus or
        gi.repository are unavailable.
        """
        try:
            import gi  # type: ignore[import-untyped]
            gi.require_version("GLib", "2.0")
            from gi.repository import GLib  # type: ignore[attr-defined]
            import dbus  # type: ignore[import-untyped]
            import dbus.mainloop.glib  # type: ignore[import-untyped]

            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()

            def _on_state_changed(state: int) -> None:
                _NM_STATE_CONNECTED_GLOBAL = 70
                if state == _NM_STATE_CONNECTED_GLOBAL:
                    logger.debug(
                        "Network-up trigger: NM state=%d; probing provider", state
                    )
                    self.probe_now()

            bus.add_signal_receiver(
                _on_state_changed,
                signal_name="StateChanged",
                dbus_interface="org.freedesktop.NetworkManager",
                path="/org/freedesktop/NetworkManager",
            )

            loop = GLib.MainLoop()
            loop.run()
        except Exception:  # noqa: BLE001 — D-Bus/GI unavailable; skip gracefully
            pass


# --------------------------------------------------------------------------- #
# Probe factory
# --------------------------------------------------------------------------- #


def make_remote_probe(backend: str) -> Callable[[], bool]:
    """Return a lightweight authenticated health-check callable for *backend*.

    The returned ``probe_fn`` reads the stored key on every call and does a
    real remote validation.  Returns ``True`` iff the key is present and
    accepted; ``False`` on any failure or missing key.  **Never logs the key.**

    Uses the public ``api_keys.api_key_status`` wrapper so the probe logic
    stays consistent with the rest of the key-validation stack.
    """

    def _probe() -> bool:
        try:
            from dictate import api_keys

            result = api_keys.api_key_status(backend, validate_remote=True, timeout=4)
            return result.status == "Ready"
        except Exception:  # noqa: BLE001
            return False

    return _probe


# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #

_SEVERITY = {FAIL_UNREACHABLE: 0, FAIL_RATE_LIMIT: 1, FAIL_BUDGET: 1, FAIL_AUTH: 2}


def _upgrade_failure_class(current: str | None, incoming: str) -> str:
    """Return the more severe of the two failure classes."""
    if current is None:
        return incoming
    if _SEVERITY.get(incoming, 0) > _SEVERITY.get(current, 0):
        return incoming
    return current


def _fire_callback(fn: Callable[[dict], None], state: dict) -> None:
    """Call a supervisor callback, swallowing exceptions."""
    try:
        fn(state)
    except Exception:  # noqa: BLE001
        pass
