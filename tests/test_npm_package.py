from __future__ import annotations

import json
from pathlib import Path


def test_npm_package_includes_linux_source_install_inputs() -> None:
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))
    files = set(package_json["files"])

    assert "pyproject.toml" in files
    assert "src/**/*.py" in files
    assert "ui/" in files
    assert "ui-shell/" in files
