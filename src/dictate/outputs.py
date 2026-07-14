"""Text output adapters and typing backend selection."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol


class OutputError(RuntimeError):
    """Raised when a text output backend fails."""


class BackendUnavailableError(RuntimeError):
    """Raised when no suitable typing backend is available."""


class TextOutput(Protocol):
    name: str

    def send(self, text: str) -> None:
        """Emit text through this output backend."""


def detect_session_type() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type in {"x11", "wayland"}:
        return session_type
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


@dataclass(slots=True)
class StdoutOutput:
    name: str = "stdout"

    def send(self, text: str) -> None:
        print(text)


@dataclass(slots=True)
class ClipboardOutput:
    name: str = "clipboard"

    def send(self, text: str) -> None:
        if sys.platform.startswith("win"):
            try:
                import pyperclip

                pyperclip.copy(text)
                return
            except ImportError:
                pass
            except Exception as exc:  # noqa: BLE001
                raise OutputError(f"clipboard command failed: {exc}") from exc

        if os.environ.get("WAYLAND_DISPLAY") and command_exists("wl-copy"):
            try:
                subprocess.run(
                    ["wl-copy"],
                    input=text.encode(),
                    check=True,
                )
                return
            except subprocess.CalledProcessError as exc:
                raise OutputError(f"clipboard command failed: {exc}") from exc

        if command_exists("xclip"):
            try:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(),
                    check=True,
                )
                return
            except subprocess.CalledProcessError as exc:
                raise OutputError(f"clipboard command failed: {exc}") from exc

        try:
            import pyperclip

            pyperclip.copy(text)
        except ImportError as exc:
            raise OutputError("no clipboard backend found; install xclip or pyperclip") from exc
        except Exception as exc:  # noqa: BLE001
            raise OutputError(f"clipboard command failed: {exc}") from exc


@dataclass(slots=True)
class PasteOutput:
    """Insert completed text in one paste instead of simulating every character."""

    typing_output: TextOutput
    clipboard_output: TextOutput

    @property
    def name(self) -> str:
        return f"paste/{self.typing_output.name}"

    def send(self, text: str) -> None:
        self.clipboard_output.send(text)
        _send_paste_shortcut(self.typing_output)


@dataclass(slots=True)
class XdotoolOutput:
    name: str = "xdotool"

    def send(self, text: str) -> None:
        try:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "0", text],
                check=True,
            )
        except FileNotFoundError as exc:
            raise OutputError("xdotool is not installed") from exc
        except subprocess.CalledProcessError as exc:
            raise OutputError(f"xdotool failed: {exc}") from exc


@dataclass(slots=True)
class WtypeOutput:
    name: str = "wtype"

    def send(self, text: str) -> None:
        try:
            subprocess.run(["wtype", "--", text], check=True)
        except FileNotFoundError as exc:
            raise OutputError("wtype is not installed") from exc
        except subprocess.CalledProcessError as exc:
            raise OutputError(f"wtype failed: {exc}") from exc


@dataclass(slots=True)
class YdotoolOutput:
    name: str = "ydotool"

    def send(self, text: str) -> None:
        try:
            subprocess.run(["ydotool", "type", "--key-delay", "0", text], check=True)
        except FileNotFoundError as exc:
            raise OutputError("ydotool is not installed") from exc
        except subprocess.CalledProcessError as exc:
            raise OutputError(f"ydotool failed: {exc}") from exc


@dataclass(slots=True)
class PynputOutput:
    name: str = "pynput"

    def send(self, text: str) -> None:
        try:
            from pynput.keyboard import Controller
        except ImportError as exc:
            raise OutputError("pynput is not installed") from exc
        try:
            Controller().type(text)
        except Exception as exc:  # noqa: BLE001
            raise OutputError(f"pynput failed: {exc}") from exc


def python_module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
    except ImportError:
        return False
    return True


def clipboard_backend_available() -> bool:
    if (os.environ.get("WAYLAND_DISPLAY") and command_exists("wl-copy")) or command_exists("xclip"):
        return True
    return python_module_available("pyperclip")


def available_typing_backends() -> list[str]:
    backends: list[str] = []
    for backend in ("xdotool", "wtype", "ydotool", "pynput"):
        if backend == "pynput":
            if python_module_available("pynput"):
                backends.append(backend)
        elif command_exists(backend):
            backends.append(backend)
    return backends


def _build_typing_output(backend: str) -> TextOutput:
    if backend == "xdotool":
        return XdotoolOutput()
    if backend == "wtype":
        return WtypeOutput()
    if backend == "ydotool":
        return YdotoolOutput()
    if backend == "pynput":
        return PynputOutput()
    raise BackendUnavailableError(f"unknown typing backend: {backend}")


def resolve_typing_backend(preferred: str = "auto") -> TextOutput:
    """Pick a backend and paste completed dictations into the focused control."""
    if preferred != "auto":
        if preferred == "pynput":
            if not python_module_available("pynput"):
                raise BackendUnavailableError("requested typing backend 'pynput' is not installed")
            return PasteOutput(PynputOutput(), ClipboardOutput())
        if not command_exists(preferred):
            raise BackendUnavailableError(
                f"requested typing backend '{preferred}' is not installed"
            )
        return PasteOutput(_build_typing_output(preferred), ClipboardOutput())

    session = detect_session_type()
    if session == "windows":
        candidates = ["pynput"]
    elif session == "wayland":
        candidates = ["wtype", "ydotool", "xdotool"]
    elif session == "x11":
        candidates = ["xdotool", "wtype", "ydotool"]
    else:
        candidates = ["xdotool", "wtype", "ydotool", "pynput"]

    for candidate in candidates:
        if candidate == "pynput":
            if python_module_available("pynput"):
                return PasteOutput(PynputOutput(), ClipboardOutput())
        elif command_exists(candidate):
            return PasteOutput(_build_typing_output(candidate), ClipboardOutput())

    raise BackendUnavailableError(
        "no typing backend found; install one of: xdotool, wtype, ydotool, pynput"
    )


def _send_paste_shortcut(output: TextOutput) -> None:
    try:
        if isinstance(output, XdotoolOutput):
            subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], check=True)
            return
        if isinstance(output, WtypeOutput):
            subprocess.run(
                ["wtype", "-M", "ctrl", "-P", "v", "-p", "v", "-m", "ctrl"],
                check=True,
            )
            return
        if isinstance(output, YdotoolOutput):
            subprocess.run(
                ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                check=True,
            )
            return
        if isinstance(output, PynputOutput):
            from pynput.keyboard import Controller, Key

            keyboard = Controller()
            with keyboard.pressed(Key.ctrl):
                keyboard.press("v")
                keyboard.release("v")
            return
    except FileNotFoundError as exc:
        raise OutputError(f"{output.name} is not installed") from exc
    except subprocess.CalledProcessError as exc:
        raise OutputError(f"{output.name} paste failed: {exc}") from exc
    except ImportError as exc:
        raise OutputError("pynput is not installed") from exc
    except Exception as exc:  # noqa: BLE001
        raise OutputError(f"{output.name} paste failed: {exc}") from exc
    raise OutputError(f"typing backend cannot paste: {output.name}")
