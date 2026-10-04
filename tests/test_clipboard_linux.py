"""Linux clipboard sessions: command lines with fakes, and real xclip under X when available.

The real X11 tests need ``DISPLAY`` and ``xclip``; CI runs them under Xvfb.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from dictate.clipboard_keeper import ClipboardItem, ClipboardKeeper
from dictate.clipboard_linux import (
    WaylandClipboardSession,
    XclipClipboardSession,
    _SavedSelection,
    _XclipWriter,
)


def completed(stdout: bytes = b"", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=b"")


class WaylandSessionTests(unittest.TestCase):
    def test_snapshot_saves_the_best_type(self) -> None:
        def fake_run(args, **kwargs):
            if args == ["wl-paste", "--list-types"]:
                return completed(b"text/html\nimage/png\ntext/plain\n")
            if args == ["wl-paste", "--no-newline", "--type", "image/png"]:
                return completed(b"\x89PNG-bytes")
            raise AssertionError(args)

        with patch("dictate.clipboard_linux.subprocess.run", side_effect=fake_run):
            saved = WaylandClipboardSession().snapshot()

        self.assertEqual(saved.item, ClipboardItem("image/png", b"\x89PNG-bytes"))

    def test_snapshot_of_an_empty_clipboard_is_empty(self) -> None:
        with patch("dictate.clipboard_linux.subprocess.run", return_value=completed(returncode=1)):
            self.assertIsNone(WaylandClipboardSession().snapshot().item)

    def test_restore_puts_back_the_saved_type_or_clears(self) -> None:
        session = WaylandClipboardSession()
        with patch("dictate.clipboard_linux.subprocess.run", return_value=completed()) as run:
            session.restore(_SavedSelection(ClipboardItem("text/plain;charset=utf-8", b"before")))
            session.restore(_SavedSelection(None))

        first, second = run.call_args_list
        self.assertEqual(first.args[0], ["wl-copy", "--type", "text/plain;charset=utf-8"])
        self.assertEqual(first.kwargs["input"], b"before")
        self.assertEqual(second.args[0], ["wl-copy", "--clear"])

    def test_change_is_detected_by_reading_back_the_type_that_was_written(self) -> None:
        session = WaylandClipboardSession()
        with patch("dictate.clipboard_linux.subprocess.run", return_value=completed()) as write:
            session.write_text("dictated")
        self.assertEqual(write.call_args.args[0], ["wl-copy", "--type", "text/plain;charset=utf-8"])
        self.assertEqual(write.call_args.kwargs["input"], b"dictated")
        with patch("dictate.clipboard_linux.subprocess.run", return_value=completed(b"dictated")) as read:
            self.assertFalse(session.changed_since_write())
        self.assertEqual(
            read.call_args.args[0],
            ["wl-paste", "--no-newline", "--type", "text/plain;charset=utf-8"],
        )
        with patch("dictate.clipboard_linux.subprocess.run", return_value=completed(b"user copy")):
            self.assertTrue(session.changed_since_write())
        with patch("dictate.clipboard_linux.subprocess.run", return_value=completed(returncode=1)):
            self.assertTrue(session.changed_since_write())


class FakeXclip:
    """Stands in for ``xclip -verbose``: stderr lines are fed by the test."""

    def __init__(self, args, **kwargs) -> None:
        self.args = args
        self.lines: queue.Queue[bytes | None] = queue.Queue()
        self.returncode: int | None = None
        self.stdin_data = b""
        outer = self

        class Stdin:
            def write(self, data: bytes) -> int:
                outer.stdin_data += data
                return len(data)

            def close(self) -> None:
                outer.feed("Waiting for selection requests, Control-C to quit")

        class Stderr:
            def __iter__(self):
                while True:
                    line = outer.lines.get()
                    if line is None:
                        return
                    yield line

            def close(self) -> None:
                outer.stderr_closed = True

        self.stderr_closed = False
        self.stdin = Stdin()
        self.stderr = Stderr()

    def feed(self, line: str) -> None:
        self.lines.put((line + "\n").encode())

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15
        self.lines.put(None)

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.terminate()


def wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class XclipWriterTests(unittest.TestCase):
    def test_counts_served_requests_and_notices_lost_ownership(self) -> None:
        procs: list[FakeXclip] = []

        def popen(args, **kwargs):
            proc = FakeXclip(args, **kwargs)
            procs.append(proc)
            return proc

        with patch("dictate.clipboard_linux.subprocess.Popen", side_effect=popen):
            writer = _XclipWriter("clipboard", "dictated")

        proc = procs[0]
        self.assertEqual(
            proc.args, ["xclip", "-verbose", "-selection", "clipboard", "-t", "UTF8_STRING", "-i"]
        )
        self.assertEqual(proc.stdin_data, b"dictated")
        self.assertEqual(writer.served, 0)
        proc.feed("  Waiting for selection request number 2")
        self.assertTrue(wait_until(lambda: writer.served == 1))
        self.assertFalse(writer.lost_ownership())
        proc.feed("Lost selection ownership. (some app did a copy).")
        self.assertTrue(wait_until(writer.lost_ownership))
        writer.terminate()

    def test_session_signal_ignores_requests_before_the_paste(self) -> None:
        procs: list[FakeXclip] = []

        def popen(args, **kwargs):
            proc = FakeXclip(args, **kwargs)
            procs.append(proc)
            return proc

        with patch("dictate.clipboard_linux.subprocess.Popen", side_effect=popen):
            session = XclipClipboardSession(plain_text=True)
            session.write_text("dictated")

        clipboard, primary = procs
        self.assertIn("primary", primary.args)
        # A clipboard manager reads right after the write.
        clipboard.feed("  Waiting for selection request number 2")
        self.assertTrue(wait_until(lambda: session._writers["clipboard"].served == 1))
        session.before_paste()
        self.assertFalse(session.target_has_read())
        # The terminal reads PRIMARY on Shift+Insert.
        primary.feed("  Waiting for selection request number 2")
        self.assertTrue(wait_until(session.target_has_read))

        # Selecting text replaced PRIMARY; CLIPBOARD still comes back.
        primary.terminate()
        self.assertFalse(session.changed_since_write())
        with patch("dictate.clipboard_linux.subprocess.run", return_value=completed()) as run:
            session.restore(
                {
                    "clipboard": _SavedSelection(ClipboardItem("UTF8_STRING", b"before")),
                    "primary": _SavedSelection(ClipboardItem("UTF8_STRING", b"old selection")),
                }
            )
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["xclip", "-selection", "clipboard", "-t", "UTF8_STRING", "-i"])
        self.assertEqual(run.call_args.kwargs["input"], b"before")
        session.close()
        self.assertIsNotNone(clipboard.poll())
        self.assertTrue(clipboard.stderr_closed and primary.stderr_closed)

    def test_restoring_an_empty_selection_drops_ownership(self) -> None:
        procs: list[FakeXclip] = []

        def popen(args, **kwargs):
            proc = FakeXclip(args, **kwargs)
            procs.append(proc)
            return proc

        with patch("dictate.clipboard_linux.subprocess.Popen", side_effect=popen):
            session = XclipClipboardSession()
            session.write_text("dictated")
        with patch("dictate.clipboard_linux.subprocess.run") as run:
            session.restore({"clipboard": _SavedSelection(None)})
        run.assert_not_called()
        self.assertIsNotNone(procs[0].poll())

    def test_snapshot_reads_targets_then_the_best_one(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            calls.append(args)
            target = args[-1]
            if target == "TARGETS":
                return completed(b"TARGETS\nTIMESTAMP\ntext/html\nUTF8_STRING\nSTRING\n")
            if target == "UTF8_STRING":
                return completed(b"copied text")
            raise AssertionError(args)

        with patch("dictate.clipboard_linux.subprocess.run", side_effect=fake_run):
            saved = XclipClipboardSession().snapshot()

        self.assertEqual(saved["clipboard"].item, ClipboardItem("UTF8_STRING", b"copied text"))
        self.assertEqual(calls[0], ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"])

    def test_snapshot_without_an_owner_is_empty(self) -> None:
        with patch("dictate.clipboard_linux.subprocess.run", return_value=completed(returncode=1)):
            saved = XclipClipboardSession().snapshot()
        self.assertIsNone(saved["clipboard"].item)


def _have_x11_clipboard() -> bool:
    return (
        not sys.platform.startswith("win")
        and bool(os.environ.get("DISPLAY"))
        and shutil.which("xclip") is not None
    )


@unittest.skipUnless(_have_x11_clipboard(), "needs an X display and xclip (CI runs these under Xvfb)")
class RealXclipTests(unittest.TestCase):
    """Real xclip on a real X server. Every owner process is cleaned up."""

    def setUp(self) -> None:
        self._owners: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for owner in self._owners:
            if owner.poll() is None:
                owner.terminate()
                owner.wait(timeout=2)
        subprocess.run(["pkill", "-x", "xclip"], check=False)

    def own(self, selection: str, target: str, data: bytes) -> None:
        owner = subprocess.Popen(
            ["xclip", "-quiet", "-selection", selection, "-t", target, "-i"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert owner.stdin is not None
        owner.stdin.write(data)
        owner.stdin.close()
        self._owners.append(owner)
        self.assertTrue(wait_until(lambda: self.read(selection, "TARGETS") is not None))

    def clear(self, selection: str) -> None:
        self.own(selection, "UTF8_STRING", b"x")
        for owner in self._owners:
            owner.terminate()
            owner.wait(timeout=2)
        subprocess.run(["pkill", "-x", "xclip"], check=False)
        self.assertTrue(wait_until(lambda: self.read(selection, "TARGETS") is None))

    @staticmethod
    def read(selection: str, target: str) -> bytes | None:
        done = subprocess.run(
            ["xclip", "-selection", selection, "-o", "-t", target],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return done.stdout if done.returncode == 0 else None

    def keeper(self, plain_text: bool = False) -> ClipboardKeeper:
        return ClipboardKeeper(
            lambda plain: XclipClipboardSession(plain_text=plain), background=False
        )

    def test_image_comes_back_after_the_target_reads_the_text(self) -> None:
        image = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
        self.own("clipboard", "image/png", image)
        received: list[bytes | None] = []

        readers: list[threading.Thread] = []

        def paste() -> None:
            reader = threading.Thread(
                target=lambda: received.append(self.read("clipboard", "UTF8_STRING"))
            )
            readers.append(reader)
            reader.start()

        keeper = self.keeper()
        keeper.paste("dictated on x11", paste)
        for reader in readers:
            reader.join(5)

        self.assertEqual(received, [b"dictated on x11"])
        self.assertTrue(keeper.last_outcome.read_signal, keeper.last_outcome)
        self.assertTrue(keeper.last_outcome.restored)
        self.assertEqual(self.read("clipboard", "image/png"), image)

    def test_empty_clipboard_is_empty_again(self) -> None:
        self.clear("clipboard")
        received: list[bytes | None] = []

        readers: list[threading.Thread] = []

        def paste() -> None:
            reader = threading.Thread(
                target=lambda: received.append(self.read("clipboard", "UTF8_STRING"))
            )
            readers.append(reader)
            reader.start()

        keeper = self.keeper()
        keeper.paste("dictated on x11", paste)
        for reader in readers:
            reader.join(5)

        self.assertEqual(received, [b"dictated on x11"])
        self.assertTrue(wait_until(lambda: self.read("clipboard", "TARGETS") is None))

    def test_copy_during_the_paste_is_kept(self) -> None:
        self.own("clipboard", "UTF8_STRING", b"before")

        def paste() -> None:
            subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "UTF8_STRING", "-i"],
                input=b"user copy",
                check=True,
            )

        keeper = self.keeper()
        keeper.paste("dictated on x11", paste)

        self.assertTrue(keeper.last_outcome.kept_newer_copy, keeper.last_outcome)
        self.assertEqual(self.read("clipboard", "UTF8_STRING"), b"user copy")

    def test_terminal_paste_restores_primary_and_clipboard(self) -> None:
        self.own("clipboard", "UTF8_STRING", b"clipboard before")
        self.own("primary", "UTF8_STRING", b"primary before")
        received: list[bytes | None] = []

        readers: list[threading.Thread] = []

        def paste() -> None:
            reader = threading.Thread(
                target=lambda: received.append(self.read("primary", "UTF8_STRING"))
            )
            readers.append(reader)
            reader.start()

        keeper = self.keeper()
        keeper.paste("dictated into a terminal", paste, plain_text=True)
        for reader in readers:
            reader.join(5)

        self.assertEqual(received, [b"dictated into a terminal"])
        self.assertTrue(keeper.last_outcome.read_signal)
        self.assertEqual(self.read("clipboard", "UTF8_STRING"), b"clipboard before")
        self.assertEqual(self.read("primary", "UTF8_STRING"), b"primary before")


def _have_wayland_clipboard() -> bool:
    return (
        not sys.platform.startswith("win")
        and bool(os.environ.get("WAYLAND_DISPLAY"))
        and shutil.which("wl-copy") is not None
        and shutil.which("wl-paste") is not None
    )


@unittest.skipUnless(
    _have_wayland_clipboard(),
    "needs a Wayland compositor and wl-clipboard (CI runs these under headless sway)",
)
class RealWaylandTests(unittest.TestCase):
    """Real wl-copy and wl-paste against a real compositor."""

    TEXT = "text/plain;charset=utf-8"

    def tearDown(self) -> None:
        subprocess.run(["wl-copy", "--clear"], check=False)
        subprocess.run(["pkill", "-x", "wl-copy"], check=False)

    @staticmethod
    def copy(data: bytes, mime: str) -> None:
        subprocess.run(["wl-copy", "--type", mime], input=data, check=True, timeout=5)

    @staticmethod
    def read(mime: str) -> bytes | None:
        done = subprocess.run(
            ["wl-paste", "--no-newline", "--type", mime], capture_output=True, timeout=5, check=False
        )
        return done.stdout if done.returncode == 0 else None

    @staticmethod
    def types() -> list[str] | None:
        done = subprocess.run(["wl-paste", "--list-types"], capture_output=True, timeout=5, check=False)
        if done.returncode != 0:
            return None
        return done.stdout.decode().split()

    def paste_with_reader(self, keeper: ClipboardKeeper, text: str) -> list[bytes | None]:
        received: list[bytes | None] = []
        readers: list[threading.Thread] = []

        def paste() -> None:
            reader = threading.Thread(target=lambda: received.append(self.read(self.TEXT)))
            readers.append(reader)
            reader.start()

        keeper.paste(text, paste)
        for reader in readers:
            reader.join(5)
        return received

    @staticmethod
    def keeper() -> ClipboardKeeper:
        return ClipboardKeeper(
            lambda plain: WaylandClipboardSession(plain_text=plain),
            background=False,
            no_signal_delay=0.5,
        )

    def test_image_comes_back_after_the_target_reads_the_text(self) -> None:
        image = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
        self.copy(image, "image/png")

        keeper = self.keeper()
        received = self.paste_with_reader(keeper, "dictated on wayland")

        self.assertEqual(received, [b"dictated on wayland"])
        self.assertTrue(keeper.last_outcome.restored, keeper.last_outcome)
        self.assertEqual(self.read("image/png"), image)

    def test_text_comes_back(self) -> None:
        self.copy("copied before ünïcode".encode(), self.TEXT)

        keeper = self.keeper()
        received = self.paste_with_reader(keeper, "dictated on wayland")

        self.assertEqual(received, [b"dictated on wayland"])
        self.assertEqual(self.read(self.TEXT), "copied before ünïcode".encode())

    def test_empty_clipboard_is_empty_again(self) -> None:
        subprocess.run(["wl-copy", "--clear"], check=True, timeout=5)
        self.assertIsNone(self.types())

        keeper = self.keeper()
        received = self.paste_with_reader(keeper, "dictated on wayland")

        self.assertEqual(received, [b"dictated on wayland"])
        self.assertTrue(keeper.last_outcome.restored)
        self.assertIsNone(self.types())

    def test_copy_during_the_wait_is_kept(self) -> None:
        self.copy(b"before", self.TEXT)

        def paste() -> None:
            threading.Thread(
                target=lambda: (time.sleep(0.1), self.copy(b"user copy", self.TEXT))
            ).start()

        keeper = self.keeper()
        keeper.paste("dictated on wayland", paste)

        self.assertTrue(keeper.last_outcome.kept_newer_copy, keeper.last_outcome)
        self.assertEqual(self.read(self.TEXT), b"user copy")


if __name__ == "__main__":
    unittest.main()
