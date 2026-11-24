from __future__ import annotations

import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from dictate.hotkey_backend import (
    EvdevHotkeyBackend,
    HotkeyBackendUnavailableError,
    PynputHotkeyBackend,
    _HotkeyCallbacks,
    _portal_trigger,
    detect_hotkey_backend,
)


def _wait_until(predicate, timeout: float = 3.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class _FakeListener(threading.Thread):
    """Stands in for pynput's listener: a thread that runs until stopped or killed."""

    instances: list[_FakeListener] = []

    def __init__(self, *, on_press, on_release) -> None:  # noqa: ANN001
        super().__init__(daemon=True)
        self.on_press = on_press
        self.on_release = on_release
        self.lost = threading.Event()
        _FakeListener.instances.append(self)

    def run(self) -> None:
        self.lost.wait()

    def stop(self) -> None:
        self.lost.set()


class _FakeInputDevice:
    instances: list[_FakeInputDevice] = []
    events_by_path: dict[str, list[object]] = {}

    def __init__(self, path: str) -> None:
        self.path = path
        self.events = _FakeInputDevice.events_by_path.get(path, [])
        self.unplugged = threading.Event()
        _FakeInputDevice.instances.append(self)

    def read_loop(self):  # noqa: ANN201
        yield from self.events
        self.unplugged.wait()
        raise OSError(19, "No such device")

    def close(self) -> None:
        self.unplugged.set()


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



@patch("dictate.hotkey_backend.LISTENER_POLL_SECONDS", 0.01)
@patch("dictate.hotkey_backend.RESTART_BACKOFF_SECONDS", (0.01,))
class PynputReattachTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeListener.instances = []
        fake_pynput = types.ModuleType("pynput")
        fake_pynput.keyboard = types.SimpleNamespace(Listener=_FakeListener)
        patcher = patch.dict(sys.modules, {"pynput": fake_pynput})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events: list[str] = []
        self.backend = PynputHotkeyBackend(
            combo="ctrl_r",
            callbacks=_HotkeyCallbacks(
                on_press=lambda: self.events.append("press"),
                on_release=lambda: self.events.append("release"),
            ),
        )
        self.addCleanup(self.backend.stop)

    def test_lost_display_connection_starts_a_new_listener(self) -> None:
        self.backend.start()
        first = _FakeListener.instances[0]
        first.on_press(_key("ctrl_r"))

        first.lost.set()  # The X server went away.

        self.assertTrue(_wait_until(lambda: len(_FakeListener.instances) == 2))
        second = _FakeListener.instances[1]
        self.assertTrue(_wait_until(second.is_alive))
        # The held key never sends a release on the dead connection.
        self.assertEqual(self.events, ["press", "release"])
        second.on_press(_key("ctrl_r"))
        second.on_release(_key("ctrl_r"))
        self.assertEqual(self.events, ["press", "release", "press", "release"])

    def test_stop_does_not_reattach(self) -> None:
        self.backend.start()
        self.backend.stop()
        time.sleep(0.1)
        self.assertEqual(len(_FakeListener.instances), 1)


@patch("dictate.hotkey_backend.DEVICE_RESCAN_SECONDS", 0.01)
class EvdevReattachTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeInputDevice.instances = []
        _FakeInputDevice.events_by_path = {}
        fake_evdev = types.ModuleType("evdev")
        fake_evdev.InputDevice = _FakeInputDevice
        fake_evdev.ecodes = types.SimpleNamespace(EV_KEY=1, KEY={97: "KEY_RIGHTCTRL"})
        patcher = patch.dict(sys.modules, {"evdev": fake_evdev})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.paths = ["/dev/input/event8"]
        paths_patcher = patch(
            "dictate.hotkey_backend._keyboard_device_paths", side_effect=lambda: list(self.paths)
        )
        paths_patcher.start()
        self.addCleanup(paths_patcher.stop)
        self.events: list[str] = []
        self.backend = EvdevHotkeyBackend(
            combo="ctrl_r",
            callbacks=_HotkeyCallbacks(
                on_press=lambda: self.events.append("press"),
                on_release=lambda: self.events.append("release"),
            ),
        )
        self.addCleanup(self.backend.stop)

    def test_keyboard_that_returns_on_a_new_node_is_read_again(self) -> None:
        self.backend.start()
        first = _FakeInputDevice.instances[0]
        self.backend._handle_key_event("ctrl_r", 1)

        self.paths = []
        first.unplugged.set()
        self.assertTrue(_wait_until(lambda: self.events == ["press", "release"]))

        right_ctrl_tap = [
            types.SimpleNamespace(type=1, code=97, value=1),
            types.SimpleNamespace(type=1, code=97, value=0),
        ]
        _FakeInputDevice.events_by_path["/dev/input/event11"] = right_ctrl_tap
        self.paths = ["/dev/input/event11"]

        self.assertTrue(
            _wait_until(lambda: self.events == ["press", "release", "press", "release"])
        )
        self.assertEqual(_FakeInputDevice.instances[-1].path, "/dev/input/event11")


def _key(name: str) -> object:
    return types.SimpleNamespace(name=name)


if __name__ == "__main__":
    unittest.main()
