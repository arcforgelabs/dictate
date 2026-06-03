"""Launch the Quiet Console (Tauri shell) and ensure its control server runs.

This is the bridge the tray uses to open the new web-based Settings window. It
keeps the Python engine authoritative: it starts the in-process ``ui_server`` (so
the shell has a URL + token to talk to) and then spawns the Tauri binary. When no
shell binary is installed it returns ``False`` so callers can fall back to the
existing native GTK dialogs.

Everything with a side effect (locating the binary, starting the server, spawning
the process) is injectable, so the logic is unit-tested without a real shell,
sockets or subprocesses.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Sequence

from dictate.platform_paths import is_windows

logger = logging.getLogger(__name__)

# Environment overrides, then PATH, then common install + dev locations.
_ENV_BINARY = "DICTATE_UI_SHELL"
_BINARY_NAME = "dictate-ui-shell"


def shell_binary_candidates() -> list[Path]:
    """Ordered locations to probe for the Tauri shell binary."""
    candidates: list[Path] = []
    override = os.environ.get(_ENV_BINARY)
    if override:
        candidates.append(Path(override))

    on_path = shutil.which(_BINARY_NAME)
    if on_path:
        candidates.append(Path(on_path))

    home = Path.home()
    name = _BINARY_NAME + (".exe" if is_windows() else "")
    candidates.extend(
        [
            home / ".local" / "bin" / name,
            Path("/usr/local/bin") / name,
            Path("/usr/bin") / name,
            # dev build output, relative to the repo root (…/dictate/)
            _repo_root() / "ui-shell" / "src-tauri" / "target" / "release" / name,
            _repo_root() / "ui-shell" / "src-tauri" / "target" / "debug" / name,
        ]
    )
    return candidates


def _repo_root() -> Path:
    # src/dictate/ui_launcher.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[2]


def find_shell_binary(
    exists: Callable[[Path], bool] = lambda p: p.exists(),
    candidates: Sequence[Path] | None = None,
) -> Path | None:
    """Return the first existing shell binary, or ``None``."""
    for candidate in candidates if candidates is not None else shell_binary_candidates():
        try:
            if exists(candidate):
                return candidate
        except OSError:
            continue
    return None


def build_launch_command(binary: Path) -> list[str]:
    return [str(binary)]


def open_settings_window(
    *,
    start_server: Callable[[], object] | None = None,
    find_binary: Callable[[], Path | None] = find_shell_binary,
    spawn: Callable[[list[str]], object] | None = None,
) -> bool:
    """Ensure the control server is up and launch the shell.

    Returns ``True`` when the shell was spawned, ``False`` when no shell binary is
    available (the caller should then fall back to the native dialogs).
    """
    binary = find_binary()
    if binary is None:
        logger.info("Dictate UI shell binary not found; falling back to native settings.")
        return False

    if start_server is not None:
        try:
            start_server()
        except Exception:  # noqa: BLE001 — never block opening on server hiccups
            logger.exception("Failed to start the Dictate UI control server")

    command = build_launch_command(binary)
    spawner = spawn if spawn is not None else _default_spawn
    try:
        spawner(command)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to launch the Dictate UI shell")
        return False
    return True


def _default_spawn(command: list[str]) -> subprocess.Popen:
    return subprocess.Popen(command)  # noqa: S603 — fixed, locally-resolved binary


# Process-wide handle so we start the in-process server at most once.
_server_handle: object | None = None
_server_broker: object | None = None
_wired_daemon_id: int | None = None


def ensure_server_started(daemon: object | None = None) -> object:
    """Start the in-process ``ui_server`` once and return its handle."""
    global _server_broker, _server_handle, _wired_daemon_id
    if _server_handle is not None:
        if daemon is not None and _server_broker is not None and _wired_daemon_id != id(daemon):
            _wire_daemon_events(daemon, _server_broker)
            _wired_daemon_id = id(daemon)
        return _server_handle
    from dictate import ui_server

    broker = ui_server.EventBroker()
    backend = ui_server.UiBackend(
        history_store=getattr(daemon, "history_store", None),
        broker=broker,
    )
    _server_handle = ui_server.serve(backend=backend, broker=broker)
    _server_broker = broker
    if daemon is not None:
        _wire_daemon_events(daemon, broker)
        _wired_daemon_id = id(daemon)
    return _server_handle


def _wire_daemon_events(daemon: object, broker: object) -> None:
    """Fan daemon callbacks out to the UI broker while preserving existing hooks."""
    prev_status = getattr(daemon, "status_callback", None)
    prev_recording = getattr(daemon, "recording_callback", None)

    def on_status(message: str | None) -> None:
        if prev_status is not None:
            try:
                prev_status(message)
            except Exception:  # noqa: BLE001
                logger.exception("prior status callback failed")
        broker.publish("status", message=message)

    def on_recording(active: bool) -> None:
        if prev_recording is not None:
            try:
                prev_recording(active)
            except Exception:  # noqa: BLE001
                logger.exception("prior recording callback failed")
        broker.publish("recording", active=bool(active))

    daemon.status_callback = on_status
    daemon.recording_callback = on_recording
    daemon.history_callback = lambda: broker.publish("history-changed")
