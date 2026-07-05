from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dictate.config import (
    add_hotwords,
    add_lexicon_replacements,
    load_config,
    parse_hotwords_text,
    remove_lexicon_replacements,
    set_api_key_command,
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
            self.assertEqual(config.hotwords_for_backend("xai"), "AcmeWidget")
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

    def test_load_config_reads_openai_key_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("openai_api_key_command: /usr/bin/printf key\n")

            config = load_config(path=config_path)
            self.assertEqual(config.openai_api_key_command, "/usr/bin/printf key")

    def test_load_config_reads_xai_key_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("xai_api_key_command: /usr/bin/printf key\n")

            config = load_config(path=config_path)
            self.assertEqual(config.xai_api_key_command, "/usr/bin/printf key")

    def test_load_config_reads_gemini_key_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("gemini_api_key_command: /usr/bin/printf key\n")

            config = load_config(path=config_path)
            self.assertEqual(config.gemini_api_key_command, "/usr/bin/printf key")

    def test_set_api_key_command_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            set_api_key_command("gemini", "/usr/bin/printf key", path=config_path)

            config = load_config(path=config_path)
            self.assertEqual(config.gemini_api_key_command, "/usr/bin/printf key")

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
