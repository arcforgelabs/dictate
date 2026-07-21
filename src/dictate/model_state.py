"""Persistent model preparation state for tray/runtime decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from dictate.platform_paths import user_data_dir

STATE_PATH = user_data_dir() / "model-state.json"


@dataclass(slots=True)
class ModelState:
    prepared: set[str] = field(default_factory=set)
    errors: dict[str, str] = field(default_factory=dict)


def model_key(backend: str, model: str, device: str, compute_type: str) -> str:
    return f"{backend}|{model}|{device}|{compute_type}"


def load_model_state(path: Path = STATE_PATH) -> ModelState:
    if not path.is_file():
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
