"""Native Windows notification-area host for the Dictate daemon."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from dictate.daemon import Daemon
from dictate.hotkey import format_hotkey_combo

HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
LPVOID = getattr(wintypes, "LPVOID", ctypes.c_void_p)
LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
UINT_PTR = getattr(wintypes, "UINT_PTR", wintypes.WPARAM)

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_NULL = 0x0000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
MF_UNCHECKED = 0x00000000
TPM_RIGHTBUTTON = 0x0002

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
IDI_APPLICATION = 32512

IDM_ACTIVE = 1001
IDM_CONTROLS = 1002
IDM_RECENT_HISTORY = 1003
IDM_QUIT = 1004


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", LPVOID),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", HICON),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _POINT),
    ]


class WindowsTrayIcon:
    """Run Dictate with a Windows notification-area icon and context menu."""

    def __init__(self, daemon: Daemon) -> None:
        if not sys.platform.startswith("win"):
            raise RuntimeError("Windows tray is only available on Windows.")
        self.daemon = daemon
        self._user32 = ctypes.windll.user32
        self._shell32 = ctypes.windll.shell32
        self._kernel32 = ctypes.windll.kernel32
        self._configure_win32_api()
        self._class_name = "DictateTrayWindow"
        self._hwnd = None
        self._hicon = None
        self._wndproc = None
        self._quitting = False

    def _configure_win32_api(self) -> None:
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        self._user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
        self._user32.RegisterClassW.restype = wintypes.ATOM
        self._user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            LPVOID,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.DefWindowProcW.restype = LRESULT
        self._user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self._user32.LoadImageW.restype = HICON
        self._user32.LoadIconW.argtypes = [wintypes.HINSTANCE, LPVOID]
        self._user32.LoadIconW.restype = HICON
        self._user32.CreatePopupMenu.restype = wintypes.HMENU
        self._user32.AppendMenuW.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            UINT_PTR,
            wintypes.LPCWSTR,
        ]
        self._user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            LPVOID,
        ]
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.DestroyMenu.argtypes = [wintypes.HMENU]
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.GetMessageW.argtypes = [
            ctypes.POINTER(_MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
        self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
        self._shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
        self._shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    def run(self) -> None:
        self.daemon.start()
        try:
            self._create_window()
            self._add_icon()
            print("dictate running (Windows tray icon active)", file=sys.stderr)
            print(
                f"  Hold {format_hotkey_combo(self.daemon.push_to_talk_combo)} to dictate",
                file=sys.stderr,
            )
            self._message_loop()
        finally:
            self._delete_icon()
            self.daemon.shutdown()

    def _create_window(self) -> None:
        wndproc_type = ctypes.WINFUNCTYPE(
            LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        self._wndproc = wndproc_type(self._window_proc)
        hinstance = self._kernel32.GetModuleHandleW(None)

        wc = _WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(self._wndproc, LPVOID).value
        wc.hInstance = hinstance
        wc.lpszClassName = self._class_name
        self._user32.RegisterClassW(ctypes.byref(wc))

        hwnd = self._user32.CreateWindowExW(
            0,
            self._class_name,
            "Dictate",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            raise ctypes.WinError()
        self._hwnd = hwnd

    def _add_icon(self) -> None:
        data = self._notify_data()
        data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        data.uCallbackMessage = WM_TRAYICON
        data.hIcon = self._load_icon()
        data.szTip = self._tooltip()
        if not self._shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
            raise ctypes.WinError()

    def _modify_icon(self) -> None:
        if self._hwnd is None:
            return
        data = self._notify_data()
        data.uFlags = NIF_TIP
        data.szTip = self._tooltip()
        self._shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(data))

    def _delete_icon(self) -> None:
        if self._hwnd is None:
            return
        data = self._notify_data()
        self._shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
        self._hwnd = None

    def _notify_data(self) -> _NOTIFYICONDATAW:
        data = _NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        return data

    def _load_icon(self):
        if self._hicon:
            return self._hicon
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "dictate-controls.ico"
        if icon_path.is_file():
            self._hicon = self._user32.LoadImageW(
                None,
                str(icon_path),
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE,
            )
        if not self._hicon:
            self._hicon = self._user32.LoadIconW(None, IDI_APPLICATION)
        return self._hicon

    def _tooltip(self) -> str:
        state = "active" if self.daemon.active else "paused"
        backend, model = self.daemon.current_backend_model()
        return f"Dictate {state}: {backend}/{model}"[:127]

    def _message_loop(self) -> None:
        msg = _MSG()
        while self._user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def _window_proc(self, hwnd, msg, wparam, lparam):  # noqa: ANN001
        if msg == WM_TRAYICON:
            if lparam in {WM_RBUTTONUP, WM_LBUTTONDBLCLK}:
                self._show_menu()
            return 0
        if msg == WM_COMMAND:
            self._handle_command(int(wparam) & 0xFFFF)
            return 0
        if msg == WM_DESTROY:
            self._user32.PostQuitMessage(0)
            return 0
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self) -> None:
        menu = self._user32.CreatePopupMenu()
        if not menu:
            return
        try:
            active_flags = MF_STRING | (MF_CHECKED if self.daemon.active else MF_UNCHECKED)
            self._user32.AppendMenuW(menu, active_flags, IDM_ACTIVE, "Active")
            self._user32.AppendMenuW(menu, MF_STRING, IDM_CONTROLS, "Controls")
            self._user32.AppendMenuW(menu, MF_STRING, IDM_RECENT_HISTORY, "Recent History")
            self._user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            self._user32.AppendMenuW(menu, MF_STRING, IDM_QUIT, "Quit")
            point = _POINT()
            self._user32.GetCursorPos(ctypes.byref(point))
            self._user32.SetForegroundWindow(self._hwnd)
            self._user32.TrackPopupMenu(
                menu,
                TPM_RIGHTBUTTON,
                point.x,
                point.y,
                0,
                self._hwnd,
                None,
            )
            self._user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        finally:
            self._user32.DestroyMenu(menu)

    def _handle_command(self, command_id: int) -> None:
        if command_id == IDM_ACTIVE:
            if self.daemon.active:
                self.daemon.pause()
            else:
                self.daemon.resume()
            self._modify_icon()
            return
        if command_id in {IDM_CONTROLS, IDM_RECENT_HISTORY}:
            _open_controls()
            return
        if command_id == IDM_QUIT:
            self._quitting = True
            if self._hwnd is not None:
                self._user32.DestroyWindow(self._hwnd)


def _open_controls() -> None:
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [sys.executable, "-m", "dictate", "controls"],
        cwd=os.getcwd(),
        creationflags=creationflags,
    )
