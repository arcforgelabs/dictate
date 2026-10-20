"""The feature-request form and the Barnacle override parse and keep their shape.

Barnacle reads `.github/barnacle.json` only from the default branch, and GitHub
renders issue forms only there, so a broken file would otherwise surface only
after merge.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml"
BARNACLE = ROOT / ".github" / "barnacle.json"


class FeatureRequestFormTests(unittest.TestCase):
    def test_form_parses_with_issue_form_shape(self) -> None:
        form = yaml.safe_load(FORM.read_text(encoding="utf-8"))
        self.assertIsInstance(form.get("name"), str)
        self.assertIsInstance(form.get("description"), str)
        body = form["body"]
        self.assertIsInstance(body, list)
        ids = []
        for item in body:
            self.assertIn(item["type"], {"markdown", "textarea", "input", "dropdown", "checkboxes"})
            if item["type"] == "markdown":
                self.assertTrue(item["attributes"]["value"].strip())
                continue
            self.assertTrue(item["attributes"]["label"].strip())
            ids.append(item["id"])
        self.assertEqual(len(ids), len(set(ids)))
        by_id = {item.get("id"): item for item in body}
        for required in ("problem", "proposal", "vision"):
            self.assertIs(by_id[required]["validations"]["required"], True)
        self.assertIn("VISION.md", by_id["vision"]["attributes"]["label"])


class BarnacleOverrideTests(unittest.TestCase):
    def test_override_only_adds_label_rules(self) -> None:
        config = json.loads(BARNACLE.read_text(encoding="utf-8"))
        # Any other top-level key would replace the org value instead of merging.
        self.assertEqual(set(config) - {"$comment"}, {"rules"})
        for rule in config["rules"]:
            self.assertEqual(set(rule) - {"close", "stateReason", "message", "lock", "enabled"}, {"label"})
            self.assertIsInstance(rule["label"], str)

    def test_not_in_vision_closes_with_a_link_to_the_vision(self) -> None:
        rules = json.loads(BARNACLE.read_text(encoding="utf-8"))["rules"]
        rule = next(item for item in rules if item["label"] == "r: not-in-vision")
        self.assertIs(rule["close"], True)
        # A vision rejection is "not planned", not "completed".
        self.assertEqual(rule["stateReason"], "not_planned")
        self.assertNotIn("enabled", rule)
        self.assertIn("https://github.com/arcforgelabs/dictate/blob/master/VISION.md", rule["message"])


if __name__ == "__main__":
    unittest.main()
