"""Persistent model preparation state for tray/runtime decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from dictate.platform_paths import is_windows, user_data_dir

# The exact pre-fix path used on ALL platforms, including Windows. Non-Windows
# platforms must keep writing here forever -- zero Linux/macOS behavior change
# is required, so this is NOT derived from user_data_dir() (which would move
# for anyone with XDG_DATA_HOME set). On Windows it's kept only as a one-time
# migration source, see load_model_state().
LEGACY_STATE_PATH = Path.home() / ".local" / "share" / "dictate" / "model-state.json"


def _resolve_state_path() -> Path:
    if is_windows():
        return user_data_dir() / "model-state.json"
    return LEGACY_STATE_PATH


STATE_PATH = _resolve_state_path()


@dataclass(slots=True)
class ModelState:
    prepared: set[str] = field(default_factory=set)
    errors: dict[str, str] = field(default_factory=dict)


def model_key(backend: str, model: str, device: str, compute_type: str) -> str:
    return f"{backend}|{model}|{device}|{compute_type}"


def load_model_state(path: Path = STATE_PATH) -> ModelState:
    if not path.is_file():
        # One-time Windows migration: if the real default (%LOCALAPPDATA%-based)
        # path has never been written yet, fall back to reading the legacy
        # path so existing Windows users don't lose their prepared-model cache
        # and trigger a surprise re-prep/re-download. Read-only -- the legacy
        # file is never deleted -- and scoped to the real default STATE_PATH
        # only, not caller-supplied override paths (e.g. tests).
        if is_windows() and path == STATE_PATH and LEGACY_STATE_PATH.is_file():
            path = LEGACY_STATE_PATH
        else:
            return ModelState()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ModelState()

    prepared: set[str] = set()
    errors: dict[str, str] = {}

    prepared_raw = raw.get("prepared", [])
    if isinstance(prepared_raw, list):
        for item in prepared_raw:
            if isinstance(item, str):
                prepared.add(item)

    errors_raw = raw.get("errors", {})
    if isinstance(errors_raw, dict):
        for key, value in errors_raw.items():
            if isinstance(key, str) and isinstance(value, str):
                errors[key] = value

    return ModelState(prepared=prepared, errors=errors)


def save_model_state(state: ModelState, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "prepared": sorted(state.prepared),
        "errors": state.errors,
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def is_model_prepared(
    backend: str,
    model: str,
    device: str,
    compute_type: str,
    *,
    path: Path = STATE_PATH,
) -> bool:
    key = model_key(backend, model, device, compute_type)
    return key in load_model_state(path=path).prepared


def mark_model_prepared(
    backend: str,
    model: str,
    device: str,
    compute_type: str,
    *,
    path: Path = STATE_PATH,
) -> None:
    key = model_key(backend, model, device, compute_type)
    state = load_model_state(path=path)
    state.prepared.add(key)
    state.errors.pop(key, None)
    save_model_state(state, path=path)


def mark_model_failed(
    backend: str,
    model: str,
    device: str,
    compute_type: str,
    error_message: str,
    *,
    path: Path = STATE_PATH,
) -> None:
    key = model_key(backend, model, device, compute_type)
    state = load_model_state(path=path)
    state.prepared.discard(key)
    state.errors[key] = error_message[:1200] if error_message else "unknown model preparation error"
    save_model_state(state, path=path)


def get_model_error(
    backend: str,
    model: str,
    device: str,
    compute_type: str,
    *,
    path: Path = STATE_PATH,
) -> str | None:
    key = model_key(backend, model, device, compute_type)
    return load_model_state(path=path).errors.get(key)
