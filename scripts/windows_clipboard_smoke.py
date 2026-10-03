"""Paste one synthetic dictation on Windows and report what the clipboard keeper did.

Called by ``scripts/windows-clipboard-smoke.ps1``, which saves and compares the
clipboard around it. Two targets:

- ``edit`` (default, works on a CI runner): a hidden Win32 EDIT control in this
  process. The paste is a WM_PASTE message, so no keyboard focus is needed.
- ``notepad``: starts Notepad and sends the real Ctrl+V through the typing
  backend Dictate uses (pynput). Needs an unlocked desktop.

Prints one JSON line. The text is synthetic, so printing it is fine.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import threading
import time
from unittest.mock import patch

if sys.platform.startswith("win"):
    from ctypes import wintypes

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_QUIT = 0x0012
WM_PASTE = 0x0302
WS_POPUP = 0x80000000
ES_MULTILINE = 0x0004


class EditControl:
    def __init__(self) -> None:
        from dictate import clipboard_windows as cw

        self._cw = cw
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._get_message = user32.GetMessageW
        self._get_message.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        self._get_message.restype = wintypes.BOOL
        self._post = user32.PostMessageW
        self._post.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._send = user32.SendMessageW
        self._send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._send.restype = ctypes.c_ssize_t
        self._post_thread = user32.PostThreadMessageW
        self._post_thread.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._thread_id_fn = ctypes.WinDLL("kernel32").GetCurrentThreadId
        self._thread_id_fn.restype = wintypes.DWORD
        self.hwnd = 0
        self._thread_id = 0
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(5) or not self.hwnd:
            raise OSError("EDIT control did not start")

    def _run(self) -> None:
        win = self._cw.api()
        self._thread_id = self._thread_id_fn()
        self.hwnd = win.CreateWindowExW(
            0, "EDIT", "", WS_POPUP | ES_MULTILINE, 0, 0, 200, 100, None, None,
            win.GetModuleHandleW(None), None,
        ) or 0
        self._ready.set()
        msg = wintypes.MSG()
        while self._get_message(ctypes.byref(msg), None, 0, 0) > 0:
            win.TranslateMessage(ctypes.byref(msg))
            win.DispatchMessageW(ctypes.byref(msg))
        if self.hwnd:
            win.DestroyWindow(self.hwnd)

    def paste(self, *args: object, **kwargs: object) -> None:
        self._post(self.hwnd, WM_PASTE, 0, 0)

    def text(self) -> str:
        length = self._send(self.hwnd, WM_GETTEXTLENGTH, 0, 0)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._send(self.hwnd, WM_GETTEXT, length + 1, ctypes.addressof(buffer))
        return buffer.value

    def close(self) -> None:
        self._post_thread(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(5)


def paste_into_edit(text: str) -> dict[str, object]:
    from dictate.clipboard_keeper import default_clipboard_keeper
    from dictate.outputs import ClipboardOutput, PasteOutput, PynputOutput

    keeper = default_clipboard_keeper()
    if keeper is None:
        return {"error": "no clipboard keeper on this platform"}
    edit = EditControl()
    try:
        with patch("dictate.outputs._send_paste_shortcut", side_effect=edit.paste):
            PasteOutput(PynputOutput(), ClipboardOutput(), keeper).send(text)
            keeper.wait_idle(10)
        pasted = edit.text()
    finally:
        edit.close()
    return {
        "target": "edit",
        "pasted_matches": pasted == text,
        # Synthetic text, so showing what landed is safe and helps a failure.
        "pasted": pasted,
        "outcome": _outcome(keeper),
    }


def paste_into_notepad(text: str) -> dict[str, object]:
    from dictate.outputs import resolve_typing_backend

    # Notepad is left open so the maintainer can see the pasted line.
    subprocess.Popen(["notepad.exe"])
    time.sleep(2.0)
    output = resolve_typing_backend("auto")
    output.send(text)
    keeper = getattr(output, "keeper", None)
    if keeper is not None:
        keeper.wait_idle(10)
    return {
        "target": "notepad",
        "pasted_matches": None,
        "note": "check Notepad shows the dictated line, then close it without saving",
        "outcome": _outcome(keeper),
    }


def _outcome(keeper: object) -> dict[str, object] | None:
    outcome = getattr(keeper, "last_outcome", None)
    if outcome is None:
        return None
    return {
        "saved": outcome.saved,
        "read_signal": outcome.read_signal,
        "timed_out": outcome.timed_out,
        "restored": outcome.restored,
        "kept_newer_copy": outcome.kept_newer_copy,
        "error": outcome.error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["edit", "notepad"], default="edit")
    parser.add_argument("--text", required=True)
    args = parser.parse_args(argv)
    if not sys.platform.startswith("win"):
        print(json.dumps({"error": "Windows only"}))
        return 2
    result = paste_into_edit(args.text) if args.target == "edit" else paste_into_notepad(args.text)
    print(json.dumps(result))
    outcome = result.get("outcome") or {}
    ok = bool(outcome.get("restored")) and result.get("pasted_matches") is not False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
