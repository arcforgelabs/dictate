"""Leave the clipboard as it was around each dictation.

Dictate pastes completed text through the clipboard. A ``ClipboardKeeper``
saves what the clipboard held, writes the dictated text, sends the paste,
waits until the target app has read it, and then puts the saved contents
back. If someone copies something else while the paste is in flight, that
copy is left alone.

The platform work lives in a ``ClipboardSession``: one per dictation, opened
and closed on the keeper's worker thread. Nothing here logs clipboard
contents; logs carry only counts and outcomes.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Longest wait for a target app to read the dictated text when the platform
# can tell us it has (Windows delayed rendering, X11 selection requests).
SIGNAL_READ_TIMEOUT_SECONDS = 2.0
# Fixed wait when the platform gives no read signal (Wayland, pyperclip).
NO_SIGNAL_DELAY_SECONDS = 1.0
# Granularity of the wait loop.
POLL_INTERVAL_SECONDS = 0.01


class ClipboardSession(Protocol):
    """One dictation's use of the system clipboard.

    ``snapshot`` and ``restore`` exchange an opaque value. ``changed_since_write``
    is True when someone else replaced the dictated text, in which case the
    keeper does not restore. ``restore`` may return False when it finds such a
    copy itself at the last moment.
    """

    has_read_signal: bool
    settle_seconds: float
    handles_primary: bool

    def snapshot(self) -> Any: ...

    def write_text(self, text: str) -> None: ...

    def before_paste(self) -> None: ...

    def target_has_read(self) -> bool: ...

    def wait(self, seconds: float) -> None: ...

    def changed_since_write(self) -> bool: ...

    def restore(self, snapshot: Any) -> bool | None: ...

    def close(self) -> None: ...


SessionFactory = Callable[[bool], ClipboardSession]


class ClipboardKeeperUnavailable(RuntimeError):
    """The clipboard session could not be set up; paste without saving."""



@dataclass(slots=True)
class PasteOutcome:
    """What happened to the clipboard around one paste. Never holds contents."""

    saved: bool = False
    read_signal: bool = False
    timed_out: bool = False
    restored: bool = False
    kept_newer_copy: bool = False
    error: str = ""


@dataclass(slots=True)
class _Job:
    pasted: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


class ClipboardKeeper:
    """Run a paste between a clipboard snapshot and its restore.

    ``paste`` returns once the paste keystroke has been sent; the wait for the
    target to read and the restore run on a worker thread so the caller is not
    held up. Transactions are serialized: the next dictation waits for the
    previous restore, so it never snapshots the previous dictation's text.
    """

    def __init__(
        self,
        open_session: SessionFactory,
        *,
        read_timeout: float = SIGNAL_READ_TIMEOUT_SECONDS,
        no_signal_delay: float = NO_SIGNAL_DELAY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        background: bool = True,
    ) -> None:
        self._open_session = open_session
        self.read_timeout = read_timeout
        self.no_signal_delay = no_signal_delay
        self._clock = clock
        self._background = background
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self.last_outcome: PasteOutcome | None = None

    def paste(
        self,
        text: str,
        send_paste: Callable[[], None],
        *,
        plain_text: bool = False,
        after_write: Callable[[ClipboardSession], None] | None = None,
    ) -> None:
        job = _Job()
        if not self._background:
            self._run(job, text, send_paste, plain_text, after_write)
            if job.error is not None:
                raise job.error
            return
        worker = threading.Thread(
            target=self._run,
            args=(job, text, send_paste, plain_text, after_write),
            name="dictate-clipboard",
            # Not a daemon: a restore in flight finishes before the process exits.
            daemon=False,
        )
        self._worker = worker
        worker.start()
        job.pasted.wait()
        if job.error is not None:
            raise job.error

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until the last transaction has restored. For tests and shutdown."""
        worker = self._worker
        if worker is None:
            return True
        worker.join(timeout)
        return not worker.is_alive()

    def _run(
        self,
        job: _Job,
        text: str,
        send_paste: Callable[[], None],
        plain_text: bool,
        after_write: Callable[[ClipboardSession], None] | None,
    ) -> None:
        with self._lock:
            outcome = PasteOutcome()
            try:
                self._transaction(job, outcome, text, send_paste, plain_text, after_write)
            except BaseException as exc:  # noqa: BLE001
                if not job.pasted.is_set():
                    job.error = exc
                else:
                    outcome.error = type(exc).__name__
                    logger.warning("Clipboard restore failed: %s", type(exc).__name__)
            finally:
                job.pasted.set()
                self.last_outcome = outcome
                logger.debug(
                    "Clipboard around paste: saved=%s read_signal=%s timed_out=%s "
                    "restored=%s kept_newer_copy=%s",
                    outcome.saved,
                    outcome.read_signal,
                    outcome.timed_out,
                    outcome.restored,
                    outcome.kept_newer_copy,
                )

    def _transaction(
        self,
        job: _Job,
        outcome: PasteOutcome,
        text: str,
        send_paste: Callable[[], None],
        plain_text: bool,
        after_write: Callable[[ClipboardSession], None] | None,
    ) -> None:
        try:
            session = self._open_session(plain_text)
        except Exception as exc:  # noqa: BLE001
            raise ClipboardKeeperUnavailable(type(exc).__name__) from exc
        try:
            snapshot: Any = None
            try:
                snapshot = session.snapshot()
                outcome.saved = True
            except Exception as exc:  # noqa: BLE001
                # Dictation still pastes; only the restore is lost.
                logger.warning(
                    "Could not save the clipboard before pasting (%s); "
                    "it will hold the dictated text afterwards.",
                    type(exc).__name__,
                )

            try:
                session.write_text(text)
                if after_write is not None:
                    after_write(session)
                # Reads before this point (clipboard managers reacting to the
                # write) are not the paste target.
                session.before_paste()
                send_paste()
            except BaseException:
                # Nothing will read the text. If the write got far enough to
                # replace the clipboard, put the old contents straight back.
                self._restore_after_failure(session, snapshot, outcome)
                raise
            job.pasted.set()

            self._wait_for_read(session, outcome)
            if not outcome.saved:
                return
            if session.changed_since_write():
                outcome.kept_newer_copy = True
                return
            self._restore(session, snapshot, outcome)
        finally:
            session.close()

    @classmethod
    def _restore_after_failure(
        cls, session: ClipboardSession, snapshot: Any, outcome: PasteOutcome
    ) -> None:
        if not outcome.saved:
            return
        try:
            # A write that failed before touching the clipboard reads as
            # "changed" here (Windows: not the owner; Wayland/X11: our text is
            # not there), so nothing is overwritten.
            if not session.changed_since_write():
                cls._restore(session, snapshot, outcome)
        except Exception as exc:  # noqa: BLE001
            # Report the original failure, not this one.
            logger.warning("Clipboard restore after a failed paste failed: %s", type(exc).__name__)

    @staticmethod
    def _restore(session: ClipboardSession, snapshot: Any, outcome: PasteOutcome) -> None:
        # A session returns False when it found a newer copy at the last moment.
        if session.restore(snapshot) is False:
            outcome.kept_newer_copy = True
        else:
            outcome.restored = True

    def _wait_for_read(self, session: ClipboardSession, outcome: PasteOutcome) -> None:
        if not session.has_read_signal:
            session.wait(self.no_signal_delay)
            outcome.timed_out = True
            return
        deadline = self._clock() + self.read_timeout
        while True:
            if session.target_has_read():
                outcome.read_signal = True
                # Let the target finish reading (TARGETS then data on X11,
                # closing the clipboard on Windows).
                if session.settle_seconds > 0:
                    session.wait(session.settle_seconds)
                return
            if session.changed_since_write():
                return
            remaining = deadline - self._clock()
            if remaining <= 0:
                outcome.timed_out = True
                return
            session.wait(min(remaining, POLL_INTERVAL_SECONDS))


@dataclass(frozen=True, slots=True)
class ClipboardItem:
    """One format of saved clipboard data."""

    format: int | str
    data: bytes
    name: str = ""
    kind: str = "bytes"


# Targets or MIME types that carry text, best first.
TEXT_TYPES = (
    "text/plain;charset=utf-8",
    "UTF8_STRING",
    "text/plain",
    "STRING",
    "TEXT",
)

# X11 selection meta-targets that are not data.
_META_TARGETS = {
    "TARGETS",
    "MULTIPLE",
    "TIMESTAMP",
    "SAVE_TARGETS",
    "DELETE",
    "INSERT_PROPERTY",
    "INSERT_SELECTION",
}


def best_restorable_type(types: list[str]) -> str | None:
    """Pick the one type to restore when the backend can serve only one.

    Images win over text (an image copy also offers HTML or a URL that would
    paste as the wrong thing). Then text. Then whatever the owner offered first.
    """
    offered = [t for t in types if t and t not in _META_TARGETS and not t.startswith("chromium/")]
    for candidate in offered:
        if candidate == "image/png":
            return candidate
    for candidate in offered:
        if candidate.startswith("image/"):
            return candidate
    for wanted in TEXT_TYPES:
        if wanted in offered:
            return wanted
    return offered[0] if offered else None


class TextOnlyClipboardSession:
    """Plain-text save and restore through pyperclip, when nothing better exists."""

    has_read_signal = False
    settle_seconds = 0.0
    handles_primary = False

    def __init__(self, plain_text: bool = False) -> None:
        import pyperclip

        self._pyperclip = pyperclip
        self._written: str | None = None

    def snapshot(self) -> str:
        value = self._pyperclip.paste()
        return value if isinstance(value, str) else ""

    def write_text(self, text: str) -> None:
        from dictate.outputs import OutputError

        try:
            self._pyperclip.copy(text)
        except Exception as exc:  # noqa: BLE001
            raise OutputError(f"clipboard command failed: {exc}") from exc
        self._written = text

    def before_paste(self) -> None:
        pass

    def target_has_read(self) -> bool:
        return False

    def wait(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def changed_since_write(self) -> bool:
        try:
            current = self._pyperclip.paste()
        except Exception:  # noqa: BLE001
            return True
        return current != self._written

    def restore(self, snapshot: str) -> None:
        self._pyperclip.copy(snapshot)

    def close(self) -> None:
        pass


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def default_session_factory() -> SessionFactory | None:
    """The clipboard session for this desktop, or None when none can save and restore."""
    if sys.platform.startswith("win"):
        from dictate.clipboard_windows import WindowsClipboardSession

        return lambda plain_text: WindowsClipboardSession()
    if os.environ.get("WAYLAND_DISPLAY") and _command_exists("wl-copy"):
        if not _command_exists("wl-paste"):
            return None
        from dictate.clipboard_linux import WaylandClipboardSession

        return lambda plain_text: WaylandClipboardSession(plain_text=plain_text)
    if _command_exists("xclip"):
        from dictate.clipboard_linux import XclipClipboardSession

        return lambda plain_text: XclipClipboardSession(plain_text=plain_text)
    try:
        import pyperclip  # noqa: F401
    except ImportError:
        return None
    return lambda plain_text: TextOnlyClipboardSession(plain_text)


def default_clipboard_keeper() -> ClipboardKeeper | None:
    factory = default_session_factory()
    if factory is None:
        return None
    return ClipboardKeeper(factory)
