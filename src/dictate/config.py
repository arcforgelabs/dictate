"""Load dictate config from the platform-specific user config path."""

from __future__ import annotations

import locale
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dictate.hotkey import normalize_push_to_talk_combo
from dictate.platform_paths import user_config_dir

logger = logging.getLogger(__name__)

CONFIG_PATH = user_config_dir() / "config.yaml"


def _read_config_yaml(path: Path) -> dict:
    """Read and parse config.yaml, tolerating a pre-existing non-UTF-8 file.

    New writes always use UTF-8 (see _save_raw), but a config file that
    predates that fix -- or one hand-edited with a non-UTF-8 editor on
    Windows -- may still be in the platform's legacy ANSI encoding (cp1252).
    Retry once with the locale's preferred encoding before giving up, so a
    non-ASCII hotword/lexicon term in such a file doesn't silently reset the
    whole config to defaults.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding=locale.getpreferredencoding(False))
    return yaml.safe_load(text) or {}


@dataclass(slots=True)
class Config:
    hotwords: list[str] = field(default_factory=list)
    lexicon_mode: str | None = None
    lexicon_replacements: dict[str, str] = field(default_factory=dict)
    push_to_talk_combo: str | None = None
    push_to_talk_key: str | None = None
    stt_backend: str | None = None
    stt_model: str | None = None
    meeting_stt_backend: str | None = None
    meeting_stt_model: str | None = None
    stt_device: str | None = None
    stt_compute_type: str | None = None
    openai_api_key_command: str | None = None
    xai_api_key_command: str | None = None
    gemini_api_key_command: str | None = None
    cloud_provider_preference: str | None = None
    update_channel: str | None = None
    installed_package_version: str | None = None
    # Which record categories sync: "meetings" (note+segment only, the default) or
    # "everything" (also the rolling quick-copy history). See docs/record-categories-spec.md.
    sync_scope: str | None = None

    @property
    def hotwords_str(self) -> str | None:
        """Hotwords as a single space-separated string for faster-whisper."""
        return " ".join(self.hotwords) if self.hotwords else None

    def hotwords_for_backend(self, backend: str) -> str | None:
        """Hotwords formatted for the selected backend."""
        if not self.hotwords:
            return None
        if backend == "xai":
            return "\n".join(self.hotwords)
        return self.hotwords_str


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from YAML file. Returns defaults if file doesn't exist."""
    if not path.is_file():
        return Config()

    try:
        data = _read_config_yaml(path)
    except Exception:
        logger.warning(f"Failed to parse {path}, using defaults")
        return Config()

    hotwords = data.get("hotwords", [])
    if isinstance(hotwords, str):
        hotwords = [hotwords]
    if not isinstance(hotwords, list):
        hotwords = []

    lexicon_mode = data.get("lexicon_mode")
    if not isinstance(lexicon_mode, str):
        lexicon_mode = None

    push_to_talk_combo = data.get("push_to_talk_combo")
    if not isinstance(push_to_talk_combo, str):
        push_to_talk_combo = None

    push_to_talk_key = data.get("push_to_talk_key")
    if not isinstance(push_to_talk_key, str):
        push_to_talk_key = None

    lexicon_replacements_raw = data.get("lexicon_replacements", {})
    lexicon_replacements: dict[str, str] = {}
    if isinstance(lexicon_replacements_raw, dict):
        for wrong, right in lexicon_replacements_raw.items():
            if isinstance(wrong, str) and isinstance(right, str):
                wrong_clean = wrong.strip()
                right_clean = right.strip()
                if wrong_clean and right_clean:
                    lexicon_replacements[wrong_clean] = right_clean

    stt_backend = data.get("stt_backend")
    stt_model = data.get("stt_model")
    meeting_stt_backend = data.get("meeting_stt_backend")
    meeting_stt_model = data.get("meeting_stt_model")
    stt_device = data.get("stt_device")
    stt_compute_type = data.get("stt_compute_type")
    openai_api_key_command = data.get("openai_api_key_command")
    xai_api_key_command = data.get("xai_api_key_command")
    gemini_api_key_command = data.get("gemini_api_key_command")
    cloud_provider_preference = data.get("cloud_provider_preference")
    update_channel = data.get("update_channel")
    installed_package_version = data.get("installed_package_version")
    sync_scope = data.get("sync_scope")
    if not isinstance(sync_scope, str) or sync_scope not in {"meetings", "everything"}:
        sync_scope = None
    if not isinstance(stt_backend, str):
        stt_backend = None
    if not isinstance(stt_model, str):
        stt_model = None
    if not isinstance(meeting_stt_backend, str):
        meeting_stt_backend = None
    if not isinstance(meeting_stt_model, str):
        meeting_stt_model = None
    if not isinstance(stt_device, str):
        stt_device = None
    if not isinstance(stt_compute_type, str):
        stt_compute_type = None
    if not isinstance(openai_api_key_command, str):
        openai_api_key_command = None
    if not isinstance(xai_api_key_command, str):
        xai_api_key_command = None
    if not isinstance(gemini_api_key_command, str):
        gemini_api_key_command = None
    if cloud_provider_preference not in {"pro-first", "personal-first"}:
        cloud_provider_preference = None
    if not isinstance(update_channel, str):
        update_channel = None
    if not isinstance(installed_package_version, str):
        installed_package_version = None

    return Config(
        hotwords=hotwords,
        lexicon_mode=lexicon_mode,
        lexicon_replacements=lexicon_replacements,
        push_to_talk_combo=push_to_talk_combo,
        push_to_talk_key=push_to_talk_key,
        stt_backend=stt_backend,
        stt_model=stt_model,
        meeting_stt_backend=meeting_stt_backend,
        meeting_stt_model=meeting_stt_model,
        stt_device=stt_device,
        stt_compute_type=stt_compute_type,
        openai_api_key_command=openai_api_key_command,
        xai_api_key_command=xai_api_key_command,
        gemini_api_key_command=gemini_api_key_command,
        cloud_provider_preference=cloud_provider_preference,
        update_channel=update_channel,
        installed_package_version=installed_package_version,
        sync_scope=sync_scope,
    )


def _load_raw(path: Path = CONFIG_PATH) -> dict:
    """Load raw YAML dict, preserving all keys."""
    if not path.is_file():
        return {}
    try:
        return _read_config_yaml(path)
    except Exception:
        return {}


def _save_raw(data: dict, path: Path = CONFIG_PATH) -> None:
    """Write dict back to YAML, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def add_hotwords(words: list[str], path: Path = CONFIG_PATH) -> list[str]:
    """Add words to the hotwords list. Returns list of newly added words."""
    data = _load_raw(path)
    existing = data.get("hotwords", [])
    if isinstance(existing, str):
        existing = [existing]

    added = [w for w in words if w not in existing]
    if added:
        data["hotwords"] = existing + added
        _save_raw(data, path)
    return added


def parse_hotwords_text(value: str) -> list[str]:
    """Parse pasted hotwords from comma, semicolon, newline, or bullet-separated text."""
    parsed: list[str] = []
    for raw in re.split(r"[,;\n\r]+", value):
        word = raw.strip()
        word = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", word).strip()
        word = " ".join(word.split())
        if word:
            parsed.append(word)
    return parsed


def remove_hotwords(words: list[str], path: Path = CONFIG_PATH) -> list[str]:
    """Remove words from the hotwords list. Returns list of actually removed words."""
    data = _load_raw(path)
    existing = data.get("hotwords", [])
    if isinstance(existing, str):
        existing = [existing]

    removed = [w for w in words if w in existing]
    if removed:
        data["hotwords"] = [w for w in existing if w not in words]
        _save_raw(data, path)
    return removed


def set_stt_selection(backend: str, model: str, path: Path = CONFIG_PATH) -> None:
    """Persist selected STT backend/model for tray startup defaults."""
    data = _load_raw(path)
    data["stt_backend"] = backend
    data["stt_model"] = model
    _save_raw(data, path)


def set_meeting_stt_selection(backend: str, model: str, path: Path = CONFIG_PATH) -> None:
    """Persist selected Meeting STT backend/model without changing dictation."""
    data = _load_raw(path)
    data["meeting_stt_backend"] = backend
    data["meeting_stt_model"] = model
    _save_raw(data, path)


def set_stt_backend(backend: str, path: Path = CONFIG_PATH) -> None:
    """Persist STT backend without changing the saved model."""
    data = _load_raw(path)
    data["stt_backend"] = backend
    _save_raw(data, path)


def set_stt_model(model: str, path: Path = CONFIG_PATH) -> None:
    """Persist the STT model without changing the saved backend."""
    data = _load_raw(path)
    data["stt_model"] = model
    _save_raw(data, path)


def set_stt_runtime_profile(device: str, compute_type: str, path: Path = CONFIG_PATH) -> None:
    """Persist selected STT runtime profile for tray startup defaults."""
    data = _load_raw(path)
    data["stt_device"] = device
    data["stt_compute_type"] = compute_type
    _save_raw(data, path)


def set_update_channel(channel: str, path: Path = CONFIG_PATH) -> str:
    """Persist the app update channel. Returns the normalized channel."""
    normalized = channel.strip().lower()
    if normalized == "latest":
        normalized = "stable"
    if normalized not in {"stable", "unstable"}:
        raise ValueError("update channel must be stable or unstable")
    data = _load_raw(path)
    data["update_channel"] = normalized
    _save_raw(data, path)
    return normalized


def set_cloud_provider_preference(preference: str, path: Path = CONFIG_PATH) -> str:
    """Persist the priority between Pro and personal hosted credentials."""
    normalized = preference.strip().lower()
    if normalized not in {"pro-first", "personal-first"}:
        raise ValueError("cloud provider preference must be pro-first or personal-first")
    data = _load_raw(path)
    data["cloud_provider_preference"] = normalized
    _save_raw(data, path)
    return normalized


def set_installed_package_version(version: str, path: Path = CONFIG_PATH) -> str:
    """Persist the exact package version used by the installer/updater."""
    normalized = version.strip()
    if not normalized or len(normalized) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+._-]*", normalized):
        raise ValueError("installed package version is invalid")
    data = _load_raw(path)
    data["installed_package_version"] = normalized
    _save_raw(data, path)
    return normalized


def set_sync_scope(scope: str, path: Path = CONFIG_PATH) -> str:
    """Persist which record categories sync. Returns the normalized scope.

    "meetings" (default) syncs note+segment (durable recordings/notes); "everything"
    also syncs the rolling quick-copy history. See docs/record-categories-spec.md.
    """
    normalized = scope.strip().lower()
    if normalized not in {"meetings", "everything"}:
        raise ValueError("sync scope must be meetings or everything")
    data = _load_raw(path)
    data["sync_scope"] = normalized
    _save_raw(data, path)
    return normalized


def set_api_key_command(backend: str, command: str | None, path: Path = CONFIG_PATH) -> None:
    """Persist or clear the API key command for a hosted backend."""
    key_by_backend = {
        "openai": "openai_api_key_command",
        "xai": "xai_api_key_command",
        "gemini": "gemini_api_key_command",
    }
    key = key_by_backend.get(backend)
    if key is None:
        return
    data = _load_raw(path)
    cleaned = command.strip() if isinstance(command, str) else ""
    if cleaned:
        data[key] = cleaned
    else:
        data.pop(key, None)
    _save_raw(data, path)


def set_push_to_talk_combo(combo: str, path: Path = CONFIG_PATH) -> None:
    """Persist push-to-talk combo and clear legacy single-key field."""
    data = _load_raw(path)
    data["push_to_talk_combo"] = normalize_push_to_talk_combo(combo)
    data.pop("push_to_talk_key", None)
    _save_raw(data, path)


def add_lexicon_replacements(
    replacements: dict[str, str],
    path: Path = CONFIG_PATH,
) -> dict[str, str]:
    """Add or update lexical post-correction replacements."""
    data = _load_raw(path)
    existing = data.get("lexicon_replacements", {})
    if not isinstance(existing, dict):
        existing = {}

    updated: dict[str, str] = {}
    for wrong, right in replacements.items():
        wrong_clean = wrong.strip()
        right_clean = right.strip()
        if not wrong_clean or not right_clean:
            continue
        existing[wrong_clean] = right_clean
        updated[wrong_clean] = right_clean

    if updated:
        data["lexicon_replacements"] = existing
        _save_raw(data, path)
    return updated


def remove_lexicon_replacements(words: list[str], path: Path = CONFIG_PATH) -> list[str]:
    """Remove lexical post-correction replacements by their source word."""
    data = _load_raw(path)
    existing = data.get("lexicon_replacements", {})
    if not isinstance(existing, dict):
        return []

    removed: list[str] = []
    for word in words:
        if word in existing:
            removed.append(word)
            existing.pop(word, None)
    if removed:
        data["lexicon_replacements"] = existing
        _save_raw(data, path)
    return removed
