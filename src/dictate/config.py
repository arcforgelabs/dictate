"""Load dictate config from the platform-specific user config path."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dictate.hotkey import normalize_push_to_talk_combo
from dictate.platform_paths import user_config_dir

logger = logging.getLogger(__name__)

CONFIG_PATH = user_config_dir() / "config.yaml"


@dataclass(slots=True)
class Config:
    hotwords: list[str] = field(default_factory=list)
    lexicon_mode: str | None = None
    lexicon_replacements: dict[str, str] = field(default_factory=dict)
    push_to_talk_combo: str | None = None
    push_to_talk_key: str | None = None
    stt_backend: str | None = None
    stt_model: str | None = None
    stt_device: str | None = None
    stt_compute_type: str | None = None
    openai_api_key_command: str | None = None
    xai_api_key_command: str | None = None

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
        data = yaml.safe_load(path.read_text()) or {}
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
    stt_device = data.get("stt_device")
    stt_compute_type = data.get("stt_compute_type")
    openai_api_key_command = data.get("openai_api_key_command")
    xai_api_key_command = data.get("xai_api_key_command")
    if not isinstance(stt_backend, str):
        stt_backend = None
    if not isinstance(stt_model, str):
        stt_model = None
    if not isinstance(stt_device, str):
        stt_device = None
    if not isinstance(stt_compute_type, str):
        stt_compute_type = None
    if not isinstance(openai_api_key_command, str):
        openai_api_key_command = None
    if not isinstance(xai_api_key_command, str):
        xai_api_key_command = None

    return Config(
        hotwords=hotwords,
        lexicon_mode=lexicon_mode,
        lexicon_replacements=lexicon_replacements,
        push_to_talk_combo=push_to_talk_combo,
        push_to_talk_key=push_to_talk_key,
        stt_backend=stt_backend,
        stt_model=stt_model,
        stt_device=stt_device,
        stt_compute_type=stt_compute_type,
        openai_api_key_command=openai_api_key_command,
        xai_api_key_command=xai_api_key_command,
    )


def _load_raw(path: Path = CONFIG_PATH) -> dict:
    """Load raw YAML dict, preserving all keys."""
    if not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _save_raw(data: dict, path: Path = CONFIG_PATH) -> None:
    """Write dict back to YAML, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False))


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


def set_stt_runtime_profile(device: str, compute_type: str, path: Path = CONFIG_PATH) -> None:
    """Persist selected STT runtime profile for tray startup defaults."""
    data = _load_raw(path)
    data["stt_device"] = device
    data["stt_compute_type"] = compute_type
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
