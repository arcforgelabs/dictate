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
    set_push_to_talk_combo,
    set_stt_runtime_profile,
    set_stt_selection,
)


class ConfigSelectionTests(unittest.TestCase):
    def test_set_stt_preferences_preserve_hotwords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            add_hotwords(["OpenBao"], path=config_path)

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
            self.assertEqual(config.hotwords, ["OpenBao"])
            self.assertEqual(config.hotwords_for_backend("xai"), "OpenBao")
            self.assertIsNone(config.push_to_talk_combo)
            self.assertIsNone(config.push_to_talk_key)
            self.assertEqual(config.stt_backend, "gemini")
            self.assertEqual(config.stt_model, "gemini-3-flash-preview")
            self.assertEqual(config.stt_device, "cuda")
            self.assertEqual(config.stt_compute_type, "float16")

    def test_load_config_reads_push_to_talk_combo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("push_to_talk_combo: ctrl+space\n")

            config = load_config(path=config_path)
            self.assertEqual(config.push_to_talk_combo, "ctrl+space")

    def test_parse_hotwords_text_accepts_pasted_lists(self) -> None:
        text = "Arc Forge, OpenBao\n- Pixel Forge\n1. Lab Flow;  3Shape"

        self.assertEqual(
            parse_hotwords_text(text),
            ["Arc Forge", "OpenBao", "Pixel Forge", "Lab Flow", "3Shape"],
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

    def test_lexicon_replacements_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            add_lexicon_replacements(
                {
                    "kinneri": "canary",
                    "openbow": "OpenBao",
                },
                path=config_path,
            )
            removed = remove_lexicon_replacements(["openbow"], path=config_path)
            self.assertEqual(removed, ["openbow"])

            config = load_config(path=config_path)
            self.assertEqual(
                config.lexicon_replacements,
                {"kinneri": "canary"},
            )


if __name__ == "__main__":
    unittest.main()
