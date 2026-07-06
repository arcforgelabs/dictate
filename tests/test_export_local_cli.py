from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import __main__ as main_module


def _run_export_local(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = main_module._handle_export_local_command(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class _FakeExportBackend:
    def export_local_data(self) -> dict:
        return {
            "schema": "dictate.local-export.v1",
            "history": [{"id": "h1", "text": "local only"}],
            "notes": [],
        }


class ExportLocalCliTests(unittest.TestCase):
    def test_main_dispatches_export_local_subcommand(self) -> None:
        with patch("dictate.ui_server.UiBackend", return_value=_FakeExportBackend()):
            code = main_module.main(["export-local"])

        self.assertEqual(code, 0)

    def test_export_local_writes_json_to_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dictate-local-export.json"
            with patch("dictate.ui_server.UiBackend", return_value=_FakeExportBackend()):
                code, out, err = _run_export_local(["--output", str(output)])

            exported = json.loads(output.read_text())

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("local export written", out)
        self.assertEqual(exported["schema"], "dictate.local-export.v1")
        self.assertEqual(exported["history"][0]["text"], "local only")


if __name__ == "__main__":
    unittest.main()
