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

import hashlib
import json
import logging
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

from cryptography.exceptions import InvalidTag

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
from dictate.pro.client import ProClient, ProClientError
from dictate.sync import (
    SyncSettingsStore,
    create_recovery_envelope,
    generate_device_key_pair,
    generate_recovery_key,
    recover_account_key,
    recovery_envelope_from_dict,
    unwrap_account_key_for_device,
    wrap_account_key_for_device,
)
from dictate.sync_engine import SyncEngine
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
_SYNCED_PREF_KEYS = frozenset({"theme", "sound", "ambient"})

# Provider display metadata. Backend ids / models are grounded in stt.factory;
# only the human-facing bits (brand glyph, key shape, blurb) live here.
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
PROVIDER_ORDER = (
    "parakeet",
    "parakeet-pyannote",
    "parakeet-diarizen",
    "parakeet-sortformer",
    "faster-whisper",
    "whisperx",
    "openai",
    "xai",
    "gemini",
)


class ApiError(Exception):
    """Raised inside the backend to map to a specific HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _optional_positive_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "audioDurationSeconds must be a positive number") from exc
    if parsed <= 0:
        raise ApiError(400, "audioDurationSeconds must be a positive number")
    return parsed


def _first_recovery_envelope(envelopes: Any) -> dict[str, Any] | None:
    if not isinstance(envelopes, list):
        return None
    for item in envelopes:
        if not isinstance(item, dict):
            continue
        envelope = item.get("envelope")
        if isinstance(envelope, dict):
            return envelope
    return None


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
    note_store: NoteStore | None = None
    prefs_store: UiPrefsStore | None = None
    sync_settings: SyncSettingsStore | None = None
    broker: EventBroker | None = None
    pro_client: ProClient | None = None
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
        if self.note_store is None:
            self.note_store = NoteStore()
        if self.prefs_store is None:
            self.prefs_store = UiPrefsStore()
        if self.sync_settings is None:
            self.sync_settings = SyncSettingsStore()
        if self.pro_client is None:
            self.pro_client = ProClient()
        self._sync_engine().attach_outbox()

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
        # No saved backend → the hardware-aware default (Parakeet English on CPU).
        backend = cfg.stt_backend or resolve_default_local_backend(cfg.stt_device or "auto")[0]
        if backend not in BACKEND_REGISTRY:
            backend = "faster-whisper"
        model = self._effective_model(cfg, backend)
        meeting_backend, meeting_model = self._meeting_selection(cfg)
        return {
            "version": RELEASE_VERSION,
            "model": {"id": f"{backend}/{model}", "backend": backend, "model": model},
            "meetingModel": {
                "id": f"{meeting_backend}/{meeting_model}",
                "backend": meeting_backend,
                "model": meeting_model,
            },
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
            "providers": self._providers(cfg),
            "prefs": prefs,
            "notes": self._notes_payload(),
            "startup": bool(self._safe(self.startup_enabled, False)),
            "secretStore": self._safe(self.secret_store_description, "OS secret store"),
            "secretStoreAvailable": bool(self._safe(self.secret_store_available, False)),
            "micConnected": True,
            "providerHealth": self._compute_provider_health(cfg),
            "dictatePro": self._dictate_pro_state(),
            "sync": self._sync_state(),
        }

    def _dictate_pro_state(self) -> dict[str, Any]:
        client = self.pro_client
        if client is None:
            return {"signedIn": False, "entitlements": None, "usage": None, "account": None, "commerce": None}
        return self._safe(client.get_state, {
            "signedIn": False,
            "entitlements": None,
            "usage": None,
            "account": None,
            "commerce": None,
        })

    def start_pro_sign_in(self, email: str) -> dict[str, Any]:
        client = self._require_pro_client()
        return client.start_sign_in(email)

    def complete_pro_sign_in(self, *, challenge_id: str, code: str, device_label: str = "Desktop") -> dict[str, Any]:
        client = self._require_pro_client()
        device_key_pair = generate_device_key_pair()
        session = client.complete_sign_in(
            challenge_id=challenge_id,
            code=code,
            device_label=device_label,
            device_public_key=device_key_pair.public_key,
        )
        try:
            api_keys_mod.save_sync_device_private_key(session.device_id, device_key_pair.private_key)
        except (api_keys_mod.ApiKeyStorageError, OSError) as exc:
            logger.warning("could not persist Dictate sync device private key: %s", exc)
        return {
            "account_id": session.account_id,
            "device_id": session.device_id,
            "signedIn": True,
            "dictatePro": client.get_state(),
        }

    def sign_out_pro(self) -> dict[str, Any]:
        client = self._require_pro_client()
        client.clear_session()
        if self.sync_settings is not None:
            self.sync_settings.disable(clear_key=False)
        self._sync_engine().attach_outbox()
        return {"signedIn": False}

    def _sync_state(self, *, last_result: dict[str, Any] | None = None) -> dict[str, Any]:
        settings = self._require_sync_settings()
        state = settings.load()
        has_key = False
        if state.enabled:
            has_key = bool(self._safe(lambda: settings.account_key() is not None, False))
        return {
            "enabled": state.enabled,
            "accountId": state.account_id or None,
            "deviceId": state.device_id or None,
            "enabledAt": state.enabled_at,
            "lastSeq": state.last_seq,
            "keyAvailable": has_key,
            "lastResult": last_result,
        }

    def enable_sync(self, *, recovery_key: str | None = None) -> dict[str, Any]:
        client = self._require_pro_client()
        session = client.refresh_if_needed()
        if session is None:
            raise ApiError(401, "Sign in to Dictate Pro before enabling sync.")
        settings = self._require_sync_settings()
        recovery = recovery_key.strip() if isinstance(recovery_key, str) and recovery_key.strip() else None
        returned_recovery_key = None
        if recovery:
            envelopes = client.list_key_envelopes(envelope_kind="recovery").get("envelopes", [])
            envelope_payload = _first_recovery_envelope(envelopes)
            if envelope_payload is None:
                raise ApiError(409, "No recovery key is set up for this Dictate Pro account.")
            try:
                account_key = recover_account_key(
                    account_id=session.account_id,
                    recovery_key=recovery,
                    envelope=recovery_envelope_from_dict(envelope_payload),
                )
            except (InvalidTag, ValueError) as exc:
                raise ApiError(400, "Recovery key could not unlock Dictate Pro sync for this account.") from exc
            try:
                client.approve_current_device_with_recovery()
            except Exception as exc:  # noqa: BLE001
                raise ApiError(403, "Recovery key unlocked sync, but this device could not be trusted.") from exc
            state, account_key = settings.enable(session.account_id, account_key=account_key, device_id=session.device_id)
            self._save_current_device_key_envelope(client, session.account_id, session.device_id, account_key)
        else:
            try:
                device_envelopes = client.list_key_envelopes(envelope_kind="device").get("envelopes", [])
            except ProClientError as exc:
                if exc.status not in {404, 405, 501}:
                    raise
                device_envelopes = []
            device_envelope = next(
                (
                    item for item in device_envelopes
                    if isinstance(item, dict) and str(item.get("device_id") or item.get("deviceId") or "") == session.device_id
                ),
                None,
            )
            if isinstance(device_envelope, dict):
                private_key = api_keys_mod.read_sync_device_private_key(session.device_id)
                if not private_key:
                    raise ApiError(409, "This device was approved, but its local sync device key is missing.")
                try:
                    account_key = unwrap_account_key_for_device(
                        account_id=session.account_id,
                        private_key=private_key,
                        envelope=device_envelope.get("envelope"),
                    )
                except Exception as exc:  # noqa: BLE001
                    raise ApiError(400, "This device could not unlock its approved sync key.") from exc
                state, account_key = settings.enable(
                    session.account_id,
                    account_key=account_key,
                    device_id=session.device_id,
                )
            else:
                state, account_key = settings.enable(session.account_id, device_id=session.device_id)
                returned_recovery_key = generate_recovery_key()
                recovery_envelope = create_recovery_envelope(
                    account_id=session.account_id,
                    account_key=account_key,
                    recovery_key=returned_recovery_key,
                )
                self._save_current_device_key_envelope(client, session.account_id, session.device_id, account_key)
                client.save_key_envelope(envelope_kind="recovery", envelope=asdict(recovery_envelope))
        engine = self._sync_engine()
        engine.attach_outbox()
        self._enqueue_sync_snapshot()
        result = engine.run_once().as_dict()
        if self.broker is not None:
            self.broker.publish("sync-changed", sync=self._sync_state(last_result=result))
        payload = {"sync": self._sync_state(last_result=result), "deviceId": state.device_id}
        if returned_recovery_key:
            payload["recoveryKey"] = returned_recovery_key
        return payload

    def disable_sync(self, *, clear_key: bool = False) -> dict[str, Any]:
        settings = self._require_sync_settings()
        settings.disable(clear_key=clear_key)
        self._sync_engine().attach_outbox()
        if self.broker is not None:
            self.broker.publish("sync-changed", sync=self._sync_state())
        return {"sync": self._sync_state()}

    def run_sync(self) -> dict[str, Any]:
        result = self._sync_engine().run_once().as_dict()
        if self.broker is not None:
            self.broker.publish("history-changed")
            self.broker.publish("sync-changed", sync=self._sync_state(last_result=result))
        return {"sync": self._sync_state(last_result=result), "result": result, "history": self.get_history()}

    def list_pro_devices(self) -> dict[str, Any]:
        client = self._require_pro_client()
        return client.list_devices()

    def revoke_pro_device(self, device_id: str) -> dict[str, Any]:
        client = self._require_pro_client()
        return client.revoke_device(device_id)

    def approve_pro_device(self, device_id: str) -> dict[str, Any]:
        client = self._require_pro_client()
        session = client.refresh_if_needed()
        if session is None:
            raise ApiError(401, "Sign in to Dictate Pro before approving a device.")
        account_key = self._require_sync_settings().account_key()
        if account_key is None:
            raise ApiError(409, "Enable encrypted sync on this device before approving another device.")
        target = device_id.strip()
        if not target:
            raise ApiError(400, "device_id is required")
        devices = client.list_devices().get("devices", [])
        device = next(
            (
                item for item in devices
                if isinstance(item, dict) and str(item.get("device_id") or item.get("deviceId") or "") == target
            ),
            None,
        )
        if not isinstance(device, dict):
            raise ApiError(404, "Device not found.")
        public_key = str(device.get("public_key") or device.get("publicKey") or "").strip()
        if not public_key:
            raise ApiError(409, "This device cannot be approved because it did not register a sync public key.")
        envelope = wrap_account_key_for_device(
            account_id=session.account_id,
            account_key=account_key,
            recipient_public_key=public_key,
        )
        return client.approve_device(target, envelope=envelope)

    def _save_current_device_key_envelope(
        self,
        client: ProClient,
        account_id: str,
        device_id: str,
        account_key: bytes,
    ) -> None:
        public_key = self._current_device_public_key(client, device_id)
        if not public_key:
            raise ApiError(409, "This device cannot enable encrypted sync because it did not register a sync public key.")
        envelope = wrap_account_key_for_device(
            account_id=account_id,
            account_key=account_key,
            recipient_public_key=public_key,
        )
        client.save_key_envelope(envelope_kind="device", envelope=envelope)

    def _current_device_public_key(self, client: ProClient, device_id: str) -> str:
        target = device_id.strip()
        if not target:
            return ""
        devices = client.list_devices().get("devices", [])
        for item in devices:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("device_id") or item.get("deviceId") or "").strip()
            if item_id != target:
                continue
            return str(item.get("public_key") or item.get("publicKey") or "").strip()
        return ""

    def export_pro_cloud_data(self) -> dict[str, Any]:
        client = self._require_pro_client()
        return client.export_cloud_data()

    def delete_pro_cloud_data(self) -> dict[str, Any]:
        client = self._require_pro_client()
        result = client.delete_cloud_data()
        if self.sync_settings is not None:
            self.sync_settings.disable(clear_key=False)
        self._sync_engine().attach_outbox()
        if self.broker is not None:
            self.broker.publish("sync-changed", sync=self._sync_state())
        return {"cloud": result, "sync": self._sync_state()}

    def create_pro_meeting(
        self,
        *,
        language: str | None = None,
        audio_duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        client = self._require_pro_client()
        return client.create_meeting(
            language=language,
            audio_duration_seconds=audio_duration_seconds,
        )

    def upload_pro_meeting_audio(self, job_id: str, audio_path: Path) -> dict[str, Any]:
        client = self._require_pro_client()
        return client.upload_meeting_audio(job_id, audio_path)

    def get_pro_meeting(self, job_id: str) -> dict[str, Any]:
        client = self._require_pro_client()
        return client.get_meeting(job_id)

    def get_pro_meeting_transcript(self, job_id: str) -> dict[str, Any]:
        client = self._require_pro_client()
        return client.get_transcript(job_id)

    def _require_pro_client(self) -> ProClient:
        if self.pro_client is None:
            raise ApiError(503, "Dictate Pro client is not configured")
        return self.pro_client

    def _require_sync_settings(self) -> SyncSettingsStore:
        if self.sync_settings is None:
            raise ApiError(503, "Dictate sync is not configured")
        return self.sync_settings

    def _sync_engine(self) -> SyncEngine:
        return SyncEngine(
            settings=self._require_sync_settings(),
            pro_client=self._require_pro_client(),
            history_store=self.history_store,
            note_store=self.note_store,
            config_path=self.config_path,
            prefs_store=self.prefs_store,
        )

    def _sync_outbox(self):
        if self.sync_settings is None:
            return None
        return self._safe(self.sync_settings.outbox, None)

    def _enqueue_sync_snapshot(self) -> None:
        outbox = self._sync_outbox()
        if outbox is None:
            return
        prefs = self.prefs_store.load()
        for key in sorted(_SYNCED_PREF_KEYS):
            if key in prefs:
                self._enqueue_synced_pref(key, prefs[key])
        cfg = config_mod.load_config(self.config_path)
        for term in cfg.hotwords:
            self._enqueue_synced_hotword(term, deleted=False)
        for wrong, right in cfg.lexicon_replacements.items():
            self._enqueue_synced_replacement(wrong, right, deleted=False)

    def _enqueue_synced_pref(self, key: str, value: Any) -> None:
        if key not in _SYNCED_PREF_KEYS:
            return
        outbox = self._sync_outbox()
        if outbox is None:
            return
        outbox.enqueue(
            collection="settings",
            record_id=f"prefs.{key}",
            content_type="application/vnd.dictate.setting+json;v=1",
            payload={"key": key, "value": value, "updated_at": self.now().isoformat()},
        )

    def _enqueue_synced_hotword(self, term: str, *, deleted: bool) -> None:
        normalized = " ".join(term.split()).casefold()
        if not normalized:
            return
        outbox = self._sync_outbox()
        if outbox is None:
            return
        outbox.enqueue(
            collection="lexicon",
            record_id=f"hotword:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}",
            content_type="application/vnd.dictate.lexicon+json;v=1",
            payload={"kind": "hotword", "term": term, "updated_at": self.now().isoformat()},
            deleted=deleted,
        )

    def _enqueue_synced_replacement(self, wrong: str, right: str | None, *, deleted: bool) -> None:
        normalized = " ".join(wrong.split()).casefold()
        if not normalized:
            return
        outbox = self._sync_outbox()
        if outbox is None:
            return
        outbox.enqueue(
            collection="lexicon",
            record_id=f"replacement:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}",
            content_type="application/vnd.dictate.lexicon+json;v=1",
            payload={
                "kind": "replacement",
                "wrong": wrong,
                "right": right or "",
                "updated_at": self.now().isoformat(),
            },
            deleted=deleted,
        )

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
        updated = self.prefs_store.update(prefs)
        for key in _SYNCED_PREF_KEYS:
            if key in prefs:
                self._enqueue_synced_pref(key, updated[key])
        return updated

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
        for term in added:
            self._enqueue_synced_hotword(term, deleted=False)
        return {"added": added, "hotwords": list(config_mod.load_config(self.config_path).hotwords)}

    def remove_hotword(self, word: str) -> dict[str, Any]:
        if not isinstance(word, str) or not word.strip():
            raise ApiError(400, "word is required")
        removed = config_mod.remove_hotwords([word], path=self.config_path)
        for term in removed:
            self._enqueue_synced_hotword(term, deleted=True)
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
        readiness = check_backend_readiness(
            backend=backend,
            model=model,
            device=cfg.stt_device or "auto",
        )
        capabilities = BACKEND_REGISTRY[backend].capabilities
        if not capabilities.supports_speaker_attribution:
            raise ApiError(
                409,
                "Meeting needs a speaker-ready local model. Select the Meeting model and prepare it first.",
            )
        if readiness.errors:
            raise ApiError(409, f"Meeting model is not ready: {readiness.errors[0]}")
        blocking_warning = _meeting_blocking_warning(readiness.warnings)
        if blocking_warning is not None:
            raise ApiError(409, f"Meeting model is not ready: {blocking_warning}")
        self._install_meeting_backend_if_needed(cfg, backend=backend, model=model)

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
        * Local/private backends → always healthy; no key needed.
        * Supervisor present → read full state from supervisor.
        * Online + no key → unhealthy, status ``no-key``.
        * Online + key present → reflect the tracked runtime outcome.
        """
        backend = cfg.stt_backend or "faster-whisper"
        is_private = bool(PROVIDER_META.get(backend, {}).get("local", False))
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
            # Still surface no-key as unhealthy for hosted backends even when
            # supervisor is healthy. Local Parakeet/Whisper lanes need no key.
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

    def _read_uploaded_audio_file(self) -> Path:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            raise ApiError(400, "audio body is required")
        raw = self.rfile.read(length)
        if not raw:
            raise ApiError(400, "audio body is required")
        suffix = ".wav"
        content_type = str(self.headers.get("Content-Type") or "")
        if "mpeg" in content_type:
            suffix = ".mp3"
        elif "ogg" in content_type:
            suffix = ".ogg"
        temp_dir = Path(tempfile.mkdtemp(prefix="dictate-pro-upload-"))
        path = temp_dir / f"audio{suffix}"
        path.write_bytes(raw)
        return path

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
        except ProClientError as exc:
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
        if path == "/api/pro/auth/start" and method == "POST":
            body = self._read_json() or {}
            return _Response(200, backend.start_pro_sign_in(str(body.get("email", "")).strip()))
        if path == "/api/pro/auth/complete" and method == "POST":
            body = self._read_json() or {}
            return _Response(
                200,
                backend.complete_pro_sign_in(
                    challenge_id=str(body.get("challenge_id", "")).strip(),
                    code=str(body.get("code", "")).strip(),
                    device_label=str(body.get("deviceLabel") or body.get("device_label") or "Desktop"),
                ),
            )
        if path == "/api/pro/sign-out" and method == "POST":
            return _Response(200, backend.sign_out_pro())
        if path == "/api/pro/sync/enable" and method == "POST":
            body = self._read_json() or {}
            return _Response(200, backend.enable_sync(recovery_key=str(body.get("recoveryKey") or "")))
        if path == "/api/pro/sync/disable" and method == "POST":
            body = self._read_json() or {}
            return _Response(200, backend.disable_sync(clear_key=bool(body.get("clearKey", False))))
        if path == "/api/pro/sync/run" and method == "POST":
            return _Response(200, backend.run_sync())
        if path == "/api/pro/devices" and method == "GET":
            return _Response(200, backend.list_pro_devices())
        if path == "/api/pro/devices/revoke" and method == "POST":
            body = self._read_json() or {}
            return _Response(200, backend.revoke_pro_device(str(body.get("deviceId") or body.get("device_id") or "")))
        if path == "/api/pro/devices/approve" and method == "POST":
            body = self._read_json() or {}
            return _Response(200, backend.approve_pro_device(str(body.get("deviceId") or body.get("device_id") or "")))
        if path == "/api/pro/cloud/export" and method == "GET":
            return _Response(200, backend.export_pro_cloud_data())
        if path == "/api/pro/cloud/delete" and method == "DELETE":
            return _Response(200, backend.delete_pro_cloud_data())
        if path == "/api/pro/meetings" and method == "POST":
            body = self._read_json() or {}
            language = str(body.get("language") or "").strip() or None
            audio_duration_seconds = _optional_positive_float(
                body.get("audioDurationSeconds", body.get("audio_duration_seconds"))
            )
            return _Response(
                200,
                backend.create_pro_meeting(
                    language=language,
                    audio_duration_seconds=audio_duration_seconds,
                ),
            )
        if path.startswith("/api/pro/meetings/") and method == "GET":
            job_id = path.removeprefix("/api/pro/meetings/").split("/", 1)[0]
            if path.endswith("/transcript"):
                return _Response(200, backend.get_pro_meeting_transcript(job_id))
            return _Response(200, backend.get_pro_meeting(job_id))
        if path.startswith("/api/pro/meetings/") and path.endswith("/audio") and method == "POST":
            job_id = path.removeprefix("/api/pro/meetings/").removesuffix("/audio")
            audio_path = self._read_uploaded_audio_file()
            try:
                return _Response(200, backend.upload_pro_meeting_audio(job_id, audio_path))
            finally:
                try:
                    audio_path.unlink(missing_ok=True)
                    audio_path.parent.rmdir()
                except OSError:
                    pass
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
