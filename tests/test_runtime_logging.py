from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dictate import runtime_logging


class RuntimeLoggingTests(unittest.TestCase):
    def test_run_with_startup_logging_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            with patch.object(runtime_logging, "LOG_DIR", log_dir), patch.object(
                runtime_logging, "LATEST_LOG_PATH", log_dir / "latest.log"
            ), patch.object(runtime_logging, "LAST_FAILURE_LOG_PATH", log_dir / "last_failure.log"), patch(
                "sys.stderr", new_callable=StringIO
            ):
                code = runtime_logging.run_with_startup_logging(lambda: 0)
                self.assertEqual(code, 0)
                self.assertTrue((log_dir / "latest.log").exists())
                self.assertFalse((log_dir / "last_failure.log").exists())

    def test_run_with_startup_logging_nonzero_records_last_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            with patch.object(runtime_logging, "LOG_DIR", log_dir), patch.object(
                runtime_logging, "LATEST_LOG_PATH", log_dir / "latest.log"
            ), patch.object(runtime_logging, "LAST_FAILURE_LOG_PATH", log_dir / "last_failure.log"), patch(
                "sys.stderr", new_callable=StringIO
            ):
                code = runtime_logging.run_with_startup_logging(lambda: 2)
                self.assertEqual(code, 2)
                self.assertTrue((log_dir / "latest.log").exists())
                self.assertTrue((log_dir / "last_failure.log").exists())

    def test_run_with_startup_logging_allows_missing_gui_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            with patch.object(runtime_logging, "LOG_DIR", log_dir), patch.object(
                runtime_logging, "LATEST_LOG_PATH", log_dir / "latest.log"
            ), patch.object(runtime_logging, "LAST_FAILURE_LOG_PATH", log_dir / "last_failure.log"), patch(
                "sys.stderr",
                None,
            ):
                code = runtime_logging.run_with_startup_logging(lambda: 0)

            self.assertEqual(code, 0)
            latest = (log_dir / "latest.log").read_text(encoding="utf-8")
            self.assertIn("dictate: startup at", latest)
            self.assertIn("dictate: exit code 0", latest)
            self.assertFalse((log_dir / "last_failure.log").exists())

    def test_dictated_text_reaches_terminal_but_not_log(self) -> None:
        class _Tty(StringIO):
            def isatty(self) -> bool:
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            terminal = _Tty()
            with patch.object(runtime_logging, "LOG_DIR", log_dir), patch.object(
                runtime_logging, "LATEST_LOG_PATH", log_dir / "latest.log"
            ), patch.object(runtime_logging, "LAST_FAILURE_LOG_PATH", log_dir / "last_failure.log"), patch(
                "sys.stderr", terminal
            ):
                runtime_logging.run_with_startup_logging(
                    lambda: runtime_logging.echo_dictated_text("Typed", "my secret words") or 0
                )

            latest = (log_dir / "latest.log").read_text(encoding="utf-8")
            self.assertNotIn("my secret words", latest)
            self.assertIn("Typed: [15 characters, not logged]", latest)
            self.assertIn("Typed: my secret words", terminal.getvalue())

    def test_dictated_text_redacted_when_stderr_is_not_a_terminal(self) -> None:
        # A desktop launch hands stderr to the system journal, not a terminal.
        captured = StringIO()
        with patch("sys.stderr", captured):
            runtime_logging.echo_dictated_text("Saved note", "meeting notes")
        self.assertNotIn("meeting notes", captured.getvalue())
        self.assertIn("Saved note: [13 characters, not logged]", captured.getvalue())

    def test_dictated_text_with_no_stderr_is_a_no_op(self) -> None:
        with patch("sys.stderr", None):
            runtime_logging.echo_dictated_text("Typed", "anything")


if __name__ == "__main__":
    unittest.main()
