"""Save, paste and restore logic around a dictation, against a fake clipboard."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from dictate.clipboard_keeper import ClipboardKeeper, best_restorable_type
from dictate.outputs import OutputError, PasteOutput, XdotoolOutput

TEXT = 13
DIB = 8
HDROP = 15
HTML = 0xC0A1


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.events: list[tuple[float, object]] = []

    def __call__(self) -> float:
        return self.now

    def at(self, when: float, action) -> None:
        self.events.append((when, action))
        self.events.sort(key=lambda event: event[0])

    def advance(self, seconds: float) -> None:
        target = self.now + seconds
        while self.events and self.events[0][0] <= target:
            when, action = self.events.pop(0)
            self.now = max(self.now, when)
            action()
        self.now = target


class FakeBoard:
    """The system clipboard: formats, who owns them, and a sequence number."""

    def __init__(self, formats: dict[int, bytes] | None = None) -> None:
        self.formats = dict(formats or {})
        self.owner: object = "someone"
        self.sequence = 1

    def set(self, owner: object, formats: dict[int, bytes]) -> None:
        self.formats = dict(formats)
        self.owner = owner
        self.sequence += 1


class FakeSession:
    settle_seconds = 0.05
    handles_primary = False

    def __init__(self, board: FakeBoard, clock: FakeClock, *, has_read_signal: bool = True) -> None:
        self.board = board
        self.clock = clock
        self.has_read_signal = has_read_signal
        self.read = False
        self.restored_at: float | None = None
        self.closed = False
        self.paste_sent_at: float | None = None
        self.fail_snapshot = False

    def snapshot(self):
        if self.fail_snapshot:
            raise OSError("busy")
        return dict(self.board.formats)

    def write_text(self, text: str) -> None:
        self.board.set(self, {TEXT: text.encode("utf-16-le")})

    def before_paste(self) -> None:
        self.paste_sent_at = self.clock.now

    def target_has_read(self) -> bool:
        return self.read

    def wait(self, seconds: float) -> None:
        self.clock.advance(seconds)

    def changed_since_write(self) -> bool:
        return self.board.owner is not self

    def restore(self, snapshot) -> None:
        self.board.set(self, snapshot)
        self.restored_at = self.clock.now

    def close(self) -> None:
        self.closed = True


class Target:
    """An app that reads the clipboard some time after the paste keystroke."""

    def __init__(self, board: FakeBoard, clock: FakeClock, session: FakeSession, delay: float | None) -> None:
        self.board = board
        self.clock = clock
        self.session = session
        self.delay = delay
        self.received: bytes | None = None
        self.read_at: float | None = None

    def press_paste(self) -> None:
        if self.delay is None:
            return

        def read() -> None:
            self.received = self.board.formats.get(TEXT)
            self.read_at = self.clock.now
            self.session.read = True

        self.clock.at(self.clock.now + self.delay, read)


def make_keeper(session: FakeSession, clock: FakeClock, **kwargs) -> ClipboardKeeper:
    return ClipboardKeeper(lambda plain_text: session, clock=clock, background=False, **kwargs)


class ClipboardKeeperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()

    def run_paste(self, board: FakeBoard, *, delay: float | None = 0.02, **kwargs):
        session = FakeSession(board, self.clock, **{k: kwargs.pop(k) for k in list(kwargs) if k == "has_read_signal"})
        target = Target(board, self.clock, session, delay)
        keeper = make_keeper(session, self.clock, **kwargs)
        keeper.paste("dictated words", target.press_paste)
        return keeper, session, target

    def test_text_image_file_list_and_html_come_back_byte_for_byte(self) -> None:
        before = {
            TEXT: "copied earlier".encode("utf-16-le"),
            DIB: b"BM-header" + bytes(range(64)),
            HDROP: b"\x14\x00\x00\x00" + "C:\\a.txt\0\0".encode("utf-16-le"),
            HTML: b"Version:0.9\r\n<b>hi</b>",
        }
        board = FakeBoard(before)

        keeper, session, target = self.run_paste(board)

        self.assertEqual(target.received, "dictated words".encode("utf-16-le"))
        self.assertEqual(board.formats, before)
        self.assertTrue(keeper.last_outcome.read_signal)
        self.assertTrue(keeper.last_outcome.restored)
        self.assertTrue(session.closed)

    def test_empty_clipboard_is_left_empty(self) -> None:
        board = FakeBoard({})

        keeper, _, target = self.run_paste(board)

        self.assertIsNotNone(target.received)
        self.assertEqual(board.formats, {})
        self.assertTrue(keeper.last_outcome.restored)

    def test_a_copy_made_mid_dictation_is_not_overwritten(self) -> None:
        board = FakeBoard({TEXT: b"old"})
        self.clock.at(0.01, lambda: board.set("user", {TEXT: b"user copy"}))

        keeper, session, _ = self.run_paste(board, delay=None)

        self.assertEqual(board.formats, {TEXT: b"user copy"})
        self.assertTrue(keeper.last_outcome.kept_newer_copy)
        self.assertFalse(keeper.last_outcome.restored)
        self.assertIsNone(session.restored_at)
        # It noticed the copy straight away instead of waiting out the timeout.
        self.assertLess(self.clock.now, 0.1)

    def test_a_copy_made_after_the_target_read_is_not_overwritten(self) -> None:
        board = FakeBoard({TEXT: b"old"})
        self.clock.at(0.03, lambda: board.set("user", {TEXT: b"user copy"}))

        keeper, _, target = self.run_paste(board, delay=0.01)

        self.assertIsNotNone(target.received)
        self.assertEqual(board.formats, {TEXT: b"user copy"})
        self.assertTrue(keeper.last_outcome.kept_newer_copy)

    def test_a_copy_found_by_the_restore_itself_is_kept(self) -> None:
        board = FakeBoard({TEXT: b"old"})

        class LateCopySession(FakeSession):
            def restore(self, snapshot):
                # Someone copied between the keeper's check and the restore.
                self.board.set("user", {TEXT: b"user copy"})
                return False

        session = LateCopySession(board, self.clock)
        target = Target(board, self.clock, session, 0.02)
        keeper = make_keeper(session, self.clock)
        keeper.paste("dictated words", target.press_paste)

        self.assertTrue(keeper.last_outcome.kept_newer_copy)
        self.assertFalse(keeper.last_outcome.restored)
        self.assertEqual(board.formats, {TEXT: b"user copy"})

    def test_restore_waits_for_a_target_that_reads_late(self) -> None:
        board = FakeBoard({TEXT: b"old"})

        keeper, session, target = self.run_paste(board, delay=1.4)

        self.assertEqual(target.received, "dictated words".encode("utf-16-le"))
        self.assertIsNotNone(session.restored_at)
        self.assertGreaterEqual(session.restored_at, target.read_at + session.settle_seconds - 1e-9)
        self.assertFalse(keeper.last_outcome.timed_out)
        self.assertEqual(board.formats, {TEXT: b"old"})

    def test_restore_is_bounded_when_the_target_never_reads(self) -> None:
        board = FakeBoard({TEXT: b"old"})

        keeper, session, _ = self.run_paste(board, delay=None, read_timeout=0.5)

        self.assertTrue(keeper.last_outcome.timed_out)
        self.assertAlmostEqual(session.restored_at, 0.5, places=6)
        self.assertEqual(board.formats, {TEXT: b"old"})

    def test_backend_without_a_read_signal_waits_a_fixed_delay(self) -> None:
        board = FakeBoard({TEXT: b"old"})

        keeper, session, target = self.run_paste(
            board, delay=0.3, has_read_signal=False, no_signal_delay=0.75
        )

        self.assertIsNotNone(target.received)
        self.assertAlmostEqual(session.restored_at, 0.75, places=6)
        self.assertEqual(board.formats, {TEXT: b"old"})

    def test_a_failed_paste_restores_at_once_and_reports_the_error(self) -> None:
        board = FakeBoard({TEXT: b"old"})
        session = FakeSession(board, self.clock)
        keeper = make_keeper(session, self.clock)

        def fail() -> None:
            raise OutputError("pynput paste failed")

        with self.assertRaises(OutputError):
            keeper.paste("dictated words", fail)

        self.assertEqual(board.formats, {TEXT: b"old"})
        self.assertEqual(session.restored_at, 0.0)
        self.assertTrue(session.closed)

    def test_dictation_still_pastes_when_the_clipboard_cannot_be_saved(self) -> None:
        board = FakeBoard({TEXT: b"old"})
        session = FakeSession(board, self.clock)
        session.fail_snapshot = True
        target = Target(board, self.clock, session, 0.02)
        keeper = make_keeper(session, self.clock)

        with self.assertLogs("dictate.clipboard_keeper", level="WARNING") as logs:
            keeper.paste("dictated words", target.press_paste)

        self.assertIsNotNone(target.received)
        self.assertFalse(keeper.last_outcome.saved)
        self.assertIsNone(session.restored_at)
        self.assertNotIn("dictated words", "\n".join(logs.output))

    def test_logs_never_carry_clipboard_contents(self) -> None:
        board = FakeBoard({TEXT: b"secret old copy"})
        session = FakeSession(board, self.clock)
        target = Target(board, self.clock, session, 0.02)
        keeper = make_keeper(session, self.clock)

        with self.assertLogs("dictate.clipboard_keeper", level="DEBUG") as logs:
            keeper.paste("secret dictated words", target.press_paste)

        joined = "\n".join(logs.output)
        self.assertNotIn("secret", joined)

    def test_background_paste_returns_before_restore_and_serializes(self) -> None:
        board = FakeBoard({TEXT: b"old"})
        order: list[str] = []
        lock = threading.Lock()

        class SlowSession(FakeSession):
            def wait(self, seconds: float) -> None:
                time.sleep(min(seconds, 0.01))
                self.clock.now += seconds

            def restore(self, snapshot) -> None:
                with lock:
                    order.append("restore")
                super().restore(snapshot)

            def snapshot(self):
                with lock:
                    order.append("snapshot")
                return super().snapshot()

        clock = FakeClock()
        keeper = ClipboardKeeper(
            lambda plain_text: SlowSession(board, clock, has_read_signal=False),
            no_signal_delay=0.05,
            clock=clock,
        )
        keeper.paste("one", lambda: None)
        keeper.paste("two", lambda: None)
        self.assertTrue(keeper.wait_idle(5))

        self.assertEqual(order, ["snapshot", "restore", "snapshot", "restore"])
        self.assertEqual(board.formats, {TEXT: b"old"})

    def test_write_errors_reach_the_caller_in_background_mode(self) -> None:
        session = MagicMock()
        session.write_text.side_effect = OutputError("clipboard command failed: busy")
        keeper = ClipboardKeeper(lambda plain_text: session)

        with self.assertRaises(OutputError):
            keeper.paste("words", lambda: None)
        keeper.wait_idle(5)
        session.close.assert_called_once()


class BestRestorableTypeTests(unittest.TestCase):
    def test_prefers_png_then_any_image(self) -> None:
        self.assertEqual(
            best_restorable_type(["TARGETS", "text/html", "image/jpeg", "image/png"]), "image/png"
        )
        self.assertEqual(best_restorable_type(["text/html", "image/bmp"]), "image/bmp")

    def test_prefers_utf8_text(self) -> None:
        self.assertEqual(
            best_restorable_type(["TIMESTAMP", "TARGETS", "STRING", "UTF8_STRING", "text/html"]),
            "UTF8_STRING",
        )
        self.assertEqual(
            best_restorable_type(["text/plain", "text/plain;charset=utf-8"]),
            "text/plain;charset=utf-8",
        )

    def test_falls_back_to_the_first_offered_type(self) -> None:
        self.assertEqual(best_restorable_type(["TARGETS", "application/x-thing"]), "application/x-thing")
        self.assertIsNone(best_restorable_type(["TARGETS", "TIMESTAMP"]))
        self.assertIsNone(best_restorable_type([]))


class PasteOutputKeeperTests(unittest.TestCase):
    def test_paste_output_goes_through_the_keeper(self) -> None:
        keeper = MagicMock()
        typing = XdotoolOutput()
        clipboard = MagicMock()
        with (
            patch("dictate.outputs._focused_window_wants_plain_paste", return_value=False),
            patch("dictate.outputs._send_paste_shortcut") as shortcut,
        ):
            PasteOutput(typing, clipboard, keeper).send("complete dictation")
            args, kwargs = keeper.paste.call_args
            self.assertEqual(args[0], "complete dictation")
            self.assertFalse(kwargs["plain_text"])
            args[1]()

        shortcut.assert_called_once_with(typing, plain_text=False)
        clipboard.send.assert_not_called()

    def test_terminal_paste_asks_the_keeper_for_primary(self) -> None:
        keeper = MagicMock()
        with patch("dictate.outputs._focused_window_wants_plain_paste", return_value=True):
            PasteOutput(XdotoolOutput(), MagicMock(), keeper).send("hello")

        self.assertTrue(keeper.paste.call_args.kwargs["plain_text"])

    def test_primary_falls_back_to_xclip_when_the_session_cannot_restore_it(self) -> None:
        keeper = MagicMock()
        with patch("dictate.outputs._focused_window_wants_plain_paste", return_value=True):
            PasteOutput(XdotoolOutput(), MagicMock(), keeper).send("hello")
        after_write = keeper.paste.call_args.kwargs["after_write"]

        with (
            patch("dictate.outputs.command_exists", return_value=True),
            patch("dictate.outputs._set_x_selection") as selection,
        ):
            after_write(MagicMock(handles_primary=False))
            selection.assert_called_once_with("primary", "hello")
            selection.reset_mock()
            after_write(MagicMock(handles_primary=True))
            selection.assert_not_called()

    def test_falls_back_to_a_plain_paste_when_the_session_cannot_start(self) -> None:
        def broken(plain_text: bool):
            raise OSError("no window")

        keeper = ClipboardKeeper(broken)
        clipboard = MagicMock()
        typing = XdotoolOutput()
        with (
            patch("dictate.outputs._focused_window_wants_plain_paste", return_value=False),
            patch("dictate.outputs._send_paste_shortcut") as shortcut,
            self.assertLogs("dictate.outputs", level="WARNING"),
        ):
            PasteOutput(typing, clipboard, keeper).send("hello")

        clipboard.send.assert_called_once_with("hello")
        shortcut.assert_called_once_with(typing, plain_text=False)

    def test_real_paste_through_a_keeper_restores_the_fake_clipboard(self) -> None:
        clock = FakeClock()
        board = FakeBoard({TEXT: b"old"})
        session = FakeSession(board, clock)
        target = Target(board, clock, session, 0.02)
        keeper = make_keeper(session, clock)
        with (
            patch("dictate.outputs._focused_window_wants_plain_paste", return_value=False),
            patch("dictate.outputs._send_paste_shortcut", side_effect=lambda *a, **k: target.press_paste()),
        ):
            PasteOutput(XdotoolOutput(), MagicMock(), keeper).send("hello there")

        self.assertEqual(target.received, "hello there".encode("utf-16-le"))
        self.assertEqual(board.formats, {TEXT: b"old"})


if __name__ == "__main__":
    unittest.main()
