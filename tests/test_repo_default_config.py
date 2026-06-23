from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class RepoDefaultConfigTests(unittest.TestCase):
    def test_default_install_config_is_valid_and_leaves_model_unset(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "config" / "default-config.yaml"
        data = yaml.safe_load(config_path.read_text())

        self.assertEqual(data["stt_backend"], "faster-whisper")
        self.assertNotIn("stt_model", data)
        self.assertEqual(data["stt_device"], "auto")
        self.assertEqual(data["stt_compute_type"], "int8")
        self.assertEqual(data["push_to_talk_combo"], "ctrl+d")
        self.assertEqual(data["hotwords"], [])


if __name__ == "__main__":
    unittest.main()
