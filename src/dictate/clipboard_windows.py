"""Clipboard save and restore on Windows through the Win32 clipboard API (ctypes).

Every format the clipboard holds is copied before Dictate writes, except the
ones whose data is a GDI or owner-drawn handle that cannot be duplicated as
bytes (CF_BITMAP, CF_PALETTE, CF_METAFILEPICT, owner-display and private/GDI
ranges). Windows synthesizes CF_BITMAP from CF_DIB/CF_DIBV5 again after the
restore. Enhanced metafiles are copied through their bits.

The dictated text is offered by delayed rendering: Windows asks Dictate's
window for it (WM_RENDERFORMAT) when an app first reads it, which is the
signal that the paste target has the text. It is marked so clipboard history
(Win+V) and cloud clipboard do not record it.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dictate.clipboard_keeper import ClipboardItem

CF_TEXT = 1
CF_BITMAP = 2
CF_METAFILEPICT = 3
CF_OEMTEXT = 7
CF_DIB = 8
CF_PALETTE = 9
CF_UNICODETEXT = 13
CF_ENHMETAFILE = 14
CF_HDROP = 15
CF_LOCALE = 16
CF_DIBV5 = 17
CF_OWNERDISPLAY = 0x0080
CF_DSPBITMAP = 0x0082
CF_DSPMETAFILEPICT = 0x0083
CF_DSPENHMETAFILE = 0x008E
CF_PRIVATEFIRST = 0x0200
CF_GDIOBJLAST = 0x03FF

# Data in these formats is a handle to a GDI object, or is drawn by the owner.
_HANDLE_FORMATS = {
    CF_BITMAP,
    CF_METAFILEPICT,
    CF_PALETTE,
    CF_OWNERDISPLAY,
    CF_DSPBITMAP,
    CF_DSPMETAFILEPICT,
    CF_DSPENHMETAFILE,
}
# OLE's own plumbing: points at the source app's live data object. Copying it
# would make a later paste talk to that object instead of the saved formats.
_SKIPPED_NAMES = {"DataObject", "Ole Private Data"}

EXCLUDE_FROM_MONITORS = "ExcludeClipboardContentFromMonitorProcessing"
CAN_INCLUDE_IN_HISTORY = "CanIncludeInClipboardHistory"
CAN_UPLOAD_TO_CLOUD = "CanUploadToCloudClipboard"

WM_RENDERFORMAT = 0x0305
WM_RENDERALLFORMATS = 0x0306
WM_DESTROYCLIPBOARD = 0x0307
GMEM_MOVEABLE = 0x0002
HWND_MESSAGE = -3
QS_ALLINPUT = 0x04FF
PM_REMOVE = 0x0001
ERROR_CLASS_ALREADY_EXISTS = 1410

_OPEN_TIMEOUT_SECONDS = 1.0
_PRE_PASTE_SETTLE_SECONDS = 0.02
_PRE_PASTE_MAX_SECONDS = 0.1
_CLASS_NAME = "DictateClipboardKeeper"


def format_is_copyable(fmt: int) -> bool:
    if fmt in _HANDLE_FORMATS:
        return False
    return not CF_PRIVATEFIRST <= fmt <= CF_GDIOBJLAST


class ClipboardBusyError(OSError):
    """Another app kept the clipboard open."""


class _Api:
    """user32/kernel32/gdi32 entry points with explicit prototypes.

    Private WinDLL instances, so the prototypes here never change the ones
    other modules (pynput, the tray) set on ``ctypes.windll``.
    """

    def __init__(self) -> None:
        from ctypes import wintypes

        self.wt = wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        HANDLE = wintypes.HANDLE
        HWND = wintypes.HWND
        UINT = wintypes.UINT
        BOOL = wintypes.BOOL
        LRESULT = ctypes.c_ssize_t
        self.LRESULT = LRESULT

        self.WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", UINT),
                ("lpfnWndProc", self.WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hwndActive", HWND),
                ("hwndFocus", HWND),
                ("hwndCapture", HWND),
                ("hwndMenuOwner", HWND),
                ("hwndMoveSize", HWND),
                ("hwndCaret", HWND),
                ("rcCaret", wintypes.RECT),
            ]

        self.WNDCLASSW = WNDCLASSW
        self.GUITHREADINFO = GUITHREADINFO
        self.MSG = wintypes.MSG

        def proto(dll: Any, name: str, restype: Any, *argtypes: Any) -> Any:
            fn = getattr(dll, name)
            fn.restype = restype
            fn.argtypes = list(argtypes)
            return fn

        self.OpenClipboard = proto(user32, "OpenClipboard", BOOL, HWND)
        self.CloseClipboard = proto(user32, "CloseClipboard", BOOL)
        self.EmptyClipboard = proto(user32, "EmptyClipboard", BOOL)
        self.EnumClipboardFormats = proto(user32, "EnumClipboardFormats", UINT, UINT)
        self.CountClipboardFormats = proto(user32, "CountClipboardFormats", ctypes.c_int)
        self.GetClipboardData = proto(user32, "GetClipboardData", HANDLE, UINT)
        self.SetClipboardData = proto(user32, "SetClipboardData", HANDLE, UINT, HANDLE)
        self.GetClipboardSequenceNumber = proto(user32, "GetClipboardSequenceNumber", wintypes.DWORD)
        self.GetClipboardOwner = proto(user32, "GetClipboardOwner", HWND)
        self.GetOpenClipboardWindow = proto(user32, "GetOpenClipboardWindow", HWND)
        self.RegisterClipboardFormatW = proto(user32, "RegisterClipboardFormatW", UINT, wintypes.LPCWSTR)
        self.GetClipboardFormatNameW = proto(
            user32, "GetClipboardFormatNameW", ctypes.c_int, UINT, wintypes.LPWSTR, ctypes.c_int
        )
        self.RegisterClassW = proto(user32, "RegisterClassW", wintypes.ATOM, ctypes.POINTER(WNDCLASSW))
        self.CreateWindowExW = proto(
            user32,
            "CreateWindowExW",
            HWND,
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            ctypes.c_void_p,
        )
        self.DestroyWindow = proto(user32, "DestroyWindow", BOOL, HWND)
        self.DefWindowProcW = proto(
            user32, "DefWindowProcW", LRESULT, HWND, UINT, wintypes.WPARAM, wintypes.LPARAM
        )
        self.PeekMessageW = proto(
            user32, "PeekMessageW", BOOL, ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT, UINT
        )
        self.TranslateMessage = proto(user32, "TranslateMessage", BOOL, ctypes.POINTER(wintypes.MSG))
        self.DispatchMessageW = proto(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(wintypes.MSG))
        self.MsgWaitForMultipleObjects = proto(
            user32,
            "MsgWaitForMultipleObjects",
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            BOOL,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        self.GetForegroundWindow = proto(user32, "GetForegroundWindow", HWND)
        self.GetGUIThreadInfo = proto(
            user32, "GetGUIThreadInfo", BOOL, wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)
        )
        self.GetWindowThreadProcessId = proto(
            user32, "GetWindowThreadProcessId", wintypes.DWORD, HWND, ctypes.POINTER(wintypes.DWORD)
        )

        self.GetModuleHandleW = proto(kernel32, "GetModuleHandleW", wintypes.HMODULE, wintypes.LPCWSTR)
        self.GlobalAlloc = proto(kernel32, "GlobalAlloc", HANDLE, UINT, ctypes.c_size_t)
        self.GlobalFree = proto(kernel32, "GlobalFree", HANDLE, HANDLE)
        self.GlobalLock = proto(kernel32, "GlobalLock", ctypes.c_void_p, HANDLE)
        self.GlobalUnlock = proto(kernel32, "GlobalUnlock", BOOL, HANDLE)
        self.GlobalSize = proto(kernel32, "GlobalSize", ctypes.c_size_t, HANDLE)

        self.GetEnhMetaFileBits = proto(
            gdi32, "GetEnhMetaFileBits", UINT, HANDLE, UINT, ctypes.c_void_p
        )
        self.SetEnhMetaFileBits = proto(gdi32, "SetEnhMetaFileBits", HANDLE, UINT, ctypes.c_char_p)
        self.DeleteEnhMetaFile = proto(gdi32, "DeleteEnhMetaFile", BOOL, HANDLE)


_api_instance: _Api | None = None
_api_lock = threading.Lock()
_class_registered = False
_wndproc_ref: Any = None
_sessions: dict[int, "WindowsClipboardSession"] = {}


def api() -> _Api:
    global _api_instance
    if not sys.platform.startswith("win"):
        raise OSError("the Windows clipboard is only available on Windows")
    with _api_lock:
        if _api_instance is None:
            _api_instance = _Api()
        return _api_instance


def _last_error() -> OSError:
    return ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]


def _wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    session = _sessions.get(hwnd or 0)
    try:
        if session is not None:
            if msg == WM_RENDERFORMAT:
                session._on_render_format(int(wparam))
                return 0
            if msg == WM_RENDERALLFORMATS:
                session._on_render_all_formats()
                return 0
            if msg == WM_DESTROYCLIPBOARD:
                session._on_destroy_clipboard()
                return 0
    except Exception:  # noqa: BLE001
        # Never let an exception unwind through the window procedure.
        return 0
    win = _api_instance
    if win is None:
        return 0
    return win.DefWindowProcW(hwnd, msg, wparam, lparam)


def _ensure_window_class(win: _Api) -> None:
    global _class_registered, _wndproc_ref
    with _api_lock:
        if _class_registered:
            return
        _wndproc_ref = win.WNDPROC(_wndproc)
        wc = win.WNDCLASSW()
        wc.lpfnWndProc = _wndproc_ref
        wc.hInstance = win.GetModuleHandleW(None)
        wc.lpszClassName = _CLASS_NAME
        if not win.RegisterClassW(ctypes.byref(wc)):
            if ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS:  # type: ignore[attr-defined]
                raise _last_error()
        _class_registered = True


def _format_name(win: _Api, fmt: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    length = win.GetClipboardFormatNameW(fmt, buffer, len(buffer))
    return buffer.value[:length] if length > 0 else ""


def _read_hglobal(win: _Api, handle: int) -> bytes | None:
    size = win.GlobalSize(handle)
    if size == 0:
        return b""
    pointer = win.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.string_at(pointer, size)
    finally:
        win.GlobalUnlock(handle)


def _hglobal_from_bytes(win: _Api, data: bytes) -> int:
    handle = win.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise _last_error()
    if data:
        pointer = win.GlobalLock(handle)
        if not pointer:
            win.GlobalFree(handle)
            raise _last_error()
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            win.GlobalUnlock(handle)
    return handle


def _pid_of(win: _Api, hwnd: int | None) -> int:
    if not hwnd:
        return 0
    pid = win.wt.DWORD(0)
    win.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def foreground_pids() -> set[int]:
    """Processes behind the foreground window and its focused control."""
    win = api()
    pids = {_pid_of(win, win.GetForegroundWindow())}
    info = win.GUITHREADINFO()
    info.cbSize = ctypes.sizeof(win.GUITHREADINFO)
    if win.GetGUIThreadInfo(0, ctypes.byref(info)):
        pids.add(_pid_of(win, info.hwndFocus))
        pids.add(_pid_of(win, info.hwndActive))
    pids.discard(0)
    return pids


@dataclass(frozen=True, slots=True)
class WindowsSnapshot:
    items: tuple[ClipboardItem, ...]
    skipped: int = 0

    @property
    def empty(self) -> bool:
        return not self.items


class WindowsClipboardSession:
    """One dictation's clipboard transaction. Create, use and close on one thread."""

    has_read_signal = True
    settle_seconds = 0.05
    handles_primary = False

    def __init__(self, *, target_pids: Callable[[], set[int]] | None = None) -> None:
        self._win = api()
        _ensure_window_class(self._win)
        self._target_pids = target_pids or foreground_pids
        self._text: str | None = None
        self._armed = False
        self._restoring = False
        self._lost = False
        self._rendered = False
        self._read_by_target = False
        self._own_sequence: int | None = None
        hwnd = self._win.CreateWindowExW(
            0,
            _CLASS_NAME,
            "Dictate clipboard",
            0,
            0,
            0,
            0,
            0,
            self._win.wt.HWND(HWND_MESSAGE),
            None,
            self._win.GetModuleHandleW(None),
            None,
        )
        if not hwnd:
            raise _last_error()
        self.hwnd: int = hwnd
        _sessions[hwnd] = self

    # -- clipboard access -------------------------------------------------

    def _open(self) -> None:
        deadline = time.monotonic() + _OPEN_TIMEOUT_SECONDS
        while not self._win.OpenClipboard(self.hwnd):
            if time.monotonic() >= deadline:
                raise ClipboardBusyError("the clipboard is held open by another app")
            # Keep answering render requests while another app has it open.
            self.wait(0.01)

    def snapshot(self) -> WindowsSnapshot:
        win = self._win
        self._open()
        try:
            items: list[ClipboardItem] = []
            skipped = 0
            fmt = 0
            while True:
                ctypes.set_last_error(0)  # type: ignore[attr-defined]
                fmt = win.EnumClipboardFormats(fmt)
                if not fmt:
                    error = ctypes.get_last_error()  # type: ignore[attr-defined]
                    if error:
                        raise ctypes.WinError(error)  # type: ignore[attr-defined]
                    break
                item = self._copy_format(fmt)
                if item is None:
                    skipped += 1
                else:
                    items.append(item)
            return WindowsSnapshot(tuple(items), skipped)
        finally:
            win.CloseClipboard()

    def _copy_format(self, fmt: int) -> ClipboardItem | None:
        win = self._win
        if not format_is_copyable(fmt):
            return None
        name = _format_name(win, fmt)
        if name in _SKIPPED_NAMES:
            return None
        handle = win.GetClipboardData(fmt)
        if not handle:
            return None
        if fmt == CF_ENHMETAFILE:
            size = win.GetEnhMetaFileBits(handle, 0, None)
            if not size:
                return None
            buffer = ctypes.create_string_buffer(size)
            if win.GetEnhMetaFileBits(handle, size, buffer) != size:
                return None
            return ClipboardItem(fmt, buffer.raw, name, "emf")
        data = _read_hglobal(win, handle)
        if data is None:
            return None
        return ClipboardItem(fmt, data, name, "hglobal")

    def write_text(self, text: str) -> None:
        win = self._win
        self._text = text
        try:
            self._open()
        except ClipboardBusyError as exc:
            from dictate.outputs import OutputError

            raise OutputError(f"clipboard command failed: {exc}") from exc
        try:
            if not win.EmptyClipboard():
                raise _last_error()
            # Delayed rendering: Windows asks this window for the text when an
            # app reads it, which tells us the paste has been picked up.
            win.SetClipboardData(CF_UNICODETEXT, None)
            for marker in (EXCLUDE_FROM_MONITORS, CAN_INCLUDE_IN_HISTORY, CAN_UPLOAD_TO_CLOUD):
                self._set_bytes(win.RegisterClipboardFormatW(marker), b"\0\0\0\0")
        finally:
            win.CloseClipboard()
        self._own_sequence = int(win.GetClipboardSequenceNumber())
        self._armed = True

    def _set_bytes(self, fmt: int, data: bytes) -> None:
        handle = _hglobal_from_bytes(self._win, data)
        if not self._win.SetClipboardData(fmt, handle):
            self._win.GlobalFree(handle)

    def _set_item(self, item: ClipboardItem) -> None:
        win = self._win
        if item.kind == "emf":
            handle = win.SetEnhMetaFileBits(len(item.data), item.data)
            if handle and not win.SetClipboardData(int(item.format), handle):
                win.DeleteEnhMetaFile(handle)
            return
        self._set_bytes(int(item.format), item.data)

    # -- window messages --------------------------------------------------

    def _render_text(self) -> bool:
        if self._text is None:
            return False
        data = (self._text + "\0").encode("utf-16-le")
        handle = _hglobal_from_bytes(self._win, data)
        if not self._win.SetClipboardData(CF_UNICODETEXT, handle):
            self._win.GlobalFree(handle)
            return False
        return True

    def _on_render_format(self, fmt: int) -> None:
        if fmt != CF_UNICODETEXT or not self._render_text():
            return
        self._rendered = True
        requester = _pid_of(self._win, self._win.GetOpenClipboardWindow())
        try:
            targets = self._target_pids()
        except Exception:  # noqa: BLE001
            targets = set()
        if requester and requester in targets:
            self._read_by_target = True

    def _on_render_all_formats(self) -> None:
        # The window is going away while still owning unrendered text.
        if not self._win.OpenClipboard(self.hwnd):
            return
        try:
            if self._win.GetClipboardOwner() == self.hwnd:
                self._render_text()
        finally:
            self._win.CloseClipboard()

    def _on_destroy_clipboard(self) -> None:
        if self._armed and not self._restoring:
            self._lost = True

    # -- keeper interface -------------------------------------------------

    def before_paste(self) -> None:
        # Apps that watch the clipboard react to the write by opening it, and
        # may ask this window to render the text. Serve them before the
        # keystroke, so the paste target does not find the clipboard held open
        # (an app whose OpenClipboard fails pastes nothing).
        self.wait(_PRE_PASTE_SETTLE_SECONDS)
        deadline = time.monotonic() + _PRE_PASTE_MAX_SECONDS
        while self._win.GetOpenClipboardWindow() and time.monotonic() < deadline:
            self.wait(0.005)
        # Reads so far were watchers, not the paste.
        self._read_by_target = False

    def target_has_read(self) -> bool:
        return self._read_by_target

    def wait(self, seconds: float) -> None:
        win = self._win
        msg = win.MSG()
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            while win.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                win.TranslateMessage(ctypes.byref(msg))
                win.DispatchMessageW(ctypes.byref(msg))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            win.MsgWaitForMultipleObjects(0, None, False, max(1, int(remaining * 1000)), QS_ALLINPUT)

    def changed_since_write(self) -> bool:
        """True when another app replaced the dictated text.

        Ownership is the firm test: anyone writing the clipboard must empty it,
        which takes ownership away from this window. The sequence number also
        moves when we render the text, so it only counts before a render.
        """
        win = self._win
        if self._lost or win.GetClipboardOwner() != self.hwnd:
            return True
        if not self._rendered and self._own_sequence is not None:
            return int(win.GetClipboardSequenceNumber()) != self._own_sequence
        return False

    def restore(self, snapshot: WindowsSnapshot) -> bool:
        """Put the snapshot back. False when someone copied while we waited to open."""
        win = self._win
        self._open()
        # Opening may have pumped a WM_DESTROYCLIPBOARD from another app's copy.
        if self._lost or win.GetClipboardOwner() != self.hwnd:
            win.CloseClipboard()
            return False
        self._restoring = True
        try:
            if not win.EmptyClipboard():
                raise _last_error()
            # Emptying dropped the delayed text; nothing is left to render.
            self._text = None
            for item in snapshot.items:
                self._set_item(item)
            if snapshot.items and not any(i.name == EXCLUDE_FROM_MONITORS for i in snapshot.items):
                # The saved contents were recorded when they were first copied;
                # do not add them to Win+V history a second time.
                self._set_bytes(win.RegisterClipboardFormatW(EXCLUDE_FROM_MONITORS), b"\0\0\0\0")
        finally:
            win.CloseClipboard()
            self._restoring = False
        return True

    def close(self) -> None:
        hwnd = getattr(self, "hwnd", 0)
        if not hwnd:
            return
        try:
            self._win.DestroyWindow(hwnd)
        finally:
            _sessions.pop(hwnd, None)
            self.hwnd = 0


def read_clipboard_formats() -> dict[int, bytes]:
    """Every copyable format's bytes, keyed by format id. For tests and the smoke script."""
    session = WindowsClipboardSession(target_pids=lambda: {os.getpid()})
    try:
        snapshot = session.snapshot()
    finally:
        session.close()
    return {int(item.format): item.data for item in snapshot.items}
