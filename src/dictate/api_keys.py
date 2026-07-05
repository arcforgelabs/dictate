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
from pathlib import Path
from urllib import error, request

from dictate.platform_paths import user_config_dir

API_BACKENDS: tuple[str, ...] = ("openai", "xai", "gemini")
API_BACKEND_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "xai": "xAI",
    "gemini": "Google Gemini",
}
LOCAL_API_KEYS_PATH = user_config_dir() / "api-keys.json"


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


PRO_REFRESH_TOKEN_BACKEND = "dictate-pro-refresh"
SYNC_ACCOUNT_KEY_BACKEND = "dictate-sync-account-key"
SYNC_DEVICE_PRIVATE_KEY_BACKEND = "dictate-sync-device-private-key"


def save_pro_refresh_token(token: str) -> None:
    """Persist a Dictate Pro refresh token in the OS secret store."""
    cleaned = token.strip()
    if not cleaned:
        raise ApiKeyStorageError("Refresh token is empty.")
    if _is_windows():
        _windows_save_pro_refresh_token(cleaned)
        return
    if shutil.which("secret-tool") is not None:
        _secret_tool_save_pro_refresh_token(cleaned)
        return
    raise ApiKeyStorageError("No supported OS secret store is available for refresh token storage.")


def read_pro_refresh_token() -> str | None:
    """Read a Dictate Pro refresh token from the OS secret store, if one exists."""
    if _is_windows():
        return _windows_read_pro_refresh_token()
    if shutil.which("secret-tool") is not None:
        return _secret_tool_read_pro_refresh_token()
    return None


def clear_pro_refresh_token() -> None:
    """Remove a Dictate Pro refresh token from the OS secret store, if one exists."""
    if _is_windows():
        _windows_clear_pro_refresh_token()
        return
    if shutil.which("secret-tool") is not None:
        _secret_tool_clear_pro_refresh_token()


def save_sync_account_key(account_id: str, encoded_key: str) -> None:
    """Persist a Dictate Pro sync account data key in the OS secret store."""
    account = account_id.strip()
    key = encoded_key.strip()
    if not account or not key:
        raise ApiKeyStorageError("Sync account id and key are required.")
    if _is_windows():
        _windows_save_secret(_windows_sync_account_key_target_name(account), key, "sync account key")
        return
    if shutil.which("secret-tool") is not None:
        _secret_tool_save_sync_account_key(account, key)
        return
    raise ApiKeyStorageError("No supported OS secret store is available for sync account key storage.")


def read_sync_account_key(account_id: str) -> str | None:
    """Read a Dictate Pro sync account data key from the OS secret store."""
    account = account_id.strip()
    if not account:
        return None
    if _is_windows():
        return _windows_read_secret(_windows_sync_account_key_target_name(account))
    if shutil.which("secret-tool") is not None:
        return _secret_tool_read_sync_account_key(account)
    return None


def clear_sync_account_key(account_id: str) -> None:
    """Remove a Dictate Pro sync account data key from the OS secret store."""
    account = account_id.strip()
    if not account:
        return
    if _is_windows():
        _windows_clear_secret(_windows_sync_account_key_target_name(account), "sync account key")
        return
    if shutil.which("secret-tool") is not None:
        _secret_tool_clear_sync_account_key(account)


def save_sync_device_private_key(device_id: str, encoded_key: str) -> None:
    """Persist a Dictate Pro sync device private key in the OS secret store."""
    device = device_id.strip()
    key = encoded_key.strip()
    if not device or not key:
        raise ApiKeyStorageError("Sync device id and private key are required.")
    if _is_windows():
        _windows_save_secret(_windows_sync_device_private_key_target_name(device), key, "sync device private key")
        return
    if shutil.which("secret-tool") is not None:
        _secret_tool_save_sync_device_private_key(device, key)
        return
    raise ApiKeyStorageError("No supported OS secret store is available for sync device private key storage.")


def read_sync_device_private_key(device_id: str) -> str | None:
    """Read a Dictate Pro sync device private key from the OS secret store."""
    device = device_id.strip()
    if not device:
        return None
    if _is_windows():
        return _windows_read_secret(_windows_sync_device_private_key_target_name(device))
    if shutil.which("secret-tool") is not None:
        return _secret_tool_read_sync_device_private_key(device)
    return None


def clear_sync_device_private_key(device_id: str) -> None:
    """Remove a Dictate Pro sync device private key from the OS secret store."""
    device = device_id.strip()
    if not device:
        return
    if _is_windows():
        _windows_clear_secret(_windows_sync_device_private_key_target_name(device), "sync device private key")
        return
    if shutil.which("secret-tool") is not None:
        _secret_tool_clear_sync_device_private_key(device)


def save_api_key(backend: str, api_key: str) -> None:
    """Persist an API key in the best available local secret store."""
    _validate_backend(backend)
    cleaned = api_key.strip()
    if not cleaned:
        raise ApiKeyStorageError("API key is empty.")
    if _is_windows():
        _windows_save_api_key(backend, cleaned)
        return
    if shutil.which("secret-tool") is not None:
        _secret_tool_save_api_key(backend, cleaned)
        return
    _local_file_save_api_key(backend, cleaned)


def read_api_key(backend: str) -> str | None:
    """Read an API key from the best available local secret store, if one exists."""
    _validate_backend(backend)
    if _is_windows():
        return _windows_read_api_key(backend)
    if shutil.which("secret-tool") is not None:
        value = _secret_tool_read_api_key(backend)
        if value:
            return value
    return _local_file_read_api_key(backend)


def clear_api_key(backend: str) -> None:
    """Remove an API key from the OS secret store, if one exists."""
    _validate_backend(backend)
    if _is_windows():
        _windows_clear_api_key(backend)
        return
    if shutil.which("secret-tool") is not None:
        _secret_tool_clear_api_key(backend)
    _local_file_clear_api_key(backend)


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
    log_failures: bool = True,
) -> ApiKeyStatus:
    """Return Ready, None, or Invalid for a hosted backend API key.

    ``log_failures=False`` keeps a passive status check quiet: it still reports an
    Invalid/None status, but does not log a validation failure. Use it when
    enumerating every backend for display (an unused, optionally-configured
    provider should not spam the daemon log), and leave it on for explicit
    user-driven validation and the provider health probe.
    """
    _validate_backend(backend)
    if api_key is None:
        try:
            api_key, source = _configured_api_key(backend, include_command=include_command)
        except Exception as exc:  # noqa: BLE001
            if log_failures:
                _log_api_key_validation_failure(backend, "read", exc)
            return ApiKeyStatus(backend=backend, status="Invalid", detail="read failed")
    else:
        api_key = api_key.strip()
        source = "entered"

    if not api_key:
        return ApiKeyStatus(backend=backend, status="None")

    format_error = validate_api_key_format(backend, api_key)
    if format_error:
        if log_failures:
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
        if log_failures:
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
    return True


def secret_store_description() -> str:
    """Human-readable description of the active secret store."""
    if _is_windows():
        return "Windows Credential Manager"
    if shutil.which("secret-tool") is not None:
        return "the desktop Secret Service keyring"
    return f"private local key file ({LOCAL_API_KEYS_PATH})"


def _local_file_save_api_key(backend: str, api_key: str) -> None:
    data = _local_file_load()
    data[backend] = api_key
    _local_file_save(data)


def _local_file_read_api_key(backend: str) -> str | None:
    value = _local_file_load().get(backend)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _local_file_clear_api_key(backend: str) -> None:
    data = _local_file_load()
    if backend in data:
        data.pop(backend, None)
        _local_file_save(data)


def _local_file_load(path: Path | None = None) -> dict[str, str]:
    path = path or LOCAL_API_KEYS_PATH
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for backend, value in raw.items():
        if backend in API_BACKENDS and isinstance(value, str) and value.strip():
            out[backend] = value.strip()
    return out


def _local_file_save(data: dict[str, str], path: Path | None = None) -> None:
    path = path or LOCAL_API_KEYS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass


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


def _secret_tool_save_pro_refresh_token(token: str) -> None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "store",
            "--label",
            "Dictate Pro refresh token",
            "application",
            "dictate",
            "backend",
            PRO_REFRESH_TOKEN_BACKEND,
            "kind",
            "pro-refresh-token",
        ],
        action="store",
        input=token,
        timeout=20,
    )
    if completed.returncode != 0:
        raise ApiKeyStorageError(_secret_tool_error("store", completed.stderr))


def _secret_tool_read_pro_refresh_token() -> str | None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "lookup",
            "application",
            "dictate",
            "backend",
            PRO_REFRESH_TOKEN_BACKEND,
            "kind",
            "pro-refresh-token",
        ],
        action="lookup",
        timeout=10,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _secret_tool_clear_pro_refresh_token() -> None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "clear",
            "application",
            "dictate",
            "backend",
            PRO_REFRESH_TOKEN_BACKEND,
            "kind",
            "pro-refresh-token",
        ],
        action="clear",
        timeout=10,
    )
    if completed.returncode not in {0, 1}:
        raise ApiKeyStorageError(_secret_tool_error("clear", completed.stderr))


def _secret_tool_save_sync_account_key(account_id: str, encoded_key: str) -> None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "store",
            "--label",
            "Dictate Pro sync account key",
            "application",
            "dictate",
            "backend",
            SYNC_ACCOUNT_KEY_BACKEND,
            "kind",
            "sync-account-key",
            "account",
            account_id,
        ],
        action="store",
        input=encoded_key,
        timeout=20,
    )
    if completed.returncode != 0:
        raise ApiKeyStorageError(_secret_tool_error("store", completed.stderr))


def _secret_tool_read_sync_account_key(account_id: str) -> str | None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "lookup",
            "application",
            "dictate",
            "backend",
            SYNC_ACCOUNT_KEY_BACKEND,
            "kind",
            "sync-account-key",
            "account",
            account_id,
        ],
        action="lookup",
        timeout=10,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _secret_tool_clear_sync_account_key(account_id: str) -> None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "clear",
            "application",
            "dictate",
            "backend",
            SYNC_ACCOUNT_KEY_BACKEND,
            "kind",
            "sync-account-key",
            "account",
            account_id,
        ],
        action="clear",
        timeout=10,
    )
    if completed.returncode not in {0, 1}:
        raise ApiKeyStorageError(_secret_tool_error("clear", completed.stderr))


def _secret_tool_save_sync_device_private_key(device_id: str, encoded_key: str) -> None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "store",
            "--label",
            "Dictate Pro sync device private key",
            "application",
            "dictate",
            "backend",
            SYNC_DEVICE_PRIVATE_KEY_BACKEND,
            "kind",
            "sync-device-private-key",
            "device",
            device_id,
        ],
        action="store",
        input=encoded_key,
        timeout=20,
    )
    if completed.returncode != 0:
        raise ApiKeyStorageError(_secret_tool_error("store", completed.stderr))


def _secret_tool_read_sync_device_private_key(device_id: str) -> str | None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "lookup",
            "application",
            "dictate",
            "backend",
            SYNC_DEVICE_PRIVATE_KEY_BACKEND,
            "kind",
            "sync-device-private-key",
            "device",
            device_id,
        ],
        action="lookup",
        timeout=10,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _secret_tool_clear_sync_device_private_key(device_id: str) -> None:
    secret_tool = _require_secret_tool()
    completed = _run_secret_tool(
        [
            secret_tool,
            "clear",
            "application",
            "dictate",
            "backend",
            SYNC_DEVICE_PRIVATE_KEY_BACKEND,
            "kind",
            "sync-device-private-key",
            "device",
            device_id,
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
    _windows_save_secret(_windows_target_name(backend), api_key, "API key")


def _windows_read_api_key(backend: str) -> str | None:
    return _windows_read_secret(_windows_target_name(backend))


def _windows_clear_api_key(backend: str) -> None:
    _windows_clear_secret(_windows_target_name(backend), "API key")


def _windows_save_pro_refresh_token(token: str) -> None:
    _windows_save_secret(_windows_pro_refresh_target_name(), token, "pro refresh token")


def _windows_read_pro_refresh_token() -> str | None:
    return _windows_read_secret(_windows_pro_refresh_target_name())


def _windows_clear_pro_refresh_token() -> None:
    _windows_clear_secret(_windows_pro_refresh_target_name(), "pro refresh token")


def _windows_save_secret(target_name: str, value: str, label: str) -> None:
    blob = value.encode("utf-16-le")
    credential = _CREDENTIALW()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = target_name
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob), wintypes.LPBYTE)
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "dictate"
    if not _advapi32().CredWriteW(ctypes.byref(credential), 0):
        raise ApiKeyStorageError(_windows_error(f"write {label}"))


def _windows_read_secret(target_name: str) -> str | None:
    credential_ptr = ctypes.POINTER(_CREDENTIALW)()
    ok = _advapi32().CredReadW(
        target_name,
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


def _windows_clear_secret(target_name: str, label: str) -> None:
    if _advapi32().CredDeleteW(target_name, _CRED_TYPE_GENERIC, 0):
        return
    code = _windows_last_error()
    if code == _ERROR_NOT_FOUND:
        return
    raise ApiKeyStorageError(_windows_error(f"delete {label}", code=code))


def _windows_target_name(backend: str) -> str:
    return f"Dictate:{backend}:api-key"


def _windows_pro_refresh_target_name() -> str:
    return f"Dictate:{PRO_REFRESH_TOKEN_BACKEND}:pro-refresh-token"


def _windows_sync_account_key_target_name(account_id: str) -> str:
    return f"Dictate:{SYNC_ACCOUNT_KEY_BACKEND}:{account_id}:sync-account-key"


def _windows_sync_device_private_key_target_name(device_id: str) -> str:
    return f"Dictate:{SYNC_DEVICE_PRIVATE_KEY_BACKEND}:{device_id}:sync-device-private-key"


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
