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
    stt_compute_type: str | None = None
    update_channel: str | None = None
    installed_package_version: str | None = None

    @property
    def hotwords_str(self) -> str | None:
        """Hotwords as a single space-separated string for the lexicon layer."""
        return " ".join(self.hotwords) if self.hotwords else None

    def hotwords_for_backend(self, backend: str) -> str | None:
        """Hotwords formatted for the selected backend."""
        if not self.hotwords:
            return None
        return self.hotwords_str


# Compute types that only meant something on a GPU, and the CPU type that
# replaces them. Parakeet already loaded int8 when float16 was saved.
_GPU_ONLY_COMPUTE_TYPES = {"float16": "int8"}


def migrate_cpu_only_settings(data: dict) -> tuple[bool, list[str]]:
    """Move settings saved while GPU lanes existed to their CPU equivalent.

    Dictate runs on CPU only (#111). ``stt_device`` is removed, whatever it
    said: CPU is the only device, so there is nothing left to choose. A
    GPU-only ``stt_compute_type`` (float16) becomes int8. Everything else in
    ``data`` is left as it is. Changes ``data`` in place and returns whether
    it changed, plus a notice for each choice that moved (a saved ``cpu`` or
    ``auto`` device moves silently).
    """
    changed = False
    notices: list[str] = []
    if "stt_device" in data:
        device = data.pop("stt_device")
        changed = True
        if isinstance(device, str) and device.strip().lower() not in {"", "cpu", "auto"}:
            notices.append(f"Moved saved STT device '{device}' to CPU: Dictate runs on CPU only.")
    compute_type = data.get("stt_compute_type")
    if isinstance(compute_type, str) and compute_type in _GPU_ONLY_COMPUTE_TYPES:
        replacement = _GPU_ONLY_COMPUTE_TYPES[compute_type]
        data["stt_compute_type"] = replacement
        changed = True
        notices.append(
            f"Moved saved STT compute type '{compute_type}' to {replacement}: "
            "Dictate runs on CPU only."
        )
    return changed, notices


# Speaker-labelling backends removed with Meeting capture (#140).
MEETING_BACKENDS = frozenset({"parakeet-pyannote", "parakeet-diarizen", "parakeet-sortformer"})
_MEETING_SETTING_KEYS = ("meeting_stt_backend", "meeting_stt_model")


def migrate_meeting_settings(data: dict) -> tuple[bool, list[str]]:
    """Remove settings that only Meeting capture used.

    Meeting capture was removed from the app (#140; the work is kept on the
    ``archive/meeting-2026-10-03`` branch). ``meeting_stt_backend`` and
    ``meeting_stt_model`` are dropped, with one notice. A dictation
    ``stt_backend`` set to one of the removed Meeting backends becomes
    ``parakeet`` and keeps its saved model: every Meeting backend ran a Parakeet
    model. Saved notes and meeting transcripts live outside config.yaml and are
    not touched. Changes ``data`` in place and returns whether it changed, plus
    the notices.
    """
    changed = False
    notices: list[str] = []
    removed = [key for key in _MEETING_SETTING_KEYS if key in data]
    if removed:
        for key in removed:
            data.pop(key)
        changed = True
        notices.append(
            f"Removed saved Meeting settings ({', '.join(removed)}): Meeting capture is no "
            "longer in Dictate (#140). Saved meeting transcripts stay in history."
        )
    backend = data.get("stt_backend")
    if isinstance(backend, str) and backend.strip() in MEETING_BACKENDS:
        data["stt_backend"] = "parakeet"
        changed = True
        notices.append(
            f"Moved saved STT backend '{backend}' to parakeet: the Meeting backends were "
            "removed (#140)."
        )
    return changed, notices


def migrate_saved_settings(data: dict) -> tuple[bool, list[str]]:
    """Apply every settings migration to ``data`` (see the ``migrate_*`` functions)."""
    cpu_changed, cpu_notices = migrate_cpu_only_settings(data)
    meeting_changed, meeting_notices = migrate_meeting_settings(data)
    return cpu_changed or meeting_changed, cpu_notices + meeting_notices


def _migrate_saved_config(data: dict, path: Path) -> None:
    """Rewrite config.yaml once when it still holds retired settings."""
    changed, notices = migrate_saved_settings(data)
    if not changed:
        return
    for notice in notices:
        logger.warning(notice)
    try:
        _save_raw(data, path)
    except OSError as exc:
        # The settings above are still used as migrated for this run.
        logger.warning(f"Could not save migrated settings to {path}: {exc}")


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from YAML file. Returns defaults if file doesn't exist.

    A config written while GPU lanes or Meeting capture existed is migrated
    and saved back on the first load (see ``migrate_saved_settings``).
    """
    if not path.is_file():
        return Config()

    try:
        data = _read_config_yaml(path)
    except Exception:
        logger.warning(f"Failed to parse {path}, using defaults")
        return Config()

    if isinstance(data, dict):
        _migrate_saved_config(data, path)

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
    stt_compute_type = data.get("stt_compute_type")
    update_channel = data.get("update_channel")
    installed_package_version = data.get("installed_package_version")
    if not isinstance(stt_backend, str):
        stt_backend = None
    if not isinstance(stt_model, str):
        stt_model = None
    if not isinstance(stt_compute_type, str):
        stt_compute_type = None
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
        stt_compute_type=stt_compute_type,
        update_channel=update_channel,
        installed_package_version=installed_package_version,
    )


def _load_raw(path: Path = CONFIG_PATH) -> dict:
    """Load raw YAML dict, preserving all keys except retired settings.

    Setters save this dict back, so a retired setting is migrated by the first
    write as well as the first ``load_config``.
    """
    if not path.is_file():
        return {}
    try:
        data = _read_config_yaml(path)
    except Exception:
        return {}
    if isinstance(data, dict):
        _changed, notices = migrate_saved_settings(data)
        for notice in notices:
            logger.warning(notice)
    return data


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



def set_installed_package_version(version: str, path: Path = CONFIG_PATH) -> str:
    """Persist the exact package version used by the installer/updater."""
    normalized = version.strip()
    if not normalized or len(normalized) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+._-]*", normalized):
        raise ValueError("installed package version is invalid")
    data = _load_raw(path)
    data["installed_package_version"] = normalized
    _save_raw(data, path)
    return normalized




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
