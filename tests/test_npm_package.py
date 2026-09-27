from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")


def test_npm_package_includes_linux_source_install_inputs() -> None:
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))
    files = set(package_json["files"])

    assert "pyproject.toml" in files
    assert "src/**/*.py" in files
    assert "ui/" in files
    assert "ui-shell/" in files


def _lifecycle_dispatch(tmp_path: Path, bin_name: str, *args: str) -> list[str]:
    """Run the npm shim as `bin_name` with stub scripts that echo their argv."""
    root = Path(tempfile.mkdtemp(dir=tmp_path))
    (root / "npm").mkdir(parents=True)
    shutil.copy("npm/dictate-lifecycle.mjs", root / "npm" / "dictate-lifecycle.mjs")
    for script in ("install.sh", "update.sh", "uninstall.sh"):
        (root / script).write_text(f'echo "{script}" "$@"\n', encoding="utf-8")
    link = root / "npm" / bin_name
    link.symlink_to("dictate-lifecycle.mjs")
    out = subprocess.run(
        ["node", str(link), *args], capture_output=True, text=True, check=True
    ).stdout
    return out.split()


@needs_node
def test_npx_command_word_wins_over_the_bin_npx_picked(tmp_path: Path) -> None:
    # npx runs dictate-update for `npx @arcforgelabs/dictate <command>`.
    assert _lifecycle_dispatch(tmp_path, "dictate-update", "install") == ["install.sh"]
    assert _lifecycle_dispatch(tmp_path, "dictate-update", "update", "--user") == [
        "update.sh",
        "--user",
    ]
    assert _lifecycle_dispatch(tmp_path, "dictate-update", "uninstall") == ["uninstall.sh"]


@needs_node
def test_lifecycle_bins_still_dispatch_by_name(tmp_path: Path) -> None:
    assert _lifecycle_dispatch(tmp_path, "dictate-install", "--no-ui") == ["install.sh", "--no-ui"]
    assert _lifecycle_dispatch(tmp_path, "dictate-update", "--user") == ["update.sh", "--user"]
    assert _lifecycle_dispatch(tmp_path, "dictate-uninstall") == ["uninstall.sh"]
