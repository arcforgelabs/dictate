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
import os
import secrets
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable
from urllib.parse import urlparse, parse_qs


from dictate import config as config_mod
from dictate import startup as startup_mod
from dictate import update_status as update_status_mod
from dictate.history import HistoryStore
from dictate.hotkey import (
    DEFAULT_PUSH_TO_TALK_COMBO,
    format_hotkey_combo,
    normalize_push_to_talk_combo,
)
from dictate.note_store import NoteSegment, NoteStore
from dictate.platform_paths import user_config_dir, user_data_dir
from dictate.stt.factory import (
    BACKEND_REGISTRY,
    DEFAULT_MODELS,
    check_backend_readiness,
    create_speech_to_text,
    resolve_default_local_backend,
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
    "outputFormat": "plain",     # "plain" | "markdown"
}
PROVIDER_META: dict[str, dict[str, Any]] = {
    "faster-whisper": {
        "provider": "Local",
        "brand": None,
        "local": True,
        "desc": "Runs on this machine — no key, nothing leaves your device.",
    },
    "parakeet": {
        "provider": "Local",
        "brand": None,
        "local": True,
        "desc": "Runs on this machine — fast, accurate English, nothing leaves your device.",
    },
    "parakeet-pyannote": {
        "provider": "Local",
        "brand": None,
        "local": True,
        "experimental": True,
        "desc": "Local Meeting backend with Parakeet and speaker labels.",
    },
    "parakeet-diarizen": {
        "provider": "Local",
        "brand": None,
        "local": True,
        "experimental": True,
        "desc": "Local Meeting backend with Parakeet and DiariZen speaker labels.",
    },
    "parakeet-sortformer": {
        "provider": "Local",
        "brand": None,
        "local": True,
        "experimental": True,
        "desc": "Local Meeting backend with Parakeet and NVIDIA Sortformer speakers.",
    },
    "whisperx": {
        "provider": "Local",
        "brand": None,
        "local": True,
        "experimental": True,
        "desc": "Experimental local meeting diarization with WhisperX and pyannote.",
    },
}

PROVIDER_ORDER = (
    "parakeet",
    "parakeet-pyannote",
    "parakeet-diarizen",
    "parakeet-sortformer",
    "faster-whisper",
    "whisperx",
)

_VALID_THEMES = ("light", "dark", "system")
_VALID_ACTIVATIONS = ("hold", "toggle")
_VALID_OUTPUT_FORMATS = ("plain", "markdown")
_PRIVATE_DICTATION_BACKEND = "parakeet"
_PRIVATE_DICTATION_MODEL = "parakeet-tdt-0.6b-v2"
_LEGACY_REGULAR_BACKENDS = {"faster-whisper", "whisperx"}


class ApiError(Exception):
    """Raised inside the backend to map to a specific HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _dedupe_text(text: str) -> str:
    return " ".join(text.split()).casefold()


def _meeting_blocking_warning(warnings: list[str]) -> str | None:
    for warning in warnings:
        normalized = warning.casefold()
        if "pyannote/speaker-diarization-community-1 is gated" in normalized:
            return warning
    return None


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

    def __init__(self, path: Path = UI_PREFS_PATH, meta_path: Path | None = None) -> None:
        self._path = path
        self._meta_path = meta_path or path.with_name(f"{path.stem}-sync-meta{path.suffix}")

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
        accepted: set[str] = set()
        for key, value in changes.items():
            if key in DEFAULT_PREFS:
                prefs[key] = value
                accepted.add(key)
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
        if prefs.get("outputFormat") not in _VALID_OUTPUT_FORMATS:
            prefs["outputFormat"] = DEFAULT_PREFS["outputFormat"]
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
    note_store: NoteStore | None = None
    prefs_store: UiPrefsStore | None = None
    broker: EventBroker | None = None
    daemon: Any | None = None
    provider_health: _ProviderHealthState = field(default_factory=_ProviderHealthState)
    # Injectable hooks (default to the real implementations).
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
        if self.note_store is None:
            self.note_store = NoteStore()
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

    def _load_ui_config(self) -> config_mod.Config:
        """Load config and migrate stale regular dictation backends for the UI.

        The UI ships Parakeet as the private regular dictation default. Legacy
        faster-whisper / whisperx values are treated as stale regular dictation
        state and rewritten so the runtime follows the shipped default instead
        of continuing to hydrate the old multilingual local path.
        """
        cfg = config_mod.load_config(self.config_path)
        # Legacy local backends, and backends this build no longer ships
        # (hosted xAI / OpenAI / Gemini), are stale dictation state. The daemon
        # already ignores them and runs Parakeet; rewrite the saved selection
        # so the About row reports that same engine instead of a Whisper name.
        removed = bool(cfg.stt_backend) and cfg.stt_backend not in BACKEND_REGISTRY
        if cfg.stt_backend in _LEGACY_REGULAR_BACKENDS or removed:
            config_mod.set_stt_selection(
                _PRIVATE_DICTATION_BACKEND,
                _PRIVATE_DICTATION_MODEL,
                path=self.config_path,
            )
            cfg = config_mod.load_config(self.config_path)
        return cfg

    def get_state(self) -> dict[str, Any]:
        cfg = self._load_ui_config()
        prefs = self.prefs_store.load()
        # No saved backend, or one this build does not ship, uses the same
        # local default the daemon runs (Parakeet on this machine).
        backend = cfg.stt_backend or resolve_default_local_backend(cfg.stt_device or "auto")[0]
        if backend not in BACKEND_REGISTRY:
            backend, model = resolve_default_local_backend(cfg.stt_device or "auto")
        else:
            model = self._effective_model(cfg, backend)
        meeting_backend, meeting_model = self._meeting_selection(cfg)
        meeting_readiness = self._meeting_readiness(cfg)
        return {
            "version": RELEASE_VERSION,
            "model": {"id": f"{backend}/{model}", "backend": backend, "model": model},
            "meetingModel": {
                "id": f"{meeting_backend}/{meeting_model}",
                "backend": meeting_backend,
                "model": meeting_model,
            },
            "meetingReadiness": meeting_readiness,
            "models": self._models(cfg),
            "shortcut": self._shortcut(cfg, prefs),
            "hotwords": list(cfg.hotwords),
            "history": self.get_history(),
            "device": {
                "name": "Default device",
                "device": cfg.stt_device or "auto",
                "compute": cfg.stt_compute_type or "int8",
            },
            "updateChannel": cfg.update_channel or "stable",
            "installedPackageVersion": cfg.installed_package_version,
            "prefs": prefs,
            "notes": self._notes_payload(),
            "startup": bool(self._safe(self.startup_enabled, False)),
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
                models.append(entry)
        # The local provider's display name keeps the "provider · model" form.
        for entry in models:
            if entry["local"]:
                entry["name"] = f"{entry['backend']} · {entry['model']}"
        return models

    def get_history(self) -> list[dict[str, Any]]:
        seen_text: set[str] = set()
        out: list[dict[str, Any]] = []
        if self.note_store is not None:
            for note in self.note_store.list_notes(limit=50):
                payload = self.note_payload(self.note_store, note.note_id)
                if payload is None:
                    continue
                text = str(payload.get("text") or "").strip()
                if not text:
                    continue
                payload["time"] = self._history_label(str(payload.get("createdAt") or ""))
                out.append(payload)
                seen_text.add(_dedupe_text(text))

        entries = self.history_store.load()
        for entry in entries:
            text_key = _dedupe_text(entry.text)
            if text_key in seen_text:
                continue
            out.append(
                {
                    "id": entry.id,
                    "text": entry.text,
                    "time": self._history_label(entry.created_at),
                    "createdAt": entry.created_at,
                }
            )
            seen_text.add(text_key)
        # Notes are walked first so a saved note wins the text-dedupe over the
        # rolling history copy. The list the UI shows is still newest speech
        # first: a quick dictation that never became a note has to sort in with
        # the notes, not get stuck underneath older ones.
        out.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        return out

    def export_local_data(self) -> dict[str, Any]:
        """Return an explicit local-only export without synced/cloud state or secrets."""
        history = [asdict(entry) for entry in self.history_store.load(include_archived=True)]
        notes: list[dict[str, Any]] = []
        if self.note_store is not None:
            for note in self.note_store.list_notes(limit=10_000, include_archived=True):
                payload = self.note_payload(self.note_store, note.note_id)
                if payload is None:
                    continue
                payload["archived"] = note.archived
                payload["rev"] = note.rev
                payload["updatedAt"] = note.updated_at
                notes.append(payload)
        return {
            "schema": "dictate.local-export.v1",
            "exportedAt": self.now().isoformat(),
            "history": history,
            "notes": notes,
        }

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
        if "updateChannel" in payload:
            self._set_update_channel(payload["updateChannel"])
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
        if "activation" in prefs and prefs["activation"] not in _VALID_ACTIVATIONS:
            raise ApiError(400, f"invalid activation: {prefs['activation']!r}")
        if "outputFormat" in prefs and prefs["outputFormat"] not in _VALID_OUTPUT_FORMATS:
            raise ApiError(400, f"invalid outputFormat: {prefs['outputFormat']!r}")
        return self.prefs_store.update(prefs)

    def _set_startup(self, enabled: Any) -> None:
        try:
            self.set_startup_enabled(bool(enabled))
        except Exception as exc:  # noqa: BLE001
            raise ApiError(500, f"could not change startup: {exc}") from exc

    def _set_update_channel(self, channel: Any) -> None:
        if not isinstance(channel, str):
            raise ApiError(400, "updateChannel must be stable or unstable")
        normalized = channel.strip().lower()
        if normalized == "latest":
            normalized = "stable"
        if normalized not in {"stable", "unstable"}:
            raise ApiError(400, "updateChannel must be stable or unstable")
        config_mod.set_update_channel(normalized, path=self.config_path)

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

    def archive_history_item(self, item_id: str) -> dict[str, Any]:
        if not isinstance(item_id, str) or not item_id.strip():
            raise ApiError(400, "id is required")
        item_id = item_id.strip()
        archived = False
        if self.note_store is not None:
            archived = self.note_store.archive_note(item_id)
        if not archived:
            archived = self.history_store.archive(item_id)
        if not archived:
            raise ApiError(404, "note not found")
        if self.broker is not None:
            self.broker.publish("history-changed")
        return {"history": self.get_history()}

    def unarchive_history_item(self, item_id: str) -> dict[str, Any]:
        if not isinstance(item_id, str) or not item_id.strip():
            raise ApiError(400, "id is required")
        item_id = item_id.strip()
        restored = False
        if self.note_store is not None:
            restored = self.note_store.unarchive_note(item_id)
        if not restored:
            restored = self.history_store.unarchive(item_id)
        if not restored:
            raise ApiError(404, "note not found")
        if self.broker is not None:
            self.broker.publish("history-changed")
        return {"history": self.get_history()}

    def start_note_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        started = bool(daemon.start_note_recording())
        return self._notes_payload()

    def start_meeting_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        self._ensure_meeting_backend_ready()
        daemon.start_meeting_recording()
        return self._notes_payload()

    def stop_note_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        daemon.stop_note_recording()
        return self._notes_payload()

    def stop_meeting_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        daemon.stop_meeting_recording()
        return self._notes_payload()

    def discard_note_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        daemon.cancel_note_recording()
        return self._notes_payload()

    def discard_meeting_recording(self) -> dict[str, Any]:
        daemon = self._require_daemon()
        daemon.cancel_meeting_recording()
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

    def _ensure_meeting_backend_ready(self) -> None:
        cfg = config_mod.load_config(self.config_path)
        backend, model = self._meeting_selection(cfg)
        readiness_payload = self._meeting_readiness(cfg)
        if not readiness_payload["ready"]:
            raise ApiError(409, f"Meeting model is not ready: {readiness_payload['reason']}")
        self._install_meeting_backend_if_needed(cfg, backend=backend, model=model)

    def _meeting_readiness(self, cfg: config_mod.Config) -> dict[str, Any]:
        backend, model = self._meeting_selection(cfg)
        readiness = check_backend_readiness(
            backend=backend,
            model=model,
            device=cfg.stt_device or "auto",
        )
        capabilities = BACKEND_REGISTRY[backend].capabilities
        if not capabilities.supports_speaker_attribution:
            reason = "Meeting needs a speaker-ready local model. Select the Meeting model and prepare it first."
        elif readiness.errors:
            reason = readiness.errors[0]
        else:
            reason = _meeting_blocking_warning(readiness.warnings)
        return {
            "ready": reason is None,
            "reason": reason,
            "errors": list(readiness.errors),
            "warnings": list(readiness.warnings),
        }

    def _meeting_selection(self, cfg: config_mod.Config) -> tuple[str, str]:
        backend = cfg.meeting_stt_backend or "parakeet-pyannote"
        if backend not in BACKEND_REGISTRY:
            backend = "parakeet-pyannote"
        model = resolve_model_name(backend, cfg.meeting_stt_model)
        return backend, model

    def _install_meeting_backend_if_needed(
        self,
        cfg: config_mod.Config,
        *,
        backend: str,
        model: str,
    ) -> None:
        daemon = self._require_daemon()
        set_meeting = getattr(daemon, "set_meeting_speech_to_text", None)
        if not callable(set_meeting):
            return
        current_meeting = getattr(daemon, "current_meeting_backend_model", None)
        if callable(current_meeting) and current_meeting() == (backend, model):
            return
        stt = create_speech_to_text(
            backend=backend,
            model=model,
            device=cfg.stt_device or "auto",
            compute_type=cfg.stt_compute_type or "int8",
        )
        set_meeting(stt, hotwords=cfg.hotwords_for_backend(backend))

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
            "installStartedAt": status.install_started_at,
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
            "installStartedAt": flow.install_started_at,
        }

    @staticmethod
    def _safe(fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return default

    def _note_recording_active(self) -> bool:
        return bool(self.daemon is not None and getattr(self.daemon, "long_recording_active", False))

    def _note_recording_paused(self) -> bool:
        return bool(self.daemon is not None and getattr(self.daemon, "note_recording_paused", False))

    def _notes_payload(self) -> dict[str, Any]:
        paused = self._note_recording_paused()
        payload: dict[str, Any] = {
            "recording": self._note_recording_active(),
            "paused": paused,
        }
        if self.daemon is not None:
            mode = getattr(self.daemon, "long_recording_mode", None)
            if mode in {"note", "meeting"}:
                payload["mode"] = mode
        if paused and self.daemon is not None:
            reason = getattr(self.daemon, "note_pause_reason", None)
            if isinstance(reason, str) and reason:
                payload["pauseReason"] = reason
        return payload

    @staticmethod
    def note_segment_payload(segment: NoteSegment) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "seq": segment.seq,
            "tStart": segment.t_start,
            "tEnd": segment.t_end,
            "text": segment.text,
            "provider": segment.provider,
            "model": segment.model,
        }
        if segment.speaker_id:
            payload["speakerId"] = segment.speaker_id
        if segment.speaker_label:
            payload["speakerLabel"] = segment.speaker_label
        return payload

    @classmethod
    def note_payload(cls, note_store: NoteStore, note_id: str) -> dict[str, Any] | None:
        note = note_store.load_note(note_id)
        if note is None:
            return None
        segments = note_store.load_segments(note_id)
        return {
            "id": note.note_id,
            "mode": note.mode,
            "status": note.status,
            "text": note_store.assembled_text(note.note_id),
            "createdAt": note.started_at,
            "endedAt": note.ended_at,
            "durationSeconds": note.duration_s,
            "provider": note.provider,
            "model": note.model,
            "speakerLabels": note.speaker_labels,
            "segments": [cls.note_segment_payload(segment) for segment in segments],
        }

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
        Transcription is local-only, so the provider is always healthy.
        """
        backend = cfg.stt_backend or "faster-whisper"
        return {
            "healthy": True,
            "status": "ok",
            "mode": "private",
            "preferred": backend,
            "active": backend,
            "degraded": False,
            "reason": None,
            "since": None,
        }


    def connect_engine_health(self, engine: Any) -> None:
        """Wire this backend's health tracker as the engine's ``health_sink``.

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
        if path == "/api/local/export" and method == "GET":
            return _Response(200, backend.export_local_data())
        if path == "/api/history" and method == "DELETE":
            return _Response(200, backend.clear_history())
        if path == "/api/history/archive" and method == "POST":
            body = self._read_json() or {}
            return _Response(200, backend.archive_history_item((body or {}).get("id", "")))
        if path == "/api/history/unarchive" and method == "POST":
            body = self._read_json() or {}
            return _Response(200, backend.unarchive_history_item((body or {}).get("id", "")))
        if path == "/api/notes/start" and method == "POST":
            return _Response(200, backend.start_note_recording())
        if path == "/api/notes/stop" and method == "POST":
            return _Response(200, backend.stop_note_recording())
        if path == "/api/meetings/start" and method == "POST":
            return _Response(200, backend.start_meeting_recording())
        if path == "/api/meetings/stop" and method == "POST":
            return _Response(200, backend.stop_meeting_recording())
        if path == "/api/notes/discard" and method == "POST":
            return _Response(200, backend.discard_note_recording())
        if path == "/api/meetings/discard" and method == "POST":
            return _Response(200, backend.discard_meeting_recording())
        if path == "/api/notes/pause" and method == "POST":
            return _Response(200, backend.pause_note_recording())
        if path == "/api/notes/resume" and method == "POST":
            return _Response(200, backend.resume_note_recording())
        if path == "/api/notes/toggle" and method == "POST":
            return _Response(200, backend.toggle_note_recording())
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
