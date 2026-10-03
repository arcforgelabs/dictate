"""Clipboard save and restore on Linux desktops (X11 through xclip, Wayland through wl-clipboard).

Both command-line tools serve one type per process, so a restore puts back the
single most useful type the owner offered: an image if there was one, else
text, else the first type offered. An empty clipboard is restored as empty.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass

from dictate.clipboard_keeper import ClipboardItem, best_restorable_type

_READ_TIMEOUT_SECONDS = 1.0
_READY_TIMEOUT_SECONDS = 1.0
_REQUEST_RE = re.compile(r"Waiting for selection request number (\d+)")


def _output_error(message: str) -> Exception:
    from dictate.outputs import OutputError

    return OutputError(message)


@dataclass(slots=True)
class _SavedSelection:
    """``item`` is None for an empty selection."""

    item: ClipboardItem | None


class _XclipWriter:
    """An ``xclip -verbose`` process that owns one selection and reports pastes.

    Verbose xclip stays in the foreground and prints "Waiting for selection
    request number N" after serving request N-1, so the count of served
    requests is the paste signal. It exits when another client takes the
    selection, which is how a copy made mid-dictation is noticed.
    """

    def __init__(self, selection: str, text: str) -> None:
        self.selection = selection
        self._served = 0
        self._ready = threading.Event()
        self._lost = False
        self._lock = threading.Lock()
        try:
            self._proc = subprocess.Popen(
                ["xclip", "-verbose", "-selection", selection, "-t", "UTF8_STRING", "-i"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise _output_error(f"clipboard command failed: {exc}") from exc
        self._reader = threading.Thread(
            target=self._read_stderr, name=f"dictate-xclip-{selection}", daemon=True
        )
        self._reader.start()
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.write(text.encode())
            self._proc.stdin.close()
        except OSError as exc:
            self.terminate()
            raise _output_error(f"clipboard command failed: {exc}") from exc
        deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
        while not self._ready.wait(0.01):
            if self._proc.poll() is not None or time.monotonic() >= deadline:
                code = self._proc.poll()
                self.terminate()
                raise _output_error(f"clipboard command failed: xclip did not take the {selection} selection (exit {code})")

    def _read_stderr(self) -> None:
        stream = self._proc.stderr
        if stream is None:
            return
        for raw in stream:
            line = raw.decode(errors="replace")
            if "Waiting for selection request" in line or "Waiting for one selection" in line:
                self._ready.set()
            match = _REQUEST_RE.search(line)
            if match:
                with self._lock:
                    self._served = max(self._served, int(match.group(1)) - 1)
            if "Lost selection ownership" in line:
                with self._lock:
                    self._lost = True

    @property
    def served(self) -> int:
        with self._lock:
            return self._served

    def lost_ownership(self) -> bool:
        with self._lock:
            if self._lost:
                return True
        return self._proc.poll() is not None

    def terminate(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def _xclip_read(selection: str, target: str) -> bytes | None:
    try:
        completed = subprocess.run(
            ["xclip", "-selection", selection, "-o", "-t", target],
            capture_output=True,
            timeout=_READ_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _output_error(f"{selection} owner did not answer") from exc
    if completed.returncode != 0:
        return None
    return completed.stdout


def _xclip_snapshot(selection: str) -> _SavedSelection:
    listing = _xclip_read(selection, "TARGETS")
    if listing is None:
        # No owner, or an old owner that does not list targets: try text.
        data = _xclip_read(selection, "UTF8_STRING")
        if data is None:
            return _SavedSelection(None)
        return _SavedSelection(ClipboardItem("UTF8_STRING", data))
    targets = [line.strip() for line in listing.decode(errors="replace").splitlines()]
    target = best_restorable_type(targets)
    if target is None:
        return _SavedSelection(None)
    data = _xclip_read(selection, target)
    if data is None:
        return _SavedSelection(None)
    return _SavedSelection(ClipboardItem(target, data))


class XclipClipboardSession:
    """X11: CLIPBOARD, plus PRIMARY when the terminal paste path uses it."""

    has_read_signal = True
    settle_seconds = 0.2
    handles_primary = True

    def __init__(self, *, plain_text: bool = False) -> None:
        self._selections = ["clipboard", "primary"] if plain_text else ["clipboard"]
        self._writers: dict[str, _XclipWriter] = {}
        self._baseline: dict[str, int] = {}

    def snapshot(self) -> dict[str, _SavedSelection]:
        return {selection: _xclip_snapshot(selection) for selection in self._selections}

    def write_text(self, text: str) -> None:
        for selection in self._selections:
            self._writers[selection] = _XclipWriter(selection, text)

    def before_paste(self) -> None:
        # Requests served before the keystroke (clipboard managers) do not count.
        self._baseline = {name: writer.served for name, writer in self._writers.items()}

    def target_has_read(self) -> bool:
        return any(
            writer.served > self._baseline.get(name, 0) for name, writer in self._writers.items()
        )

    def wait(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def changed_since_write(self) -> bool:
        # Selecting text in a terminal replaces PRIMARY all the time; that must
        # not stop CLIPBOARD coming back. Each selection is checked in restore.
        return bool(self._writers) and all(w.lost_ownership() for w in self._writers.values())

    def restore(self, snapshot: dict[str, _SavedSelection]) -> None:
        for selection, saved in snapshot.items():
            writer = self._writers.get(selection)
            if writer is None or writer.lost_ownership():
                continue
            if saved.item is None:
                # The server clears a selection when its owner disconnects.
                writer.terminate()
                continue
            subprocess.run(
                ["xclip", "-selection", selection, "-t", str(saved.item.format), "-i"],
                input=saved.item.data,
                check=True,
                timeout=2.0,
            )

    def close(self) -> None:
        for writer in self._writers.values():
            writer.terminate()
        self._writers.clear()


def _wl_paste(args: list[str]) -> bytes | None:
    try:
        completed = subprocess.run(
            ["wl-paste", *args],
            capture_output=True,
            timeout=_READ_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _output_error("clipboard owner did not answer") from exc
    if completed.returncode != 0:
        return None
    return completed.stdout


class WaylandClipboardSession:
    """Wayland through wl-copy and wl-paste. There is no read signal, so the
    keeper waits a fixed, bounded time before restoring."""

    has_read_signal = False
    settle_seconds = 0.0
    handles_primary = False

    def __init__(self, *, plain_text: bool = False) -> None:
        self._written: bytes | None = None

    def snapshot(self) -> _SavedSelection:
        listing = _wl_paste(["--list-types"])
        if listing is None:
            return _SavedSelection(None)
        types = [line.strip() for line in listing.decode(errors="replace").splitlines()]
        mime = best_restorable_type(types)
        if mime is None:
            return _SavedSelection(None)
        data = _wl_paste(["--no-newline", "--type", mime])
        if data is None:
            return _SavedSelection(None)
        return _SavedSelection(ClipboardItem(mime, data))

    def write_text(self, text: str) -> None:
        payload = text.encode()
        try:
            subprocess.run(["wl-copy"], input=payload, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise _output_error(f"clipboard command failed: {exc}") from exc
        self._written = payload

    def before_paste(self) -> None:
        pass

    def target_has_read(self) -> bool:
        return False

    def wait(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def changed_since_write(self) -> bool:
        current = _wl_paste(["--no-newline", "--type", "text/plain;charset=utf-8"])
        return current != self._written

    def restore(self, snapshot: _SavedSelection) -> None:
        if snapshot.item is None:
            subprocess.run(["wl-copy", "--clear"], check=True, timeout=2.0)
            return
        subprocess.run(
            ["wl-copy", "--type", str(snapshot.item.format)],
            input=snapshot.item.data,
            check=True,
            timeout=2.0,
        )

    def close(self) -> None:
        pass
