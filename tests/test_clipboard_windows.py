"""The real Windows clipboard around a paste (ctypes, no fakes).

These run on the windows-latest CI runner. If the runner has no usable
clipboard they skip and say so; ``scripts/windows-clipboard-smoke.ps1`` is the
manual check for a desktop session.
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

from dictate.clipboard_keeper import ClipboardKeeper
from dictate.clipboard_windows import (
    CF_BITMAP,
    CF_DIB,
    CF_ENHMETAFILE,
    CF_HDROP,
    CF_OWNERDISPLAY,
    CF_PALETTE,
    CF_UNICODETEXT,
    format_is_copyable,
)

IS_WINDOWS = sys.platform.startswith("win")

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_QUIT = 0x0012
WM_PASTE = 0x0302
WS_POPUP = 0x80000000
ES_MULTILINE = 0x0004

TEXT_BEFORE = "copied before dictation\r\nline two"
DICTATED = "dictated words for issue 149"


class FormatSelectionTests(unittest.TestCase):
    def test_handle_formats_are_skipped_and_data_formats_kept(self) -> None:
        for fmt in (CF_BITMAP, CF_PALETTE, CF_OWNERDISPLAY, 0x0200, 0x02FF, 0x0300, 0x03FF):
            self.assertFalse(format_is_copyable(fmt), hex(fmt))
        for fmt in (CF_UNICODETEXT, CF_DIB, 17, CF_HDROP, CF_ENHMETAFILE, 16, 0xC000, 0xC1FF):
            self.assertTrue(format_is_copyable(fmt), hex(fmt))


def _unicode(text: str) -> bytes:
    return (text + "\0").encode("utf-16-le")


def _dib() -> bytes:
    header = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 32, 0, 16, 2835, 2835, 0, 0)
    return header + bytes([0x10, 0x20, 0x30, 0x00]) * 4


def _hdrop() -> bytes:
    # DROPFILES: pFiles, pt.x, pt.y, fNC, fWide; then a double-NUL list of paths.
    return struct.pack("<IiiII", 20, 0, 0, 0, 1) + "C:\\Windows\\win.ini\0\0".encode("utf-16-le")


if IS_WINDOWS:
    from ctypes import wintypes

    from dictate import clipboard_windows as cw

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _GetMessageW = _user32.GetMessageW
    _GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _GetMessageW.restype = wintypes.BOOL
    _PostMessageW = _user32.PostMessageW
    _PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _PostMessageW.restype = wintypes.BOOL
    _SendMessageW = _user32.SendMessageW
    _SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _SendMessageW.restype = ctypes.c_ssize_t
    _PostThreadMessageW = _user32.PostThreadMessageW
    _PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _PostThreadMessageW.restype = wintypes.BOOL
    _GetCurrentThreadId = ctypes.WinDLL("kernel32").GetCurrentThreadId
    _GetCurrentThreadId.restype = wintypes.DWORD
    _CountClipboardFormats = _user32.CountClipboardFormats
    _CountClipboardFormats.restype = ctypes.c_int


def _open_with(win, hwnd: int) -> None:
    deadline = time.monotonic() + 2.0
    while not win.OpenClipboard(hwnd):
        if time.monotonic() > deadline:
            raise OSError("could not open the clipboard")
        time.sleep(0.01)


def put_clipboard(formats: dict[int, bytes]) -> None:
    """Replace the clipboard with these formats, from whatever thread calls it."""
    win = cw.api()
    holder = cw.WindowsClipboardSession()
    try:
        _open_with(win, holder.hwnd)
        try:
            if not win.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            for fmt, data in formats.items():
                handle = cw._hglobal_from_bytes(win, data)
                if not win.SetClipboardData(fmt, handle):
                    win.GlobalFree(handle)
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            win.CloseClipboard()
    finally:
        holder.close()


class TargetApp:
    """Reads the clipboard like a paste target, on its own thread and window."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.text: str | None = None
        self.format_names: set[str] = set()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name="fake-paste-target")

    def press_paste(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        try:
            time.sleep(self.delay)
            win = cw.api()
            holder = cw.WindowsClipboardSession()
            try:
                _open_with(win, holder.hwnd)
                try:
                    fmt = 0
                    while True:
                        fmt = win.EnumClipboardFormats(fmt)
                        if not fmt:
                            break
                        name = cw._format_name(win, fmt)
                        if name:
                            self.format_names.add(name)
                    handle = win.GetClipboardData(CF_UNICODETEXT)
                    data = cw._read_hglobal(win, handle) if handle else None
                    if data is not None:
                        self.text = data.decode("utf-16-le").split("\0", 1)[0]
                finally:
                    win.CloseClipboard()
            finally:
                holder.close()
        except BaseException as exc:  # noqa: BLE001
            self.error = exc


class EditControl:
    """A real Win32 EDIT control on its own thread with a message loop."""

    def __init__(self) -> None:
        self.hwnd = 0
        self._thread_id = 0
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="edit-control", daemon=True)
        self._thread.start()
        if not self._ready.wait(5) or not self.hwnd:
            raise OSError("EDIT control did not start")

    def _run(self) -> None:
        win = cw.api()
        self._thread_id = _GetCurrentThreadId()
        self.hwnd = win.CreateWindowExW(
            0, "EDIT", "", WS_POPUP | ES_MULTILINE, 0, 0, 200, 100, None, None,
            win.GetModuleHandleW(None), None,
        ) or 0
        self._ready.set()
        msg = wintypes.MSG()
        while _GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            win.TranslateMessage(ctypes.byref(msg))
            win.DispatchMessageW(ctypes.byref(msg))
        if self.hwnd:
            win.DestroyWindow(self.hwnd)

    def paste(self) -> None:
        _PostMessageW(self.hwnd, WM_PASTE, 0, 0)

    def text(self) -> str:
        length = _SendMessageW(self.hwnd, WM_GETTEXTLENGTH, 0, 0)
        buffer = ctypes.create_unicode_buffer(length + 1)
        _SendMessageW(self.hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buffer))
        return buffer.value

    def close(self) -> None:
        _PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(5)


def _clipboard_unavailable_reason() -> str | None:
    if not IS_WINDOWS:
        return "Windows only"
    try:
        put_clipboard({CF_UNICODETEXT: _unicode("probe")})
        formats = cw.read_clipboard_formats()
    except OSError as exc:
        return f"the clipboard API is not usable on this machine: {exc}"
    if formats.get(CF_UNICODETEXT) != _unicode("probe"):
        return "the clipboard API is not usable on this machine: write did not read back"
    return None


_SKIP_REASON = _clipboard_unavailable_reason() if IS_WINDOWS else "Windows only"


@unittest.skipIf(_SKIP_REASON is not None, _SKIP_REASON or "")
class WindowsClipboardRoundTripTests(unittest.TestCase):
    def keeper(self, **kwargs) -> ClipboardKeeper:
        own_pid = os.getpid()
        return ClipboardKeeper(
            lambda plain_text: cw.WindowsClipboardSession(target_pids=lambda: {own_pid}),
            background=False,
            **kwargs,
        )

    def put_mixed(self) -> dict[int, bytes]:
        win = cw.api()
        formats = {
            CF_UNICODETEXT: _unicode(TEXT_BEFORE),
            CF_DIB: _dib(),
            CF_HDROP: _hdrop(),
            win.RegisterClipboardFormatW("HTML Format"): b"Version:0.9\r\nStartHTML:0\r\n<b>bold</b>\0",
            win.RegisterClipboardFormatW("Rich Text Format"): b"{\\rtf1 {\\b bold}}\0",
            win.RegisterClipboardFormatW("Dictate Test Format"): bytes(range(256)),
        }
        put_clipboard(formats)
        before = cw.read_clipboard_formats()
        for fmt, data in formats.items():
            self.assertEqual(before.get(fmt), data, hex(fmt))
        return before

    def assert_unchanged(self, before: dict[int, bytes]) -> None:
        after = cw.read_clipboard_formats()
        for fmt, data in before.items():
            self.assertEqual(after.get(fmt), data, f"format {fmt:#x} changed")
        marker = cw.api().RegisterClipboardFormatW(cw.EXCLUDE_FROM_MONITORS)
        self.assertLessEqual(set(after) - set(before), {marker})

    def test_text_image_file_list_html_rtf_and_custom_formats_round_trip(self) -> None:
        before = self.put_mixed()
        target = TargetApp(delay=0.05)

        keeper = self.keeper()
        keeper.paste(DICTATED, target.press_paste)
        target.thread.join(5)

        self.assertIsNone(target.error)
        self.assertEqual(target.text, DICTATED)
        self.assertTrue(
            {cw.EXCLUDE_FROM_MONITORS, cw.CAN_INCLUDE_IN_HISTORY, cw.CAN_UPLOAD_TO_CLOUD}
            <= target.format_names,
            target.format_names,
        )
        outcome = keeper.last_outcome
        self.assertTrue(outcome.read_signal, outcome)
        self.assertTrue(outcome.restored, outcome)
        self.assert_unchanged(before)

    def test_empty_clipboard_is_empty_afterwards(self) -> None:
        put_clipboard({})
        self.assertEqual(_CountClipboardFormats(), 0)
        target = TargetApp(delay=0.02)

        keeper = self.keeper()
        keeper.paste(DICTATED, target.press_paste)
        target.thread.join(5)

        self.assertEqual(target.text, DICTATED)
        self.assertTrue(keeper.last_outcome.restored)
        self.assertEqual(_CountClipboardFormats(), 0)

    def test_copy_made_mid_dictation_is_kept(self) -> None:
        self.put_mixed()
        user_copy = threading.Thread(
            target=lambda: (time.sleep(0.05), put_clipboard({CF_UNICODETEXT: _unicode("user copy")}))
        )

        keeper = self.keeper()
        keeper.paste(DICTATED, user_copy.start)
        user_copy.join(5)

        self.assertTrue(keeper.last_outcome.kept_newer_copy, keeper.last_outcome)
        self.assertFalse(keeper.last_outcome.restored)
        self.assertEqual(cw.read_clipboard_formats().get(CF_UNICODETEXT), _unicode("user copy"))

    def test_restore_waits_for_a_target_that_reads_late(self) -> None:
        before = self.put_mixed()
        target = TargetApp(delay=0.6)

        keeper = self.keeper(read_timeout=3.0)
        started = time.monotonic()
        keeper.paste(DICTATED, target.press_paste)
        target.thread.join(5)

        self.assertEqual(target.text, DICTATED)
        self.assertTrue(keeper.last_outcome.read_signal)
        self.assertGreaterEqual(time.monotonic() - started, 0.6)
        self.assert_unchanged(before)

    def test_restore_is_bounded_when_nothing_reads(self) -> None:
        before = self.put_mixed()

        keeper = self.keeper(read_timeout=0.3)
        started = time.monotonic()
        keeper.paste(DICTATED, lambda: None)

        self.assertTrue(keeper.last_outcome.timed_out)
        self.assertLess(time.monotonic() - started, 3.0)
        self.assert_unchanged(before)

    def test_paste_output_into_an_edit_control_leaves_the_clipboard_as_it_was(self) -> None:
        from dictate.outputs import ClipboardOutput, PasteOutput, PynputOutput

        before = self.put_mixed()
        edit = EditControl()
        own_pid = os.getpid()
        keeper = ClipboardKeeper(
            lambda plain_text: cw.WindowsClipboardSession(target_pids=lambda: {own_pid})
        )
        try:
            with patch("dictate.outputs._send_paste_shortcut", side_effect=lambda *a, **k: edit.paste()):
                PasteOutput(PynputOutput(), ClipboardOutput(), keeper).send(DICTATED)
                self.assertTrue(keeper.wait_idle(10))
            pasted = edit.text()
        finally:
            edit.close()

        self.assertEqual(pasted, DICTATED)
        self.assertTrue(keeper.last_outcome.read_signal, keeper.last_outcome)
        self.assertTrue(keeper.last_outcome.restored, keeper.last_outcome)
        self.assert_unchanged(before)


if __name__ == "__main__":
    unittest.main()
