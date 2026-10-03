from __future__ import annotations

import locale
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from dictate.config import (
    add_hotwords,
    add_lexicon_replacements,
    load_config,
    parse_hotwords_text,
    remove_lexicon_replacements,
    set_installed_package_version,
    set_push_to_talk_combo,
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
            config = load_config(path=config_path)
            self.assertEqual(config.hotwords, ["AcmeWidget"])
            self.assertEqual(config.hotwords_for_backend("gemini"), "AcmeWidget")
            self.assertIsNone(config.push_to_talk_combo)
            self.assertIsNone(config.push_to_talk_key)
            self.assertEqual(config.stt_backend, "gemini")
            self.assertEqual(config.stt_model, "gemini-3-flash-preview")

    def test_gpu_era_settings_migrate_to_cpu_on_first_load(self) -> None:
        # Dictate runs on CPU only. A config written while GPU lanes existed
        # moves to CPU on the first load and is saved back, keeping every
        # other choice; it neither fails nor keeps the GPU setting around.
        for device in ("cuda", "amd"):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.yaml"
                config_path.write_text(
                    "hotwords: [AcmeWidget]\n"
                    "lexicon_replacements: {acme: Acme}\n"
                    "stt_backend: parakeet\n"
                    "stt_model: parakeet-tdt-0.6b-v3\n"
                    f"stt_device: {device}\n"
                    "stt_compute_type: float16\n",
                    encoding="utf-8",
                )

                with self.assertLogs("dictate.config", level="WARNING") as logs:
                    config = load_config(path=config_path)

                self.assertEqual(config.stt_compute_type, "int8")
                self.assertFalse(hasattr(config, "stt_device"))
                self.assertEqual(config.hotwords, ["AcmeWidget"])
                self.assertEqual(config.lexicon_replacements, {"acme": "Acme"})
                self.assertEqual(config.stt_backend, "parakeet")
                self.assertEqual(config.stt_model, "parakeet-tdt-0.6b-v3")
                self.assertEqual(
                    [record.getMessage() for record in logs.records],
                    [
                        f"Moved saved STT device '{device}' to CPU: Dictate runs on CPU only.",
                        "Moved saved STT compute type 'float16' to int8: "
                        "Dictate runs on CPU only.",
                    ],
                )

                saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                self.assertNotIn("stt_device", saved)
                self.assertEqual(saved["stt_compute_type"], "int8")
                self.assertEqual(saved["hotwords"], ["AcmeWidget"])
                self.assertEqual(saved["lexicon_replacements"], {"acme": "Acme"})
                self.assertEqual(saved["stt_backend"], "parakeet")
                self.assertEqual(saved["stt_model"], "parakeet-tdt-0.6b-v3")

                # The migration happens once: the next load is silent.
                with self.assertNoLogs("dictate.config", level="WARNING"):
                    self.assertEqual(load_config(path=config_path).stt_compute_type, "int8")

    def test_saved_cpu_or_auto_device_is_dropped_silently(self) -> None:
        for device in ("cpu", "auto"):
            with self.subTest(device=device), tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.yaml"
                config_path.write_text(
                    f"stt_device: {device}\nstt_compute_type: float32\n", encoding="utf-8"
                )

                with self.assertNoLogs("dictate.config", level="WARNING"):
                    config = load_config(path=config_path)

                self.assertEqual(config.stt_compute_type, "float32")
                saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved, {"stt_compute_type": "float32"})

    def test_current_config_is_not_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            original = "# my notes\nhotwords: [AcmeWidget]\nstt_compute_type: int8\n"
            config_path.write_text(original, encoding="utf-8")

            load_config(path=config_path)

            self.assertEqual(config_path.read_text(encoding="utf-8"), original)

    def test_gpu_era_settings_still_load_when_config_cannot_be_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "stt_device: cuda\nstt_compute_type: float16\n", encoding="utf-8"
            )

            with (
                patch("dictate.config._save_raw", side_effect=PermissionError("read-only")),
                self.assertLogs("dictate.config", level="WARNING") as logs,
            ):
                config = load_config(path=config_path)

            self.assertEqual(config.stt_compute_type, "int8")
            self.assertTrue(
                any(
                    "Could not save migrated settings" in record.getMessage()
                    for record in logs.records
                )
            )

    def test_first_setter_write_also_drops_gpu_era_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "stt_device: cuda\nstt_compute_type: float16\n", encoding="utf-8"
            )

            with self.assertLogs("dictate.config", level="WARNING"):
                add_hotwords(["AcmeWidget"], path=config_path)

            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, {"hotwords": ["AcmeWidget"], "stt_compute_type": "int8"})

    def test_saved_meeting_settings_are_removed_on_upgrade(self) -> None:
        # What 2026.9.27 wrote after "dictate config set-meeting-model" (#140).
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "hotwords:\n- AcmeWidget\n"
                "push_to_talk_combo: ctrl_r\n"
                "stt_backend: parakeet\n"
                "stt_model: parakeet-tdt-0.6b-v3\n"
                "meeting_stt_backend: parakeet-pyannote\n"
                "meeting_stt_model: parakeet-tdt-0.6b-v2\n",
                encoding="utf-8",
            )

            with self.assertLogs("dictate.config", level="WARNING") as logs:
                config = load_config(path=config_path)

            self.assertEqual(len(logs.output), 1)
            self.assertIn("Removed saved Meeting settings", logs.output[0])
            self.assertNotIn("\n", logs.output[0])
            self.assertEqual(config.stt_backend, "parakeet")
            self.assertEqual(config.stt_model, "parakeet-tdt-0.6b-v3")
            self.assertEqual(config.hotwords, ["AcmeWidget"])
            self.assertEqual(config.push_to_talk_combo, "ctrl_r")
            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved,
                {
                    "hotwords": ["AcmeWidget"],
                    "push_to_talk_combo": "ctrl_r",
                    "stt_backend": "parakeet",
                    "stt_model": "parakeet-tdt-0.6b-v3",
                },
            )
            # Migrated once: the next start is quiet.
            with self.assertNoLogs("dictate.config", level="WARNING"):
                load_config(path=config_path)

    def test_meeting_backend_saved_for_dictation_moves_to_parakeet(self) -> None:
        for backend in ("parakeet-pyannote", "parakeet-diarizen", "parakeet-sortformer"):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "config.yaml"
                config_path.write_text(
                    f"stt_backend: {backend}\nstt_model: parakeet-tdt-0.6b-v3\n",
                    encoding="utf-8",
                )

                with self.assertLogs("dictate.config", level="WARNING") as logs:
                    config = load_config(path=config_path)

                self.assertEqual(config.stt_backend, "parakeet")
                self.assertEqual(config.stt_model, "parakeet-tdt-0.6b-v3")
                self.assertIn(f"Moved saved STT backend '{backend}' to parakeet", logs.output[0])
                saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    saved, {"stt_backend": "parakeet", "stt_model": "parakeet-tdt-0.6b-v3"}
                )

    def test_malformed_meeting_settings_never_break_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "meeting_stt_backend: 42\nmeeting_stt_model:\n- odd\nhotwords: [Acme]\n",
                encoding="utf-8",
            )

            with self.assertLogs("dictate.config", level="WARNING"):
                config = load_config(path=config_path)

            self.assertEqual(config.hotwords, ["Acme"])
            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, {"hotwords": ["Acme"]})

    def test_setter_drops_meeting_settings_too(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "meeting_stt_backend: parakeet-pyannote\nmeeting_stt_model: parakeet-tdt-0.6b-v2\n",
                encoding="utf-8",
            )

            with self.assertLogs("dictate.config", level="WARNING"):
                add_hotwords(["AcmeWidget"], path=config_path)

            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, {"hotwords": ["AcmeWidget"]})

    def test_hotwords_for_backend_is_uniform_across_backends(self) -> None:
        """Transcription is local-only, so every backend gets the same space-joined
        hotword string (and None when there are no hotwords)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"

            self.assertIsNone(
                load_config(path=config_path).hotwords_for_backend("parakeet")
            )

            add_hotwords(["AcmeWidget", "ProjectNova"], path=config_path)
            config = load_config(path=config_path)

            for backend in ("parakeet", "parakeet-pyannote", "parakeet-sortformer"):
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


if __name__ == "__main__":
    unittest.main()
