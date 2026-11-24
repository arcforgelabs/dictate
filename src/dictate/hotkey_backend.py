"""Hotkey backend selection and runtime integrations."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dictate.hotkey import combo_is_active, key_event_names, normalize_push_to_talk_combo
from dictate.outputs import detect_session_type

PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop"
PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop"
PORTAL_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
PORTAL_REQUEST_INTERFACE = "org.freedesktop.portal.Request"
PORTAL_SESSION_INTERFACE = "org.freedesktop.portal.Session"
PORTAL_REGISTRY_INTERFACE = "org.freedesktop.host.portal.Registry"
PUSH_TO_TALK_SHORTCUT_ID = "push-to-talk"
APP_ID = "dictate"
# Wait between attempts to re-attach a lost key listener. A display server
# that restarts after a desktop crash takes some seconds to accept clients.
RESTART_BACKOFF_SECONDS = (1.0, 2.0, 5.0, 10.0)
DEVICE_RESCAN_SECONDS = 2.0
LISTENER_POLL_SECONDS = 1.0

logger = logging.getLogger(__name__)


class HotkeyBackendUnavailableError(RuntimeError):
    """Raised when no supported hotkey backend is available."""


class HotkeyBackend:
    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def set_combo(self, combo: str) -> None:
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError


@dataclass(slots=True)
class _HotkeyCallbacks:
    on_press: Callable[[], None]
    on_release: Callable[[], None]


class PynputHotkeyBackend(HotkeyBackend):
    """X11 listener that re-attaches when its display connection is lost.

    A desktop crash (for example GNOME Shell on X11) restarts the X server.
    The pynput listener thread then dies with ``ConnectionClosedError``. A
    supervisor thread starts a new listener, which connects to the new server.
    """

    def __init__(
        self,
        *,
        combo: str,
        callbacks: _HotkeyCallbacks,
    ) -> None:
        try:
            from pynput import keyboard
        except ImportError as exc:
            raise HotkeyBackendUnavailableError("pynput is not installed") from exc

        self._keyboard = keyboard
        self._callbacks = callbacks
        self._listener: keyboard.Listener | None = None
        self._supervisor: threading.Thread | None = None
        self._stop = threading.Event()
        self._pressed_key_names: set[str] = set()
        self._push_to_talk_pressed = False
        self._combo = normalize_push_to_talk_combo(combo)

    @property
    def name(self) -> str:
        return "pynput"

    def start(self) -> None:
        if self._supervisor is not None:
            return
        self._stop.clear()
        self._listener = self._new_listener()
        self._listener.start()
        self._supervisor = threading.Thread(target=self._supervise, daemon=True)
        self._supervisor.start()

    def stop(self) -> None:
        self._stop.set()
        listener = self._listener
        supervisor = self._supervisor
        self._listener = None
        self._supervisor = None
        self._pressed_key_names.clear()
        self._push_to_talk_pressed = False
        if listener is not None:
            try:
                listener.stop()
            except Exception:  # noqa: BLE001
                pass
        if supervisor is not None and supervisor is not threading.current_thread():
            supervisor.join(timeout=1.0)

    def set_combo(self, combo: str) -> None:
        self._combo = normalize_push_to_talk_combo(combo)
        self._pressed_key_names.clear()
        self._push_to_talk_pressed = False

    def _new_listener(self):  # noqa: ANN202
        return self._keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )

    def _supervise(self) -> None:
        # Poll is_alive() instead of pynput's join() and wait(): when the
        # display connection fails, pynput never marks the listener ready and
        # never fills its exception queue, so both of those block forever.
        attempt = 0
        while not self._stop.is_set():
            listener = self._listener
            while listener is not None and listener.is_alive():
                if self._stop.wait(LISTENER_POLL_SECONDS):
                    return
            if self._stop.is_set():
                return
            if attempt == 0:
                logger.warning("Key listener stopped; re-attaching to the display")
            self._release_held_key()
            delay = RESTART_BACKOFF_SECONDS[min(attempt, len(RESTART_BACKOFF_SECONDS) - 1)]
            if self._stop.wait(delay):
                return
            attempt += 1
            try:
                listener = self._new_listener()
                listener.start()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Key listener restart failed: %s", exc)
                self._listener = None
                continue
            self._listener = listener
            if not self._stop.wait(LISTENER_POLL_SECONDS) and listener.is_alive():
                logger.warning("Key listener re-attached")
                attempt = 0

    def _release_held_key(self) -> None:
        was_pressed = self._push_to_talk_pressed
        self._pressed_key_names.clear()
        self._push_to_talk_pressed = False
        if was_pressed:
            self._callbacks.on_release()

    def _on_press(self, key) -> None:  # noqa: ANN001
        self._pressed_key_names.update(key_event_names(key))
        if self._push_to_talk_pressed:
            return
        if combo_is_active(self._pressed_key_names, self._combo):
            self._push_to_talk_pressed = True
            self._callbacks.on_press()

    def _on_release(self, key) -> None:  # noqa: ANN001
        self._pressed_key_names.difference_update(key_event_names(key))
        if self._push_to_talk_pressed and not combo_is_active(
            self._pressed_key_names,
            self._combo,
        ):
            self._push_to_talk_pressed = False
            self._callbacks.on_release()


class PortalHotkeyBackend(HotkeyBackend):
    def __init__(
        self,
        *,
        combo: str,
        callbacks: _HotkeyCallbacks,
        parent_window: str = "",
    ) -> None:
        self._combo = normalize_push_to_talk_combo(combo)
        self._callbacks = callbacks
        self._parent_window = parent_window
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: Exception | None = None
        self._restart_requested = False
        self._stopping = False
        self._state_lock = threading.Lock()
        self._pressed = False
        self._context = None
        self._loop = None

    @property
    def name(self) -> str:
        return "portal"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._ready.clear()
        self._startup_error = None
        self._stopping = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=15.0)
        if self._startup_error is not None:
            thread = self._thread
            self._thread = None
            if thread is not None:
                thread.join(timeout=1.0)
            raise HotkeyBackendUnavailableError(str(self._startup_error)) from self._startup_error

    def stop(self) -> None:
        self._stopping = True
        self._request_restart(False)
        if self._context is not None and self._loop is not None:
            self._context.invoke_full(0, self._quit_loop)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._thread = None
        self._context = None
        self._loop = None
        with self._state_lock:
            self._pressed = False

    def set_combo(self, combo: str) -> None:
        self._combo = normalize_push_to_talk_combo(combo)
        running = self._thread is not None and self._thread.is_alive()
        if running:
            self.stop()
            self.start()

    def _request_restart(self, restart: bool) -> None:
        self._restart_requested = restart

    def _run(self) -> None:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import Gio, GLib
        except Exception as exc:  # noqa: BLE001
            self._startup_error = RuntimeError("PyGObject is required for portal hotkeys")
            self._ready.set()
            return

        context = GLib.MainContext()
        loop = GLib.MainLoop.new(context, False)
        self._context = context
        self._loop = loop
        context.push_thread_default()

        request_ids: list[int] = []
        portal_signal_ids: list[int] = []
        session_signal_ids: list[int] = []
        connection = None
        session_handle = ""

        try:
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            _register_host_app(connection, Gio, GLib)
            session_handle = self._create_portal_session(connection, Gio, GLib, context)
            portal_signal_ids.extend(
                self._subscribe_portal_shortcut_signals(
                    connection,
                    Gio,
                    session_handle,
                )
            )
            session_signal_ids.extend(
                self._subscribe_session_signals(
                    connection,
                    Gio,
                    session_handle,
                    loop,
                )
            )
            if not self._shortcut_exists(connection, Gio, GLib, context, session_handle):
                try:
                    self._bind_portal_shortcut(connection, Gio, GLib, context, session_handle)
                except RuntimeError as exc:
                    raise RuntimeError(
                        "no portal push-to-talk shortcut is approved yet"
                    ) from exc
        except Exception as exc:  # noqa: BLE001
            self._startup_error = exc
            self._ready.set()
            self._context = None
            self._loop = None
            context.pop_thread_default()
            return

        self._ready.set()

        while not self._stopping and not self._restart_requested:
            loop.run()

        if connection is not None:
            for subscription_id in portal_signal_ids + session_signal_ids + request_ids:
                if subscription_id:
                    connection.signal_unsubscribe(subscription_id)
            if session_handle:
                try:
                    connection.call_sync(
                        PORTAL_BUS_NAME,
                        session_handle,
                        PORTAL_SESSION_INTERFACE,
                        "Close",
                        None,
                        None,
                        Gio.DBusCallFlags.NONE,
                        -1,
                        None,
                    )
                except Exception:  # noqa: BLE001
                    pass

        context.pop_thread_default()
        self._context = None
        self._loop = None

    def _create_portal_session(self, connection, Gio, GLib, context) -> str:  # noqa: ANN001
        token = _token("session")
        options = {
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", token),
        }
        results = self._call_request_method(
            connection,
            Gio,
            GLib,
            context,
            method_name="CreateSession",
            parameters=GLib.Variant("(a{sv})", (options,)),
            token=token,
        )
        session_handle = results.get("session_handle")
        if not isinstance(session_handle, str) or not session_handle:
            raise RuntimeError("portal CreateSession did not return a session handle")
        return session_handle

    def _bind_portal_shortcut(self, connection, Gio, GLib, context, session_handle: str) -> None:  # noqa: ANN001
        token = _token("bind")
        shortcut = (
            PUSH_TO_TALK_SHORTCUT_ID,
            {
                "description": GLib.Variant("s", "Push to talk"),
                "preferred_trigger": GLib.Variant("s", _portal_trigger(self._combo)),
            },
        )
        self._call_request_method(
            connection,
            Gio,
            GLib,
            context,
            method_name="BindShortcuts",
            parameters=GLib.Variant(
                "(oa(sa{sv})sa{sv})",
                (
                    session_handle,
                    [shortcut],
                    self._parent_window,
                    {"handle_token": GLib.Variant("s", token)},
                ),
            ),
            token=token,
        )

    def _shortcut_exists(self, connection, Gio, GLib, context, session_handle: str) -> bool:  # noqa: ANN001
        token = _token("list")
        results = self._call_request_method(
            connection,
            Gio,
            GLib,
            context,
            method_name="ListShortcuts",
            parameters=GLib.Variant(
                "(oa{sv})",
                (
                    session_handle,
                    {"handle_token": GLib.Variant("s", token)},
                ),
            ),
            token=token,
        )
        shortcuts = results.get("shortcuts")
        if not isinstance(shortcuts, list):
            return False
        for item in shortcuts:
            if isinstance(item, tuple) and len(item) >= 1 and item[0] == PUSH_TO_TALK_SHORTCUT_ID:
                return True
        return False

    def _call_request_method(
        self,
        connection,  # noqa: ANN001
        Gio,  # noqa: ANN001
        GLib,  # noqa: ANN001
        context,  # noqa: ANN001
        *,
        method_name: str,
        parameters,
        token: str,
    ) -> dict:
        sender_path = connection.get_unique_name()[1:].replace(".", "_")
        expected_request_path = (
            f"/org/freedesktop/portal/desktop/request/{sender_path}/{token}"
        )
        result_holder: dict[str, object] = {"done": False}
        wait_loop = GLib.MainLoop.new(context, False)

        def on_response(_connection, _sender_name, _object_path, _interface_name, _signal_name, params):  # noqa: ANN001
            response_code, results = params.unpack()
            result_holder["done"] = True
            result_holder["response_code"] = response_code
            result_holder["results"] = results
            wait_loop.quit()

        subscription_id = connection.signal_subscribe(
            PORTAL_BUS_NAME,
            PORTAL_REQUEST_INTERFACE,
            "Response",
            expected_request_path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_response,
        )
        try:
            response = connection.call_sync(
                PORTAL_BUS_NAME,
                PORTAL_OBJECT_PATH,
                PORTAL_INTERFACE,
                method_name,
                parameters,
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            request_path = response.unpack()[0]
            if request_path != expected_request_path:
                connection.signal_unsubscribe(subscription_id)
                subscription_id = connection.signal_subscribe(
                    PORTAL_BUS_NAME,
                    PORTAL_REQUEST_INTERFACE,
                    "Response",
                    request_path,
                    None,
                    Gio.DBusSignalFlags.NONE,
                    on_response,
                )
            while not result_holder["done"]:
                wait_loop.run()
        finally:
            connection.signal_unsubscribe(subscription_id)

        response_code = result_holder.get("response_code")
        if response_code != 0:
            raise RuntimeError(f"portal {method_name} failed with response code {response_code}")
        results = result_holder.get("results")
        if isinstance(results, dict):
            return results
        return {}

    def _subscribe_portal_shortcut_signals(self, connection, Gio, session_handle: str) -> list[int]:  # noqa: ANN001
        def on_activated(_connection, _sender_name, _object_path, _interface_name, _signal_name, params):  # noqa: ANN001
            current_session, shortcut_id, _timestamp, _options = params.unpack()
            if current_session != session_handle or shortcut_id != PUSH_TO_TALK_SHORTCUT_ID:
                return
            with self._state_lock:
                if self._pressed:
                    return
                self._pressed = True
            self._callbacks.on_press()

        def on_deactivated(_connection, _sender_name, _object_path, _interface_name, _signal_name, params):  # noqa: ANN001
            current_session, shortcut_id, _timestamp, _options = params.unpack()
            if current_session != session_handle or shortcut_id != PUSH_TO_TALK_SHORTCUT_ID:
                return
            with self._state_lock:
                if not self._pressed:
                    return
                self._pressed = False
            self._callbacks.on_release()

        activated_id = connection.signal_subscribe(
            PORTAL_BUS_NAME,
            PORTAL_INTERFACE,
            "Activated",
            PORTAL_OBJECT_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            on_activated,
        )
        deactivated_id = connection.signal_subscribe(
            PORTAL_BUS_NAME,
            PORTAL_INTERFACE,
            "Deactivated",
            PORTAL_OBJECT_PATH,
            None,
            Gio.DBusSignalFlags.NONE,
            on_deactivated,
        )
        return [activated_id, deactivated_id]

    def _subscribe_session_signals(self, connection, Gio, session_handle: str, loop) -> list[int]:  # noqa: ANN001
        def on_closed(_connection, _sender_name, _object_path, _interface_name, _signal_name, _params):  # noqa: ANN001
            self._stopping = True
            loop.quit()

        closed_id = connection.signal_subscribe(
            PORTAL_BUS_NAME,
            PORTAL_SESSION_INTERFACE,
            "Closed",
            session_handle,
            None,
            Gio.DBusSignalFlags.NONE,
            on_closed,
        )
        return [closed_id]

    def _quit_loop(self, *_args) -> bool:  # noqa: ANN002
        if self._loop is not None:
            self._loop.quit()
        return False


class EvdevHotkeyBackend(HotkeyBackend):
    """Reads keyboards directly and re-opens them when they reappear.

    A keyboard that resets or is plugged in again gets a new event node. A
    monitor thread scans for keyboards and starts a reader for each new one.
    """

    def __init__(
        self,
        *,
        combo: str,
        callbacks: _HotkeyCallbacks,
    ) -> None:
        try:
            from evdev import InputDevice, ecodes
        except ImportError as exc:
            raise HotkeyBackendUnavailableError("python-evdev is not installed") from exc

        self._InputDevice = InputDevice
        self._ecodes = ecodes
        self._callbacks = callbacks
        self._combo = normalize_push_to_talk_combo(combo)
        self._devices: dict[str, object] = {}
        self._threads: list[threading.Thread] = []
        self._monitor: threading.Thread | None = None
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._pressed_key_names: set[str] = set()
        self._push_to_talk_pressed = False

    @property
    def name(self) -> str:
        return "evdev"

    def start(self) -> None:
        if self._monitor is not None:
            return
        device_paths = _keyboard_device_paths()
        if not device_paths:
            raise HotkeyBackendUnavailableError("no readable keyboard input devices were found")
        self._stop.clear()
        for path in device_paths:
            self._open_device(path)
        self._monitor = threading.Thread(target=self._watch_devices, daemon=True)
        self._monitor.start()

    def stop(self) -> None:
        self._stop.set()
        with self._state_lock:
            devices = list(self._devices.values())
            self._devices.clear()
        for device in devices:
            try:
                device.close()
            except Exception:  # noqa: BLE001
                pass
        threads = [*self._threads, *([self._monitor] if self._monitor else [])]
        for thread in threads:
            thread.join(timeout=1.0)
        self._monitor = None
        self._threads = []
        with self._state_lock:
            self._pressed_key_names.clear()
            self._push_to_talk_pressed = False

    def set_combo(self, combo: str) -> None:
        self._combo = normalize_push_to_talk_combo(combo)
        with self._state_lock:
            self._pressed_key_names.clear()
            self._push_to_talk_pressed = False

    def _open_device(self, path: str) -> None:
        try:
            device = self._InputDevice(path)
        except OSError as exc:
            logger.debug("Cannot open keyboard %s: %s", path, exc)
            return
        with self._state_lock:
            self._devices[path] = device
        thread = threading.Thread(target=self._read_device, args=(path, device), daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()]
        self._threads.append(thread)
        thread.start()

    def _watch_devices(self) -> None:
        while not self._stop.wait(DEVICE_RESCAN_SECONDS):
            with self._state_lock:
                known = set(self._devices)
            for path in _keyboard_device_paths():
                if path not in known and not self._stop.is_set():
                    logger.warning("Keyboard %s appeared; listening to it", path)
                    self._open_device(path)

    def _read_device(self, path: str, device) -> None:  # noqa: ANN001
        try:
            for event in device.read_loop():
                if self._stop.is_set():
                    break
                if event.type != self._ecodes.EV_KEY:
                    continue
                token = _normalize_evdev_keycode(self._ecodes.KEY.get(event.code))
                if token is None:
                    continue
                self._handle_key_event(token, event.value)
        except OSError:
            pass
        self._forget_device(path, device)

    def _forget_device(self, path: str, device) -> None:  # noqa: ANN001
        fire_release = False
        with self._state_lock:
            if self._devices.get(path) is device:
                del self._devices[path]
            if self._stop.is_set():
                return
            # Keys held on the lost keyboard never send a release event.
            fire_release = self._push_to_talk_pressed
            self._pressed_key_names.clear()
            self._push_to_talk_pressed = False
        try:
            device.close()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("Keyboard %s was lost; waiting for it to return", path)
        if fire_release:
            self._callbacks.on_release()

    def _handle_key_event(self, token: str, value: int) -> None:
        fire_press = False
        fire_release = False
        with self._state_lock:
            if value == 0:
                self._pressed_key_names.discard(token)
            else:
                self._pressed_key_names.add(token)

            if not self._push_to_talk_pressed and combo_is_active(self._pressed_key_names, self._combo):
                self._push_to_talk_pressed = True
                fire_press = True
            elif self._push_to_talk_pressed and not combo_is_active(
                self._pressed_key_names,
                self._combo,
            ):
                self._push_to_talk_pressed = False
                fire_release = True

        if fire_press:
            self._callbacks.on_press()
        if fire_release:
            self._callbacks.on_release()


def detect_hotkey_backend() -> str:
    session = detect_session_type()
    # On X11, pynput sees every keyboard through the X server. evdev sees only
    # the devices this user can open, which is often just a security key such
    # as a YubiKey (systemd gives it a uaccess ACL), not the real keyboard.
    if session == "x11" and pynput_available():
        return "pynput"
    if evdev_available():
        return "evdev"
    if session == "wayland" and portal_global_shortcuts_available():
        return "portal"
    if pynput_available():
        return "pynput"
    if session == "wayland":
        raise HotkeyBackendUnavailableError(
            "Wayland hotkey backend unavailable: GlobalShortcuts portal is not available"
        )
    raise HotkeyBackendUnavailableError("No supported hotkey backend is installed")


def create_hotkey_backend(
    *,
    combo: str,
    on_press: Callable[[], None],
    on_release: Callable[[], None],
) -> HotkeyBackend:
    backend = detect_hotkey_backend()
    callbacks = _HotkeyCallbacks(on_press=on_press, on_release=on_release)
    if backend == "evdev":
        return EvdevHotkeyBackend(combo=combo, callbacks=callbacks)
    if backend == "portal":
        return PortalHotkeyBackend(combo=combo, callbacks=callbacks)
    return PynputHotkeyBackend(combo=combo, callbacks=callbacks)


def request_portal_shortcut_authorization(combo: str) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "dictate.portal_shortcuts_helper",
                "--combo",
                normalize_push_to_talk_combo(combo),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:  # noqa: BLE001
        return (False, f"failed to launch portal authorization helper: {exc}")

    payload_text = (completed.stdout or "").strip().splitlines()
    if payload_text:
        try:
            payload = json.loads(payload_text[-1])
        except Exception:  # noqa: BLE001
            payload = None
        if isinstance(payload, dict):
            if payload.get("ok"):
                return (True, "")
            error = payload.get("error")
            if isinstance(error, str) and error:
                return (False, error)

    stderr = (completed.stderr or "").strip()
    if stderr:
        return (False, stderr.splitlines()[-1])
    return (completed.returncode == 0, f"portal helper exited with code {completed.returncode}")


def portal_global_shortcuts_available() -> bool:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except Exception:  # noqa: BLE001
        return False

    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        connection.call_sync(
            PORTAL_BUS_NAME,
            PORTAL_OBJECT_PATH,
            "org.freedesktop.DBus.Properties",
            "Get",
            GLib.Variant("(ss)", (PORTAL_INTERFACE, "version")),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
    except Exception:  # noqa: BLE001
        return False
    return True


def pynput_available() -> bool:
    try:
        from pynput import keyboard  # noqa: F401
    except ImportError:
        return False
    return True


def evdev_available() -> bool:
    try:
        from evdev import InputDevice  # noqa: F401
    except ImportError:
        return False
    return bool(_keyboard_device_paths())


def _register_host_app(connection, Gio, GLib) -> None:  # noqa: ANN001
    try:
        connection.call_sync(
            PORTAL_BUS_NAME,
            PORTAL_OBJECT_PATH,
            PORTAL_REGISTRY_INTERFACE,
            "Register",
            GLib.Variant("(sa{sv})", (APP_ID, {})),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
    except Exception:  # noqa: BLE001
        pass


def _portal_trigger(combo: str) -> str:
    modifiers: list[str] = []
    key_name = ""
    tokens = normalize_push_to_talk_combo(combo).split("+")
    for token in tokens:
        if token in _PORTAL_SINGLE_MODIFIER_KEY_NAMES and len(tokens) == 1:
            key_name = _PORTAL_SINGLE_MODIFIER_KEY_NAMES[token]
        elif token in _PORTAL_MODIFIER_NAMES:
            modifiers.append(_PORTAL_MODIFIER_NAMES[token])
        else:
            key_name = _portal_key_name(token)
    return "+".join([*modifiers, key_name] if key_name else modifiers)


_PORTAL_MODIFIER_NAMES = {
    "ctrl": "CTRL",
    "ctrl_l": "CTRL",
    "ctrl_r": "CTRL",
    "shift": "SHIFT",
    "shift_l": "SHIFT",
    "shift_r": "SHIFT",
    "alt": "ALT",
    "alt_l": "ALT",
    "alt_r": "ALT",
    "super": "LOGO",
    "super_l": "LOGO",
    "super_r": "LOGO",
}


_PORTAL_SINGLE_MODIFIER_KEY_NAMES = {
    "ctrl": "Control_L",
    "ctrl_l": "Control_L",
    "ctrl_r": "Control_R",
    "shift": "Shift_L",
    "shift_l": "Shift_L",
    "shift_r": "Shift_R",
    "alt": "Alt_L",
    "alt_l": "Alt_L",
    "alt_r": "Alt_R",
    "super": "Super_L",
    "super_l": "Super_L",
    "super_r": "Super_R",
}


def _token(prefix: str) -> str:
    return f"dictate_{prefix}_{uuid.uuid4().hex}"


def _portal_key_name(token: str) -> str:
    key_names = {
        "space": "space",
        "enter": "Return",
        "esc": "Escape",
        "tab": "Tab",
        "caps_lock": "Caps_Lock",
    }
    return key_names.get(token, token)


def _keyboard_device_paths() -> list[str]:
    by_path = Path("/dev/input/by-path")
    candidates: list[str] = []
    if by_path.is_dir():
        for path in sorted(by_path.glob("*-event-kbd")):
            real_path = os.path.realpath(path)
            if os.access(real_path, os.R_OK):
                candidates.append(real_path)
    return list(dict.fromkeys(candidates))


def _normalize_evdev_keycode(key_name: str | list[str] | None) -> str | None:
    if isinstance(key_name, list):
        if not key_name:
            return None
        key_name = key_name[0]
    if not isinstance(key_name, str):
        return None
    key_name = key_name.removeprefix("KEY_").lower()
    key_map = {
        "leftctrl": "ctrl_l",
        "rightctrl": "ctrl_r",
        "leftshift": "shift_l",
        "rightshift": "shift_r",
        "leftalt": "alt_l",
        "rightalt": "alt_r",
        "leftmeta": "super_l",
        "rightmeta": "super_r",
        "space": "space",
        "enter": "enter",
        "esc": "esc",
        "tab": "tab",
        "capslock": "caps_lock",
    }
    token = key_map.get(key_name, key_name)
    if len(token) == 1 and token.isalnum():
        return token
    if token in {
        "ctrl_l",
        "ctrl_r",
        "shift_l",
        "shift_r",
        "alt_l",
        "alt_r",
        "super_l",
        "super_r",
        "space",
        "enter",
        "esc",
        "tab",
        "caps_lock",
    }:
        return token
    return None
