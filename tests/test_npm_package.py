from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def test_npm_package_includes_linux_source_install_inputs() -> None:
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))
    files = set(package_json["files"])

    assert "pyproject.toml" in files
    assert "src/**/*.py" in files
    assert "ui/" in files
    assert "ui-shell/" in files



@unittest.skipUnless(shutil.which("node"), "node not installed")
@unittest.skipIf(sys.platform == "win32", "the shim runs the .ps1 scripts on Windows")
class LifecycleDispatchTests(unittest.TestCase):
    def _dispatch(self, bin_name: str, *args: str) -> list[str]:
        """Run the npm shim as `bin_name` with stub scripts that echo their argv."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "npm").mkdir()
            shutil.copy("npm/dictate-lifecycle.mjs", root / "npm" / "dictate-lifecycle.mjs")
            for script in ("install.sh", "update.sh", "uninstall.sh"):
                (root / script).write_text(f'echo "{script}" "$@"\n', encoding="utf-8")
            link = root / "npm" / bin_name
            link.symlink_to("dictate-lifecycle.mjs")
            out = subprocess.run(
                ["node", str(link), *args], capture_output=True, text=True, check=True
            ).stdout
        return out.split()

    def test_npx_command_word_wins_over_the_bin_npx_picked(self) -> None:
        # npx runs dictate-update for `npx @arcforgelabs/dictate <command>`.
        self.assertEqual(self._dispatch("dictate-update", "install"), ["install.sh"])
        self.assertEqual(
            self._dispatch("dictate-update", "update", "--user"), ["update.sh", "--user"]
        )
        self.assertEqual(self._dispatch("dictate-update", "uninstall"), ["uninstall.sh"])

    def test_lifecycle_bins_still_dispatch_by_name(self) -> None:
        self.assertEqual(
            self._dispatch("dictate-install", "--no-ui"), ["install.sh", "--no-ui"]
        )
        self.assertEqual(self._dispatch("dictate-update", "--user"), ["update.sh", "--user"])
        self.assertEqual(self._dispatch("dictate-uninstall"), ["uninstall.sh"])
