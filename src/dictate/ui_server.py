"""Local control-surface HTTP server for the Tauri "Quiet Console" UI.

The shipping Dictate process stays the single source of truth for STT, audio,
hotkeys, config, history and typing. This module exposes a small, loopback-only,
token-authenticated JSON API so a webview front-end (``ui/`` built and hosted by
``ui-shell/``) can reflect and drive that state without becoming a second daemon.

Design notes
------------
* ``UiBackend`` holds all the logic and returns plain ``dict`` / ``list`` values.
  Every external dependency (config path, history store, api-key functions,
  startup hooks, clock) is injectable, so the backend is unit-testable without
  sockets, a keyring or the real autostart files.
* The HTTP layer (``UiRequestHandler`` / ``serve``) is a thin adapter: it does
  auth, JSON encode/decode and routing, then calls into ``UiBackend``.
* Nothing binds beyond ``127.0.0.1`` and every mutating route requires the bearer
  token written to the runtime handshake file. See ``write_runtime_handshake``.
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable
from urllib.parse import urlparse, parse_qs

from dictate import api_keys as api_keys_mod
from dictate import config as config_mod
from dictate import startup as startup_mod
from dictate import update_status as update_status_mod
from dictate.history import HistoryStore
from dictate.provider_supervisor import ProviderSupervisor
from dictate.hotkey import (
    DEFAULT_PUSH_TO_TALK_COMBO,
    format_hotkey_combo,
    normalize_push_to_talk_combo,
)
from dictate.platform_paths import user_config_dir, user_data_dir
from dictate.stt.factory import (
    BACKEND_REGISTRY,
    DEFAULT_MODELS,
    resolve_default_local_model,
    resolve_model_name,
)
from dictate.version import RELEASE_VERSION

logger = logging.getLogger(__name__)

RUNTIME_HANDSHAKE_PATH = user_data_dir() / "ui-server.json"
UI_PREFS_PATH = user_data_dir() / "ui-prefs.json"

# Default UI-only preferences (things the engine does not already persist).
DEFAULT_PREFS: dict[str, Any] = {
    "theme": "system",          # "light" | "dark" | "system"
    "activation": "hold",       # "hold" | "toggle"
    "trayOnly": True,
    "overlay": True,
    "sound": False,
    "ambient": True,
}
_VALID_THEMES = ("light", "dark", "system")
_VALID_ACTIVATIONS = ("hold", "toggle")

# Provider display metadata. Backend ids / models are grounded in stt.factory;
# only the human-facing bits (brand glyph, key shape, blurb) live here.
PROVIDER_META: dict[str, dict[str, Any]] = {
    "faster-whisper": {
        "provider": "Local",
        "brand": None,
        "local": True,
        "desc": "Runs on this machine — no key, nothing leaves your device.",
    },
    "whisperx": {
        "provider": "Local",
        "brand": None,
        "local": True,
        "experimental": True,
        "desc": "Experimental local meeting diarization with WhisperX and pyannote.",
    },
    "openai": {
        "provider": "OpenAI",
        "brand": "openai",
        "local": False,
        "desc": "Fast, accurate hosted transcription.",
        "keyName": "OpenAI API key",
        "keyPrefix": "sk-",
    },
    "xai": {
        "provider": "xAI",
        "brand": "xai",
        "local": False,
        "desc": "Grok speech-to-text, hosted.",
        "keyName": "xAI API key",
        "keyPrefix": "xai-",
    },
    "gemini": {
        "provider": "Google",
        "brand": "gemini",
        "local": False,
        "desc": "Gemini multimodal, hosted.",
        "keyName": "Gemini API key",
        "keyPrefix": "AIza",
    },
}
# Order shown in the Model view (local first, matching the design).
PROVIDER_ORDER = ("faster-whisper", "whisperx", "openai", "xai", "gemini")


class ApiError(Exception):
    """Raised inside the backend to map to a specific HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------------- #
# Provider health — thread-safe runtime outcome tracker
# --------------------------------------------------------------------------- #
class _ProviderHealthState:
    """Thread-safe tracker for the last online-provider transcription outcome.

    Updated by ``UiBackend.connect_engine_health`` when the engine reports a
    result. The UI reads it via ``get_state()``; changes are also pushed via SSE.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._healthy: bool = True
        self._reason: str | None = None

    def report(self, healthy: bool, reason: str | None = None) -> bool:
        """Update state. Returns ``True`` if the state changed."""
        with self._lock:
            changed = self._healthy != healthy or self._reason != reason
            self._healthy = healthy
            self._reason = reason
            return changed

    def get(self) -> tuple[bool, str | None]:
        with self._lock:
            return self._healthy, self._reason


# --------------------------------------------------------------------------- #
# Preferences store (UI-only settings the engine does not persist itself)
# --------------------------------------------------------------------------- #
class UiPrefsStore:
    """Tiny JSON-backed store for UI-only preferences."""

    def __init__(self, path: Path = UI_PREFS_PATH) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        prefs = dict(DEFAULT_PREFS)
        if not self._path.is_file():
            return prefs
        try:
            raw = json.loads(self._path.read_text())
        except Exception:  # noqa: BLE001
            return prefs
        if isinstance(raw, dict):
            for key in DEFAULT_PREFS:
                if key in raw:
                    prefs[key] = raw[key]
        return self._coerce(prefs)

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        prefs = self.load()
        for key, value in changes.items():
            if key in DEFAULT_PREFS:
                prefs[key] = value
        prefs = self._coerce(prefs)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(prefs, indent=2))
        return prefs

    @staticmethod
    def _coerce(prefs: dict[str, Any]) -> dict[str, Any]:
        if prefs.get("theme") not in _VALID_THEMES:
            prefs["theme"] = DEFAULT_PREFS["theme"]
        if prefs.get("activation") not in _VALID_ACTIVATIONS:
            prefs["activation"] = DEFAULT_PREFS["activation"]
        for flag in ("trayOnly", "overlay", "sound", "ambient"):
            prefs[flag] = bool(prefs.get(flag, DEFAULT_PREFS[flag]))
        return prefs


# --------------------------------------------------------------------------- #
# Event broker — fan-out of recording/status events to SSE subscribers
# --------------------------------------------------------------------------- #
class EventBroker:
    """Thread-safe publish/subscribe used to push live state to the webview."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[Queue] = []

    def subscribe(self) -> Queue:
        q: Queue = Queue(maxsize=64)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: Queue) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event_type: str, **data: Any) -> None:
        payload = {"type": event_type, **data}
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except Exception:  # noqa: BLE001 — drop on a full/closed queue
                pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


# --------------------------------------------------------------------------- #
# Backend — all logic, fully injectable, returns plain data
# --------------------------------------------------------------------------- #
@dataclass
class UiBackend:
    """Reflective control surface over the Dictate engine state."""

    config_path: Path = field(default_factory=lambda: config_mod.CONFIG_PATH)
    history_store: HistoryStore | None = None
    prefs_store: UiPrefsStore | None = None
    broker: EventBroker | None = None
    daemon: Any | None = None
    provider_health: _ProviderHealthState = field(default_factory=_ProviderHealthState)
    # Optional supervisor wired at runtime by connect_supervisor().
    # When present, providerHealth returns richer state; SSE events are emitted
    # as provider-degraded / provider-recovered rather than provider-health.
    _supervisor: ProviderSupervisor | None = field(default=None, repr=False)

    # Injectable hooks (default to the real implementations).
    save_api_key: Callable[[str, str], None] = api_keys_mod.save_api_key
    clear_api_key: Callable[[str], None] = api_keys_mod.clear_api_key
    api_key_status: Callable[..., api_keys_mod.ApiKeyStatus] = api_keys_mod.api_key_status
    validate_api_key_format: Callable[[str, str], str | None] = (
        api_keys_mod.validate_api_key_format
    )
    secret_store_description: Callable[[], str] = api_keys_mod.secret_store_description
    secret_store_available: Callable[[], bool] = api_keys_mod.secret_store_available
    check_update_status: Callable[[], update_status_mod.UpdateStatus] = (
        update_status_mod.check_update_status
    )
    start_update_flow: Callable[[], update_status_mod.UpdateFlow] = (
        update_status_mod.start_update_flow
    )
    startup_enabled: Callable[[], bool] = startup_mod.startup_enabled
    set_startup_enabled: Callable[[bool], None] = startup_mod.set_startup_enabled
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def __post_init__(self) -> None:
        if self.history_store is None:
            self.history_store = HistoryStore()
        if self.prefs_store is None:
            self.prefs_store = UiPrefsStore()

    # ----- read ----------------------------------------------------------- #
    def _effective_model(self, cfg: config_mod.Config, backend: str) -> str:
        """The model the daemon will actually run for ``backend``.

        For faster-whisper with no saved model, this is the hardware-aware local
        default (so the UI/doctor/model-list agree with the daemon on a weak box);
        a saved model always wins.
        """
        if backend == "faster-whisper" and not cfg.stt_model:
            return resolve_default_local_model(cfg.stt_device or "auto")
        return resolve_model_name(backend, cfg.stt_model)

    def get_state(self) -> dict[str, Any]:
        cfg = config_mod.load_config(self.config_path)
        prefs = self.prefs_store.load()
        backend = cfg.stt_backend or "faster-whisper"
        if backend not in BACKEND_REGISTRY:
            backend = "faster-whisper"
        model = self._effective_model(cfg, backend)
        return {
            "version": RELEASE_VERSION,
            "model": {"id": f"{backend}/{model}", "backend": backend, "model": model},
            "models": self._models(cfg),
            "shortcut": self._shortcut(cfg, prefs),
            "hotwords": list(cfg.hotwords),
            "history": self.get_history(),
            "device": {
                "name": "Default device",
                "device": cfg.stt_device or "auto",
                "compute": cfg.stt_compute_type or "int8",
            },
            "providers": self._providers(cfg),
            "prefs": prefs,
            "notes": self._notes_payload(),
            "startup": bool(self._safe(self.startup_enabled, False)),
            "secretStore": self._safe(self.secret_store_description, "OS secret store"),
            "secretStoreAvailable": bool(self._safe(self.secret_store_available, False)),
            "micConnected": True,
            "providerHealth": self._compute_provider_health(cfg),
        }

    def _shortcut(self, cfg: config_mod.Config, prefs: dict[str, Any]) -> dict[str, Any]:
        combo = cfg.push_to_talk_combo or cfg.push_to_talk_key or DEFAULT_PUSH_TO_TALK_COMBO
        combo = normalize_push_to_talk_combo(combo)
        display = format_hotkey_combo(combo).split(" + ")
        return {"combo": combo, "display": display, "activation": prefs["activation"]}

    def _models(self, cfg: config_mod.Config) -> list[dict[str, Any]]:
        # Effective local default matches what the daemon runs on THIS machine, so
        # the model list's "default" flag agrees with get_state on a weak box.
        # A saved stt_model only counts as the faster-whisper default when the saved
        # backend IS faster-whisper; otherwise (e.g. a hosted cloud selection) resolve
        # the hardware-aware local tier instead of borrowing the hosted model name.
        fw_saved = cfg.stt_model if (cfg.stt_backend or "faster-whisper") == "faster-whisper" else None
        fw_default = fw_saved or resolve_default_local_model(cfg.stt_device or "auto")
        models: list[dict[str, Any]] = []
        for backend in PROVIDER_ORDER:
            if backend not in BACKEND_REGISTRY:
                continue
            meta = PROVIDER_META.get(backend, {})
            default_model = fw_default if backend == "faster-whisper" else DEFAULT_MODELS[backend]
            for model in BACKEND_REGISTRY[backend].model_examples:
                entry: dict[str, Any] = {
                    "id": f"{backend}/{model}",
                    "backend": backend,
                    "model": model,
                    "name": model,
                    "provider": meta.get("provider", backend),
                    "brand": meta.get("brand"),
                    "local": bool(meta.get("local")),
                    "experimental": bool(meta.get("experimental")),
                    "desc": meta.get("desc", ""),
                    "default": model == default_model,
                }
                if not meta.get("local"):
                    entry["keyName"] = meta.get("keyName", f"{backend} API key")
                    entry["keyPrefix"] = meta.get("keyPrefix", "")
                    entry["configured"] = self._provider_ready(backend, cfg)
                models.append(entry)
        # The local provider's display name keeps the "provider · model" form.
        for entry in models:
            if entry["local"]:
                entry["name"] = f"{entry['backend']} · {entry['model']}"
        return models

    def _providers(self, cfg: config_mod.Config) -> dict[str, dict[str, Any]]:
        providers: dict[str, dict[str, Any]] = {}
        for backend in api_keys_mod.API_BACKENDS:
            status = self._safe(lambda b=backend: self._provider_status(b, cfg), None)
            if status is None:
                providers[backend] = {"configured": False, "status": "None"}
            else:
                providers[backend] = {
                    "configured": status.ready,
                    "status": status.status,
                }
        return providers

    def _provider_ready(self, backend: str, cfg: config_mod.Config | None = None) -> bool:
        cfg = cfg or config_mod.load_config(self.config_path)
        status = self._safe(lambda: self._provider_status(backend, cfg), None)
        return bool(status and status.ready)

    def _provider_status(
        self,
        backend: str,
        cfg: config_mod.Config,
    ) -> api_keys_mod.ApiKeyStatus:
        command = {
            "openai": cfg.openai_api_key_command,
            "xai": cfg.xai_api_key_command,
            "gemini": cfg.gemini_api_key_command,
        }.get(backend)
        if command:
            api_key = api_keys_mod._api_key_from_command(command, backend=backend)
            return self.api_key_status(
                backend, api_key=api_key, include_command=False, log_failures=False
            )
        return self.api_key_status(backend, log_failures=False)

    def get_history(self) -> list[dict[str, Any]]:
        entries = self.history_store.load()
        out: list[dict[str, Any]] = []
        for entry in entries:
            out.append(
                {
                    "id": entry.id,
                    "text": entry.text,
                    "time": self._history_label(entry.created_at),
                    "createdAt": entry.created_at,
                }
            )
        return out

    def _history_label(self, created_at: str) -> str:
        try:
            when = datetime.fromisoformat(created_at)
        except ValueError:
            return created_at
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        local = when.astimezone()
        # Built manually rather than strftime("%-I") — the %- padding flag is a
        # glibc extension and raises on Windows.
        hour12 = local.hour % 12 or 12
        meridiem = "PM" if local.hour >= 12 else "AM"
        clock = f"{hour12}:{local.minute:02d} {meridiem}"
        return f"{clock} · {self._relative(when)}"

    def _relative(self, when: datetime) -> str:
        delta = self.now() - when
        secs = int(delta.total_seconds())
        if secs < 45:
            return "just now"
        if secs < 3600:
            return f"{max(1, secs // 60)}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"

    # ----- mutate --------------------------------------------------------- #
    def patch_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ApiError(400, "expected a JSON object")

        if "model" in payload:
            self._set_model(payload["model"])
        if "device" in payload:
            self._set_device(payload["device"])
        if "shortcut" in payload:
            self._set_shortcut(payload["shortcut"])
        if "prefs" in payload:
            self._set_prefs(payload["prefs"])
        if "startup" in payload:
            self._set_startup(payload["startup"])
        return self.get_state()

    def _set_model(self, model: Any) -> None:
        backend = model.get("backend") if isinstance(model, dict) else None
        name = model.get("model") if isinstance(model, dict) else None
        if isinstance(model, str) and "/" in model:
            backend, _, name = model.partition("/")
        if backend not in BACKEND_REGISTRY:
            raise ApiError(400, f"unknown backend: {backend!r}")
        if backend == "faster-whisper":
            # The GUI has no local model-tier picker (the privacy pill is a plain
            # local on/off), so any faster-whisper selection means "use the right
            # local model for THIS machine". Resolve it hardware-aware rather than
            # trust the client's hardcoded id, which would otherwise pin turbo in
            # config forever on a weak CPU (saved model always wins → resolver never
            # runs → the OOM/swap case the resolver exists to prevent).
            # This is authoritative because _set_model only fires on an explicit
            # PATCH /api/config user action, never on page load (load is get_state).
            cfg = config_mod.load_config(self.config_path)
            resolved = resolve_default_local_model(cfg.stt_device or "auto")
        else:
            resolved = resolve_model_name(backend, name)
        config_mod.set_stt_selection(backend, resolved, path=self.config_path)

    def _set_device(self, device: Any) -> None:
        if not isinstance(device, dict):
            raise ApiError(400, "device must be an object")
        cfg = config_mod.load_config(self.config_path)
        dev = device.get("device", cfg.stt_device or "auto")
        compute = device.get("compute", cfg.stt_compute_type or "int8")
        config_mod.set_stt_runtime_profile(str(dev), str(compute), path=self.config_path)

    def _set_shortcut(self, shortcut: Any) -> None:
        combo = None
        activation = None
        if isinstance(shortcut, dict):
            combo = shortcut.get("combo")
            activation = shortcut.get("activation")
        elif isinstance(shortcut, str):
            combo = shortcut
        if combo:
            config_mod.set_push_to_talk_combo(str(combo), path=self.config_path)
        if activation is not None:
            if activation not in _VALID_ACTIVATIONS:
                raise ApiError(400, f"invalid activation: {activation!r}")
            self.prefs_store.update({"activation": activation})

    def _set_prefs(self, prefs: Any) -> dict[str, Any]:
        if not isinstance(prefs, dict):
            raise ApiError(400, "prefs must be an object")
        if "theme" in prefs and prefs["theme"] not in _VALID_THEMES:
            raise ApiError(400, f"invalid theme: {prefs['theme']!r}")
        return self.prefs_store.update(prefs)

    def _set_startup(self, enabled: Any) -> None:
        try:
            self.set_startup_enabled(bool(enabled))
        except Exception as exc:  # noqa: BLE001
            raise ApiError(500, f"could not change startup: {exc}") from exc

    def add_hotwords(self, words: list[str]) -> dict[str, Any]:
        if not isinstance(words, list):
            raise ApiError(400, "words must be a list")
        cleaned: list[str] = []
        for word in words:
            if isinstance(word, str):
                cleaned.extend(config_mod.parse_hotwords_text(word))
        added = config_mod.add_hotwords(cleaned, path=self.config_path)
        return {"added": added, "hotwords": list(config_mod.load_config(self.config_path).hotwords)}

    def remove_hotword(self, word: str) -> dict[str, Any]:
        if not isinstance(word, str) or not word.strip():
            raise ApiError(400, "word is required")
        removed = config_mod.remove_hotwords([word], path=self.config_path)
        return {
            "removed": removed,
            "hotwords": list(config_mod.load_config(self.config_path).hotwords),
        }

    def clear_history(self) -> dict[str, Any]:
        self.history_store._save([])  # rolling buffer reset
        return {"history": []}

    def start_note_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        started = bool(daemon.start_note_recording())
        return self._notes_payload()

    def stop_note_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        daemon.stop_note_recording()
        return self._notes_payload()

    def pause_note_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        daemon.pause_note_recording()
        return self._notes_payload()

    def resume_note_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        daemon.resume_note_recording()
        return self._notes_payload()

    def toggle_note_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        daemon.toggle_note_recording()
        return self._notes_payload()

    def save_provider_key(self, backend: str, api_key: str) -> dict[str, Any]:
        if backend not in api_keys_mod.API_BACKENDS:
            raise ApiError(400, f"unknown provider: {backend!r}")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ApiError(400, "an API key is required")
        fmt_error = self._safe(lambda: self.validate_api_key_format(backend, api_key), None)
        if fmt_error:
            raise ApiError(422, fmt_error)
        try:
            self.save_api_key(backend, api_key)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(500, f"could not save key: {exc}") from exc
        config_mod.set_api_key_command(backend, None, path=self.config_path)
        return {"backend": backend, "configured": self._provider_ready(backend)}

    def clear_provider_key(self, backend: str) -> dict[str, Any]:
        if backend not in api_keys_mod.API_BACKENDS:
            raise ApiError(400, f"unknown provider: {backend!r}")
        try:
            self.clear_api_key(backend)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(500, f"could not clear key: {exc}") from exc
        config_mod.set_api_key_command(backend, None, path=self.config_path)
        return {"backend": backend, "configured": False}

    def run_doctor(self) -> dict[str, Any]:
        cfg = config_mod.load_config(self.config_path)
        backend = cfg.stt_backend or "faster-whisper"
        if backend not in BACKEND_REGISTRY:
            backend = "faster-whisper"
        # Report the model the daemon will actually run (hardware-aware for a fresh
        # weak-box config), respecting a saved model first.
        model = self._effective_model(cfg, backend)
        combo = cfg.push_to_talk_combo or DEFAULT_PUSH_TO_TALK_COMBO
        checks = [
            {"label": "Microphone access", "sub": "Default device", "ok": True},
            {"label": "Model loads", "sub": f"{backend} · {model}", "ok": True},
            {"label": "Output backend", "sub": "Typing into focused app", "ok": True},
            {
                "label": "Secret store",
                "sub": self._safe(self.secret_store_description, "OS secret store"),
                "ok": bool(self._safe(self.secret_store_available, False)),
            },
            {
                "label": "Shortcut registered",
                "sub": format_hotkey_combo(normalize_push_to_talk_combo(combo)),
                "ok": True,
            },
        ]
        return {"checks": checks, "ok": all(c["ok"] for c in checks)}

    def get_update_status(self) -> dict[str, Any]:
        status = self.check_update_status()
        return {
            "currentVersion": status.current_version,
            "latestVersion": status.latest_version,
            "updateAvailable": status.update_available,
            "checked": status.checked,
            "error": status.error,
            "url": status.url,
            "platform": status.platform,
            "installKind": status.install_kind,
            "phase": status.phase,
            "step": status.step,
            "progress": status.progress,
            "actions": status.actions or [],
            "commands": status.commands or {},
            "missingDeps": status.missing_deps or [],
            "errorCode": status.error_code,
            "errorDetail": status.error_detail,
        }

    def start_update(self) -> dict[str, Any]:
        try:
            flow = self.start_update_flow()
        except Exception as exc:  # noqa: BLE001
            raise ApiError(500, f"could not start update: {exc}") from exc
        return {
            "mode": flow.mode,
            "started": flow.started,
            "url": flow.url,
            "message": flow.message,
            "platform": flow.platform,
            "installKind": flow.install_kind,
            "phase": flow.phase,
            "step": flow.step,
            "progress": flow.progress,
            "actions": flow.actions or [],
            "commands": flow.commands or {},
            "missingDeps": flow.missing_deps or [],
            "errorCode": flow.error_code,
            "errorDetail": flow.error_detail,
        }

    @staticmethod
    def _safe(fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return default

    def _note_recording_active(self) -> bool:
        return bool(self.daemon is not None and getattr(self.daemon, "note_recording_active", False))

    def _note_recording_paused(self) -> bool:
        return bool(self.daemon is not None and getattr(self.daemon, "note_recording_paused", False))

    def _notes_payload(self) -> dict[str, Any]:
        paused = self._note_recording_paused()
        payload: dict[str, Any] = {
            "recording": self._note_recording_active(),
            "paused": paused,
        }
        if paused and self.daemon is not None:
            reason = getattr(self.daemon, "note_pause_reason", None)
            if isinstance(reason, str) and reason:
                payload["pauseReason"] = reason
        return payload

    # ----- provider health ------------------------------------------------ #
    def _compute_provider_health(self, cfg: config_mod.Config) -> dict[str, Any]:
        """Return provider health state for the UI.

        Shape (superset of the legacy ``{healthy, status, mode}``):
        - ``healthy``    bool       — backward compat; False when degraded or no-key
        - ``status``     str        — backward compat; reason string or "ok"
        - ``mode``       str        — "private" | "online"
        - ``preferred``  str        — configured stt_backend
        - ``active``     str        — currently transcribing backend
        - ``degraded``   bool       — True when remote failed, using local fallback
        - ``reason``     str|null   — failure class or null
        - ``since``      str|null   — ISO-8601 UTC timestamp of degradation start

        Logic:
        * ``private`` (faster-whisper) → always healthy; no key needed.
        * Supervisor present → read full state from supervisor.
        * Online + no key → unhealthy, status ``no-key``.
        * Online + key present → reflect the tracked runtime outcome.
        """
        backend = cfg.stt_backend or "faster-whisper"
        is_private = backend == "faster-whisper"
        mode = "private" if is_private else "online"

        # --- supervisor path (richer state) ---
        if self._supervisor is not None:
            sup_state = self._supervisor.get_state()
            preferred = sup_state.get("preferred", backend)
            active = sup_state.get("active", backend)
            degraded = bool(sup_state.get("degraded", False))
            reason = sup_state.get("reason")
            since = sup_state.get("since")
            healthy = not degraded
            status = reason if degraded else "ok"
            # Still surface no-key as unhealthy even when supervisor is healthy
            if not is_private and healthy:
                has_key = self._safe(lambda: api_keys_mod.has_stored_api_key(preferred), False)
                if not has_key:
                    healthy = False
                    status = "no-key"
            return {
                "healthy": healthy,
                "status": status,
                "mode": mode,
                "preferred": preferred,
                "active": active,
                "degraded": degraded,
                "reason": reason,
                "since": since,
            }

        # --- legacy path (no supervisor) ---
        if is_private:
            return {
                "healthy": True,
                "status": "ok",
                "mode": mode,
                "preferred": backend,
                "active": backend,
                "degraded": False,
                "reason": None,
                "since": None,
            }

        # Online: check that a key is present
        has_key = self._safe(lambda: api_keys_mod.has_stored_api_key(backend), False)
        if not has_key:
            return {
                "healthy": False,
                "status": "no-key",
                "mode": mode,
                "preferred": backend,
                "active": backend,
                "degraded": False,
                "reason": None,
                "since": None,
            }

        # Online + key present: reflect the tracked runtime outcome
        healthy, reason = self.provider_health.get()
        if not healthy:
            return {
                "healthy": False,
                "status": reason or "unreachable",
                "mode": mode,
                "preferred": backend,
                "active": "faster-whisper",
                "degraded": True,
                "reason": reason or "unreachable",
                "since": None,
            }

        return {
            "healthy": True,
            "status": "ok",
            "mode": mode,
            "preferred": backend,
            "active": backend,
            "degraded": False,
            "reason": None,
            "since": None,
        }

    def connect_supervisor(self, supervisor: ProviderSupervisor) -> None:
        """Wire a ``ProviderSupervisor`` to this backend for SSE and get_state.

        Installs ``on_degraded`` / ``on_recovered`` callbacks that update
        ``provider_health`` and publish the new ``provider-degraded`` /
        ``provider-recovered`` SSE events.  Call after the supervisor is created
        and before the daemon starts transcribing.
        """
        self._supervisor = supervisor
        ph = self.provider_health
        broker = self.broker

        def _on_degraded(state: dict) -> None:
            ph.report(False, state.get("reason"))
            if broker is not None:
                broker.publish(
                    "provider-degraded",
                    preferred=state.get("preferred"),
                    active=state.get("active"),
                    reason=state.get("reason"),
                    since=state.get("since"),
                )

        def _on_recovered(state: dict) -> None:
            ph.report(True, None)
            if broker is not None:
                broker.publish(
                    "provider-recovered",
                    preferred=state.get("preferred"),
                    active=state.get("active"),
                )

        supervisor._on_degraded = _on_degraded
        supervisor._on_recovered = _on_recovered

    def connect_engine_health(self, engine: Any) -> None:
        """Wire this backend's health tracker as the engine's ``health_sink``.

        Legacy convenience method for setups without a ``ProviderSupervisor``.
        Installs a callback that updates ``provider_health`` and pushes a
        ``provider-health`` SSE event on every state change.
        """
        ph = self.provider_health
        broker = self.broker

        def _sink(healthy: bool, reason: str | None) -> None:
            changed = ph.report(healthy, reason)
            if changed and broker is not None:
                broker.publish(
                    "provider-health",
                    healthy=bool(healthy),
                    status=reason or "ok",
                )

        try:
            engine.health_sink = _sink
        except Exception:  # noqa: BLE001
            logger.warning("Could not wire health sink to engine")

    def _require_daemon(self) -> Any:
        if self.daemon is None:
            raise ApiError(409, "note recording requires a running Dictate daemon")
        return self.daemon


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #
@dataclass
class _Response:
    status: int
    body: Any = None
    sse: Queue | None = None


class UiRequestHandler(BaseHTTPRequestHandler):
    server_version = "DictateUI/1.0"
    protocol_version = "HTTP/1.1"

    # injected by serve() onto the server instance
    backend: UiBackend
    token: str
    broker: EventBroker

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401 — quiet by default
        logger.debug("ui-server %s", fmt % args)

    # -- helpers ---------------------------------------------------------- #
    def _authorized(self, query: dict[str, list[str]]) -> bool:
        token = self.server.token  # type: ignore[attr-defined]
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            if secrets.compare_digest(header[7:], token):
                return True
        alt = self.headers.get("X-Dictate-Token", "")
        if alt and secrets.compare_digest(alt, token):
            return True
        qtok = (query.get("token") or [""])[0]
        if qtok and secrets.compare_digest(qtok, token):
            return True
        return False

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, f"invalid JSON: {exc}") from exc

    def _send_json(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type,X-Dictate-Token")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")

    # -- verbs ------------------------------------------------------------ #
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        # health is unauthenticated so the shell can probe readiness
        if path == "/api/health" and method == "GET":
            self._send_json(200, {"status": "ok", "version": RELEASE_VERSION})
            return

        if not self._authorized(query):
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            response = self._route(method, path)
        except ApiError as exc:
            self._send_json(exc.status, {"error": exc.message})
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("ui-server route failed")
            self._send_json(500, {"error": str(exc)})
            return

        if response.sse is not None:
            self._stream(response.sse)
            return
        self._send_json(response.status, response.body)

    def _route(self, method: str, path: str) -> _Response:
        backend: UiBackend = self.server.backend  # type: ignore[attr-defined]

        if path == "/api/state" and method == "GET":
            return _Response(200, backend.get_state())
        if path == "/api/config" and method == "PATCH":
            return _Response(200, backend.patch_config(self._read_json() or {}))
        if path == "/api/hotwords" and method == "POST":
            body = self._read_json() or {}
            words = body.get("words") if isinstance(body, dict) else None
            return _Response(200, backend.add_hotwords(words or []))
        if path == "/api/hotwords" and method == "DELETE":
            body = self._read_json() or {}
            return _Response(200, backend.remove_hotword((body or {}).get("word", "")))
        if path == "/api/history" and method == "GET":
            return _Response(200, {"history": backend.get_history()})
        if path == "/api/history" and method == "DELETE":
            return _Response(200, backend.clear_history())
        if path == "/api/notes/start" and method == "POST":
            return _Response(200, backend.start_note_recording())
        if path == "/api/notes/stop" and method == "POST":
            return _Response(200, backend.stop_note_recording())
        if path == "/api/notes/pause" and method == "POST":
            return _Response(200, backend.pause_note_recording())
        if path == "/api/notes/resume" and method == "POST":
            return _Response(200, backend.resume_note_recording())
        if path == "/api/notes/toggle" and method == "POST":
            return _Response(200, backend.toggle_note_recording())
        if path == "/api/api-keys" and method == "POST":
            body = self._read_json() or {}
            return _Response(
                200, backend.save_provider_key(body.get("backend", ""), body.get("apiKey", ""))
            )
        if path == "/api/api-keys" and method == "DELETE":
            body = self._read_json() or {}
            return _Response(200, backend.clear_provider_key(body.get("backend", "")))
        if path == "/api/doctor" and method == "POST":
            return _Response(200, backend.run_doctor())
        if path == "/api/update-status" and method == "GET":
            return _Response(200, backend.get_update_status())
        if path == "/api/update" and method == "POST":
            return _Response(200, backend.start_update())
        if path == "/api/events" and method == "GET":
            return _Response(200, sse=self.server.broker.subscribe())  # type: ignore[attr-defined]
        raise ApiError(404, f"no route for {method} {path}")

    def _stream(self, queue: Queue) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()
        broker: EventBroker = self.server.broker  # type: ignore[attr-defined]
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = queue.get(timeout=15)
                    chunk = f"data: {json.dumps(event)}\n\n".encode("utf-8")
                except Empty:
                    chunk = b": ping\n\n"
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ValueError):
            pass
        finally:
            broker.unsubscribe(queue)


def write_runtime_handshake(
    url: str, token: str, *, pid: int | None = None, path: Path = RUNTIME_HANDSHAKE_PATH
) -> Path:
    """Persist the URL+token so the Tauri shell can find and authenticate."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "url": url,
        "token": token,
        "pid": pid if pid is not None else os.getpid(),
        # The shell compares this against its own version and restarts a stale
        # engine after an update — shell + engine always run the same version.
        "version": RELEASE_VERSION,
    }
    path.write_text(json.dumps(payload, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


@dataclass
class UiServerHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread
    url: str
    token: str
    backend: UiBackend
    broker: EventBroker

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread.is_alive():
            self.thread.join(timeout=2)


def serve(
    backend: UiBackend | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    token: str | None = None,
    broker: EventBroker | None = None,
    write_handshake: bool = True,
    handshake_path: Path = RUNTIME_HANDSHAKE_PATH,
) -> UiServerHandle:
    """Start the UI control server in a background thread.

    A random ephemeral port and bearer token are chosen unless supplied. The
    URL + token handshake is written to ``handshake_path`` for the shell.
    """
    broker = broker or EventBroker()
    backend = backend or UiBackend(broker=broker)
    if backend.broker is None:
        backend.broker = broker
    token = token or secrets.token_urlsafe(32)

    server = ThreadingHTTPServer((host, port), UiRequestHandler)
    server.backend = backend  # type: ignore[attr-defined]
    server.token = token  # type: ignore[attr-defined]
    server.broker = broker  # type: ignore[attr-defined]
    server.daemon_threads = True

    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}"

    thread = threading.Thread(target=server.serve_forever, name="dictate-ui-server", daemon=True)
    thread.start()

    if write_handshake:
        write_runtime_handshake(url, token, path=handshake_path)
        logger.info("Dictate UI server listening on %s", url)

    return UiServerHandle(
        server=server, thread=thread, url=url, token=token, backend=backend, broker=broker
    )


def main() -> None:  # pragma: no cover — manual smoke entry
    logging.basicConfig(level=logging.INFO)
    handle = serve()
    print(f"Dictate UI server: {handle.url}")
    print(f"Handshake: {RUNTIME_HANDSHAKE_PATH}")
    try:
        handle.thread.join()
    except KeyboardInterrupt:
        handle.shutdown()


if __name__ == "__main__":  # pragma: no cover
    main()
