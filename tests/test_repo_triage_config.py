"""The feature-request form parses and keeps its required submission fields.

GitHub renders issue forms only from the default branch, so a broken file
would otherwise surface only after merge.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml"


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




if __name__ == "__main__":
    unittest.main()
