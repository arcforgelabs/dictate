"""OS-backed API key storage for hosted STT backends."""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from urllib import error, request

API_BACKENDS: tuple[str, ...] = ("openai", "xai", "gemini")
API_BACKEND_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "xai": "xAI",
    "gemini": "Google Gemini",
}


class ApiKeyStorageError(RuntimeError):
    """Raised when an API key cannot be stored or loaded."""


@dataclass(frozen=True, slots=True)
class ApiKeyStatus:
    """User-facing hosted API key readiness."""

    backend: str
    status: str
    source: str | None = None
    detail: str | None = None

    @property
    def ready(self) -> bool:
        return self.status == "Ready"


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


def api_key_status(
    backend: str,
    *,
    api_key: str | None = None,
    include_command: bool = True,
    validate_remote: bool = False,
    timeout: int = 5,
) -> ApiKeyStatus:
    """Return Ready, None, or Invalid for a hosted backend API key."""
    _validate_backend(backend)
    if api_key is None:
        try:
            api_key, source = _configured_api_key(backend, include_command=include_command)
        except Exception as exc:  # noqa: BLE001
            _log_api_key_validation_failure(backend, "read", exc)
            return ApiKeyStatus(backend=backend, status="Invalid", detail="read failed")
    else:
        api_key = api_key.strip()
        source = "entered"

    if not api_key:
        return ApiKeyStatus(backend=backend, status="None")

    format_error = validate_api_key_format(backend, api_key)
    if format_error:
        _log_api_key_validation_failure(backend, "format", format_error)
        return ApiKeyStatus(
            backend=backend,
            status="Invalid",
            source=source,
            detail=format_error,
        )

    if not validate_remote:
        return ApiKeyStatus(backend=backend, status="Ready", source=source)

    try:
        _validate_api_key_remote(backend, api_key, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        _log_api_key_validation_failure(backend, "remote", exc)
        return ApiKeyStatus(backend=backend, status="Invalid", source=source, detail=str(exc))
    return ApiKeyStatus(backend=backend, status="Ready", source=source)


def validate_api_key_format(backend: str, api_key: str) -> str | None:
    """Return None when an API key has the expected provider-local shape."""
    _validate_backend(backend)
    cleaned = api_key.strip()
    if not cleaned:
        return "empty API key"
    if any(ch.isspace() for ch in cleaned):
        return "API key contains whitespace"
    if any(ord(ch) < 32 for ch in cleaned):
        return "API key contains control characters"

    if _custom_base_url_configured(backend):
        return None

    if backend == "xai":
        if not re.fullmatch(r"xai-[A-Za-z0-9._-]{16,}", cleaned):
            return "xAI API keys must start with xai- and contain only token characters"
    elif backend == "openai":
        if not re.fullmatch(r"sk-[A-Za-z0-9._-]{16,}", cleaned):
            return "OpenAI API keys must start with sk- and contain only token characters"
    elif backend == "gemini":
        if not re.fullmatch(r"AIza[A-Za-z0-9_-]{20,}", cleaned):
            return "Gemini API keys must start with AIza and contain only token characters"
    return None


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


def _configured_api_key(backend: str, *, include_command: bool = True) -> tuple[str | None, str | None]:
    for env_name in _api_key_env_names(backend):
        value = os.environ.get(env_name)
        if value:
            return (value.strip(), env_name)
    command_env = f"DICTATE_{backend.upper()}_API_KEY_COMMAND"
    command = os.environ.get(command_env)
    if include_command and command:
        api_key = _api_key_from_command(command, backend=backend)
        if api_key:
            return (api_key, command_env)
    return (read_api_key(backend), "secret-store")


def _api_key_env_names(backend: str) -> tuple[str, ...]:
    if backend == "openai":
        return ("DICTATE_OPENAI_API_KEY", "OPENAI_API_KEY")
    if backend == "xai":
        return ("DICTATE_XAI_API_KEY", "XAI_API_KEY")
    if backend == "gemini":
        return ("DICTATE_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")
    return ()


def _custom_base_url_configured(backend: str) -> bool:
    env_name = f"DICTATE_{backend.upper()}_BASE_URL"
    return bool(os.environ.get(env_name))


def _api_key_from_command(command: str, *, backend: str) -> str | None:
    try:
        completed = subprocess.run(
            shlex.split(command),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        raise ApiKeyStorageError(f"{API_BACKEND_LABELS[backend]} API key command failed.") from exc
    output = completed.stdout.strip()
    if not output:
        return None
    return output.splitlines()[0].strip() or None


def _validate_api_key_remote(backend: str, api_key: str, *, timeout: int) -> None:
    if _custom_base_url_configured(backend):
        return
    if backend == "xai":
        base_url = os.environ.get("DICTATE_XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
        _validate_bearer_key(
            url=f"{base_url}/api-key",
            api_key=api_key,
            timeout=timeout,
            backend=backend,
        )
        return
    if backend == "openai":
        base_url = os.environ.get("DICTATE_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip(
            "/"
        )
        _validate_openai_transcription_key(
            url=f"{base_url}/audio/transcriptions",
            api_key=api_key,
            timeout=timeout,
        )
        return
    if backend == "gemini":
        base_url = os.environ.get(
            "DICTATE_GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        ).rstrip("/")
        _read_validation_response(
            url=f"{base_url}/models",
            headers={"x-goog-api-key": api_key},
            timeout=timeout,
            backend=backend,
        )


def _validate_bearer_key(*, url: str, api_key: str, timeout: int, backend: str) -> None:
    _read_validation_response(
        url=url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
        backend=backend,
    )


def _validate_openai_transcription_key(*, url: str, api_key: str, timeout: int) -> None:
    boundary = "----dictate-openai-api-key-validation"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="model"\r\n\r\n'
        "gpt-4o-mini-transcribe\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    validation_request = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with request.urlopen(validation_request, timeout=timeout) as response:
            response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code in {400, 422}:
            return
        summary = _truncate_validation_detail(detail)
        raise ApiKeyStorageError(f"HTTP {exc.code}: {summary}") from exc
    except error.URLError as exc:
        raise ApiKeyStorageError(str(exc.reason)) from exc


def _read_validation_response(
    *,
    url: str,
    headers: dict[str, str],
    timeout: int,
    backend: str,
) -> None:
    validation_request = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(validation_request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        summary = _truncate_validation_detail(detail)
        raise ApiKeyStorageError(f"HTTP {exc.code}: {summary}") from exc
    except error.URLError as exc:
        raise ApiKeyStorageError(str(exc.reason)) from exc

    if backend != "xai":
        return
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return
    for blocked_field in ("api_key_blocked", "api_key_disabled", "team_blocked"):
        if data.get(blocked_field) is True:
            raise ApiKeyStorageError(f"xAI reported {blocked_field}=true")


def _truncate_validation_detail(detail: str) -> str:
    cleaned = " ".join(detail.split())
    if len(cleaned) > 240:
        return f"{cleaned[:237]}..."
    return cleaned or "empty response"


def _log_api_key_validation_failure(backend: str, phase: str, detail: object) -> None:
    print(
        f"Dictate API key validation failed for {backend} during {phase}: {detail}",
        file=sys.stderr,
    )


def _is_windows() -> bool:
    return sys.platform.startswith("win")
