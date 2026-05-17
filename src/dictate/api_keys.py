"""OS-backed API key storage for hosted STT backends."""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from ctypes import wintypes

API_BACKENDS: tuple[str, ...] = ("openai", "xai", "gemini")
API_BACKEND_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "xai": "xAI",
    "gemini": "Google Gemini",
}


class ApiKeyStorageError(RuntimeError):
    """Raised when an API key cannot be stored or loaded."""


def save_api_key(backend: str, api_key: str) -> None:
    """Persist an API key in the OS secret store."""
    _validate_backend(backend)
    cleaned = api_key.strip()
    if not cleaned:
        raise ApiKeyStorageError("API key is empty.")
    if _is_windows():
        _windows_save_api_key(backend, cleaned)
        return
    _secret_tool_save_api_key(backend, cleaned)


def read_api_key(backend: str) -> str | None:
    """Read an API key from the OS secret store, if one exists."""
    _validate_backend(backend)
    if _is_windows():
        return _windows_read_api_key(backend)
    if shutil.which("secret-tool") is None:
        return None
    return _secret_tool_read_api_key(backend)


def clear_api_key(backend: str) -> None:
    """Remove an API key from the OS secret store, if one exists."""
    _validate_backend(backend)
    if _is_windows():
        _windows_clear_api_key(backend)
        return
    _secret_tool_clear_api_key(backend)


def has_stored_api_key(backend: str) -> bool:
    """Return whether the OS secret store has a non-empty key for a backend."""
    return bool(read_api_key(backend))


def secret_store_available() -> bool:
    """Return whether Dictate can store API keys in an OS secret store."""
    if _is_windows():
        return True
    return shutil.which("secret-tool") is not None


def secret_store_description() -> str:
    """Human-readable description of the active secret store."""
    if _is_windows():
        return "Windows Credential Manager"
    if shutil.which("secret-tool") is not None:
        return "the desktop Secret Service keyring"
    return "no supported OS secret store"


def _secret_tool_save_api_key(backend: str, api_key: str) -> None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "store",
            "--label",
            f"Dictate {API_BACKEND_LABELS[backend]} API key",
            "application",
            "dictate",
            "backend",
            backend,
            "kind",
            "api-key",
        ],
        action="store",
        input=api_key,
        timeout=20,
    )
    if completed.returncode != 0:
        raise ApiKeyStorageError(_secret_tool_error("store", completed.stderr))


def _secret_tool_read_api_key(backend: str) -> str | None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "lookup",
            "application",
            "dictate",
            "backend",
            backend,
            "kind",
            "api-key",
        ],
        action="lookup",
        timeout=10,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _secret_tool_clear_api_key(backend: str) -> None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "clear",
            "application",
            "dictate",
            "backend",
            backend,
            "kind",
            "api-key",
        ],
        action="clear",
        timeout=10,
    )
    if completed.returncode not in {0, 1}:
        raise ApiKeyStorageError(_secret_tool_error("clear", completed.stderr))


def _run_secret_tool(
    args: list[str],
    *,
    action: str,
    input: str | None = None,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            input=input,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ApiKeyStorageError(f"Secret Service timed out during API key {action}.") from exc
    except OSError as exc:
        raise ApiKeyStorageError(f"Could not run secret-tool for API key {action}: {exc}") from exc


def _require_secret_tool() -> str:
    secret_tool = shutil.which("secret-tool")
    if secret_tool is None:
        raise ApiKeyStorageError(
            "No supported OS secret store is available. Install libsecret/secret-tool, "
            "or configure an external *_api_key_command secret helper."
        )
    return secret_tool


def _secret_tool_error(action: str, stderr: str) -> str:
    detail = stderr.strip() or "unknown error"
    return f"Could not {action} API key in Secret Service: {detail}"


def _windows_save_api_key(backend: str, api_key: str) -> None:
    blob = api_key.encode("utf-16-le")
    credential = _CREDENTIALW()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = _windows_target_name(backend)
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob), wintypes.LPBYTE)
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "dictate"
    if not _advapi32().CredWriteW(ctypes.byref(credential), 0):
        raise ApiKeyStorageError(_windows_error("write"))


def _windows_read_api_key(backend: str) -> str | None:
    credential_ptr = ctypes.POINTER(_CREDENTIALW)()
    ok = _advapi32().CredReadW(
        _windows_target_name(backend),
        _CRED_TYPE_GENERIC,
        0,
        ctypes.byref(credential_ptr),
    )
    if not ok:
        return None
    try:
        credential = credential_ptr.contents
        if not credential.CredentialBlob or credential.CredentialBlobSize <= 0:
            return None
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return blob.decode("utf-16-le").strip() or None
    finally:
        _advapi32().CredFree(credential_ptr)


def _windows_clear_api_key(backend: str) -> None:
    if _advapi32().CredDeleteW(_windows_target_name(backend), _CRED_TYPE_GENERIC, 0):
        return
    code = _windows_last_error()
    if code == _ERROR_NOT_FOUND:
        return
    raise ApiKeyStorageError(_windows_error("delete", code=code))


def _windows_target_name(backend: str) -> str:
    return f"Dictate:{backend}:api-key"


def _windows_error(action: str, *, code: int | None = None) -> str:
    if code is None:
        code = _windows_last_error()
    return f"Could not {action} API key in Windows Credential Manager (error {code})."


def _windows_last_error() -> int:
    return ctypes.get_last_error()


def _advapi32():  # noqa: ANN202
    lib = ctypes.WinDLL("Advapi32", use_last_error=True)
    lib.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    lib.CredWriteW.restype = wintypes.BOOL
    lib.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    ]
    lib.CredReadW.restype = wintypes.BOOL
    lib.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    lib.CredDeleteW.restype = wintypes.BOOL
    lib.CredFree.argtypes = [wintypes.LPVOID]
    lib.CredFree.restype = None
    return lib


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", wintypes.LPBYTE),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", wintypes.LPVOID),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


def _validate_backend(backend: str) -> None:
    if backend not in API_BACKENDS:
        raise ApiKeyStorageError(f"Unsupported API backend: {backend}")


def _is_windows() -> bool:
    return sys.platform.startswith("win")
