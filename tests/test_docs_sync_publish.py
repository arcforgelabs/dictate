"""docs/ is published as the docs site (arcforgelabs/docs).

The sync refuses a tree whose docs/docs.json names a missing page or leaves
one out; this runs the same check.
"""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DocsSyncPublishTest(unittest.TestCase):
    def test_docs_json_lists_every_page_once(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is needed for scripts/docs-sync-publish.mjs")
        result = subprocess.run(
            [node, str(ROOT / "scripts" / "docs-sync-publish.mjs"), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
