from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from dictate.hotkey_backend import (
    HotkeyBackendUnavailableError,
    PynputHotkeyBackend,
    _HotkeyCallbacks,
    _portal_trigger,
    detect_hotkey_backend,
)


class HotkeyBackendSelectionTests(unittest.TestCase):
    def test_wayland_prefers_portal_backend(self) -> None:
        with patch("dictate.hotkey_backend.detect_session_type", return_value="wayland"):
            with patch("dictate.hotkey_backend.evdev_available", return_value=False):
                with patch("dictate.hotkey_backend.portal_global_shortcuts_available", return_value=True):
                    with patch("dictate.hotkey_backend.pynput_available", return_value=True):
                        self.assertEqual(detect_hotkey_backend(), "portal")

    def test_evdev_backend_wins_when_available(self) -> None:
        with patch("dictate.hotkey_backend.detect_session_type", return_value="wayland"):
            with patch("dictate.hotkey_backend.evdev_available", return_value=True):
                with patch("dictate.hotkey_backend.portal_global_shortcuts_available", return_value=True):
                    with patch("dictate.hotkey_backend.pynput_available", return_value=True):
                        self.assertEqual(detect_hotkey_backend(), "evdev")

    def test_x11_uses_pynput_backend(self) -> None:
        with patch("dictate.hotkey_backend.detect_session_type", return_value="x11"):
            with patch("dictate.hotkey_backend.evdev_available", return_value=False):
                with patch("dictate.hotkey_backend.portal_global_shortcuts_available", return_value=True):
                    with patch("dictate.hotkey_backend.pynput_available", return_value=True):
                        self.assertEqual(detect_hotkey_backend(), "pynput")

    def test_wayland_without_portal_raises(self) -> None:
        with patch("dictate.hotkey_backend.detect_session_type", return_value="wayland"):
            with patch("dictate.hotkey_backend.evdev_available", return_value=False):
                with patch("dictate.hotkey_backend.portal_global_shortcuts_available", return_value=False):
                    with patch("dictate.hotkey_backend.pynput_available", return_value=False):
                        with self.assertRaises(HotkeyBackendUnavailableError):
                            detect_hotkey_backend()

    def test_portal_trigger_formats_combo(self) -> None:
        self.assertEqual(_portal_trigger("ctrl+space"), "CTRL+space")
        self.assertEqual(_portal_trigger("ctrl+shift+r"), "CTRL+SHIFT+r")

    def test_portal_trigger_formats_side_specific_single_modifier_keys(self) -> None:
        self.assertEqual(_portal_trigger("ctrl_l"), "Control_L")
        self.assertEqual(_portal_trigger("ctrl_r"), "Control_R")


class _FakeListener:
    def __init__(self, *, on_press, on_release) -> None:  # noqa: ANN001
        self.on_press = on_press
        self.on_release = on_release
        self.alive = False
        self.stopped = False

    def start(self) -> None:
        self.alive = True

    def stop(self) -> None:
        self.alive = False
        self.stopped = True

    def is_alive(self) -> bool:
        return self.alive


class _FakeKeyboard:
    def __init__(self) -> None:
        self.listeners: list[_FakeListener] = []

    def Listener(self, *, on_press, on_release) -> _FakeListener:  # noqa: ANN001, N802
        listener = _FakeListener(on_press=on_press, on_release=on_release)
        self.listeners.append(listener)
        return listener


class _Key:
    def __init__(self, name: str) -> None:
        self.name = name


def _wait_until(predicate, timeout: float = 2.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class PynputListenerRecoveryTests(unittest.TestCase):
    def _backend(self, released: threading.Event) -> tuple[PynputHotkeyBackend, _FakeKeyboard]:
        keyboard = _FakeKeyboard()
        pynput = type("pynput", (), {"keyboard": keyboard})
        with patch.dict("sys.modules", {"pynput": pynput}):
            backend = PynputHotkeyBackend(
                combo="ctrl_r",
                callbacks=_HotkeyCallbacks(on_press=lambda: None, on_release=released.set),
            )
        backend._POLL_INTERVAL = 0.01
        backend._RESTART_DELAY_MIN = 0.01
        backend._RESTART_DELAY_MAX = 0.05
        self.addCleanup(backend.stop)
        return backend, keyboard

    def test_dead_listener_is_restarted(self) -> None:
        backend, keyboard = self._backend(threading.Event())
        backend.start()
        keyboard.listeners[0].alive = False  # display connection dropped

        self.assertTrue(_wait_until(lambda: len(keyboard.listeners) == 2))
        self.assertTrue(keyboard.listeners[1].is_alive())

    def test_recording_in_progress_is_released_when_listener_dies(self) -> None:
        released = threading.Event()
        backend, keyboard = self._backend(released)
        backend.start()
        keyboard.listeners[0].on_press(_Key("ctrl_r"))
        keyboard.listeners[0].alive = False

        self.assertTrue(released.wait(2.0))

    def test_stop_does_not_restart_listener(self) -> None:
        backend, keyboard = self._backend(threading.Event())
        backend.start()
        backend.stop()
        time.sleep(0.1)

        self.assertEqual(len(keyboard.listeners), 1)
        self.assertTrue(keyboard.listeners[0].stopped)


if __name__ == "__main__":
    unittest.main()
