from __future__ import annotations

import locale
import tempfile
import unittest
from pathlib import Path

from dictate.config import (
    add_hotwords,
    add_lexicon_replacements,
    load_config,
    parse_hotwords_text,
    remove_lexicon_replacements,
    set_installed_package_version,
    set_push_to_talk_combo,
    set_meeting_stt_selection,
    set_stt_runtime_profile,
    set_stt_selection,
    set_update_channel,
)


class ConfigSelectionTests(unittest.TestCase):
    def test_set_stt_preferences_preserve_hotwords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            add_hotwords(["AcmeWidget"], path=config_path)

            set_stt_selection(
                backend="gemini",
                model="gemini-3-flash-preview",
                path=config_path,
            )
            set_stt_runtime_profile(
                device="cuda",
                compute_type="float16",
                path=config_path,
            )

            config = load_config(path=config_path)
            self.assertEqual(config.hotwords, ["AcmeWidget"])
            self.assertEqual(config.hotwords_for_backend("gemini"), "AcmeWidget")
            self.assertIsNone(config.push_to_talk_combo)
            self.assertIsNone(config.push_to_talk_key)
            self.assertEqual(config.stt_backend, "gemini")
            self.assertEqual(config.stt_model, "gemini-3-flash-preview")
            self.assertEqual(config.stt_device, "cuda")
            self.assertEqual(config.stt_compute_type, "float16")

    def test_set_meeting_stt_preferences_preserve_primary_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            set_stt_selection("parakeet", "parakeet-tdt-0.6b-v2", path=config_path)

            set_meeting_stt_selection(
                "parakeet-pyannote",
                "parakeet-tdt-0.6b-v3",
                path=config_path,
            )

            config = load_config(path=config_path)
            self.assertEqual(config.stt_backend, "parakeet")
            self.assertEqual(config.stt_model, "parakeet-tdt-0.6b-v2")
            self.assertEqual(config.meeting_stt_backend, "parakeet-pyannote")
            self.assertEqual(config.meeting_stt_model, "parakeet-tdt-0.6b-v3")

    def test_hotwords_for_backend_is_uniform_across_backends(self) -> None:
        """Transcription is local-only, so every backend gets the same space-joined
        hotword string (and None when there are no hotwords)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            self.assertIsNone(
                load_config(path=config_path).hotwords_for_backend("faster-whisper")
            )

            add_hotwords(["AcmeWidget", "ProjectNova"], path=config_path)
            config = load_config(path=config_path)

            for backend in ("faster-whisper", "parakeet", "whisperx", "gemini"):
                self.assertEqual(
                    config.hotwords_for_backend(backend),
                    "AcmeWidget ProjectNova",
                )

    def test_load_config_reads_push_to_talk_combo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("push_to_talk_combo: ctrl+space\n")

            config = load_config(path=config_path)
            self.assertEqual(config.push_to_talk_combo, "ctrl+space")

    def test_parse_hotwords_text_accepts_pasted_lists(self) -> None:
        text = "AcmeWidget, ProjectNova\n- TeamAtlas\n1. ModelThree;  WidgetSuite"

        self.assertEqual(
            parse_hotwords_text(text),
            ["AcmeWidget", "ProjectNova", "TeamAtlas", "ModelThree", "WidgetSuite"],
        )

    def test_set_push_to_talk_combo_replaces_legacy_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("push_to_talk_key: ctrl_l\n")

            set_push_to_talk_combo("ctrl+space", path=config_path)
            config = load_config(path=config_path)
            self.assertEqual(config.push_to_talk_combo, "ctrl+space")
            self.assertIsNone(config.push_to_talk_key)

    def test_set_update_channel_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            saved = set_update_channel("unstable", path=config_path)

            config = load_config(path=config_path)
            self.assertEqual(saved, "unstable")
            self.assertEqual(config.update_channel, "unstable")

    def test_set_update_channel_accepts_latest_alias_for_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            saved = set_update_channel("latest", path=config_path)

            self.assertEqual(saved, "stable")
            self.assertEqual(load_config(path=config_path).update_channel, "stable")

    def test_set_installed_package_version_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            saved = set_installed_package_version("2026.7.4-unstable.123.1", path=config_path)

            self.assertEqual(saved, "2026.7.4-unstable.123.1")
            self.assertEqual(
                load_config(path=config_path).installed_package_version,
                "2026.7.4-unstable.123.1",
            )

    def test_non_ascii_hotwords_and_lexicon_round_trip(self) -> None:
        """A UTF-8 config with accented/non-Latin terms must not fall back to defaults."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            add_hotwords(["café", "naïve", "北京"], path=config_path)
            add_lexicon_replacements(
                {"kinneri": "café", "naiv": "naïve"},
                path=config_path,
            )

            # The file on disk must actually be UTF-8, not escaped ASCII.
            raw_bytes = config_path.read_bytes()
            raw_bytes.decode("utf-8")  # must not raise
            self.assertIn("café".encode("utf-8"), raw_bytes)

            config = load_config(path=config_path)
            self.assertEqual(config.hotwords, ["café", "naïve", "北京"])
            self.assertEqual(
                config.lexicon_replacements,
                {"kinneri": "café", "naiv": "naïve"},
            )

    def test_load_config_recovers_pre_existing_non_utf8_config(self) -> None:
        """A hand-edited or pre-fix config written in the locale's ANSI encoding
        (e.g. cp1252 on Windows) must not silently reset to defaults."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            encoding = locale.getpreferredencoding(False)
            yaml_text = "hotwords:\n  - café\npush_to_talk_combo: ctrl+space\n"
            config_path.write_bytes(yaml_text.encode(encoding))

            config = load_config(path=config_path)
            self.assertEqual(config.hotwords, ["café"])
            self.assertEqual(config.push_to_talk_combo, "ctrl+space")

    def test_add_hotwords_recovers_pre_existing_non_utf8_config(self) -> None:
        """_load_raw (used by every setter) gets the same tolerant retry."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            encoding = locale.getpreferredencoding(False)
            config_path.write_bytes("hotwords:\n  - café\n".encode(encoding))

            added = add_hotwords(["naïve"], path=config_path)
            self.assertEqual(added, ["naïve"])

            config = load_config(path=config_path)
            self.assertEqual(config.hotwords, ["café", "naïve"])

    def test_lexicon_replacements_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            add_lexicon_replacements(
                {
                    "kinneri": "canary",
                    "acme-widgit": "AcmeWidget",
                },
                path=config_path,
            )
            removed = remove_lexicon_replacements(["acme-widgit"], path=config_path)
            self.assertEqual(removed, ["acme-widgit"])

            config = load_config(path=config_path)
            self.assertEqual(
                config.lexicon_replacements,
                {"kinneri": "canary"},
            )


class DistilWhisperModelNameTests(unittest.TestCase):
    def test_distil_large_v35_is_resolved_by_faster_whisper(self) -> None:
        # faster-whisper >= 1.2 maps this alias to the official CTranslate2
        # conversion itself, so the backend passes the name through untouched.
        from faster_whisper.utils import _MODELS

        from dictate.stt.faster_whisper_backend import FasterWhisperSpeechToText

        backend = FasterWhisperSpeechToText(model_name="distil-large-v3.5")
        self.assertEqual(backend.model_name, "distil-large-v3.5")
        self.assertEqual(_MODELS["distil-large-v3.5"], "distil-whisper/distil-large-v3.5-ct2")

    def test_distil_large_v35_is_a_listed_faster_whisper_model(self) -> None:
        from dictate.stt.factory import FASTER_WHISPER_MODELS, resolve_model_name

        self.assertIn("distil-large-v3.5", FASTER_WHISPER_MODELS)
        self.assertEqual(
            resolve_model_name("faster-whisper", "distil-large-v3.5"), "distil-large-v3.5"
        )


if __name__ == "__main__":
    unittest.main()
