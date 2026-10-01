from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dictate import runtime_logging


@contextlib.contextmanager
def _isolated_log_dirs(temp_dir: str) -> Iterator[Path]:
    """Point every log dir Dictate knows about (primary, fallback, legacy) into temp_dir."""
    root = Path(temp_dir)
    log_dir = root / "logs"
    with (
        patch.object(runtime_logging, "LOG_DIR", log_dir),
        patch.object(runtime_logging, "LATEST_LOG_PATH", log_dir / "latest.log"),
        patch.object(runtime_logging, "LAST_FAILURE_LOG_PATH", log_dir / "last_failure.log"),
        patch.object(runtime_logging, "FALLBACK_LOG_DIR", root / "fallback-logs"),
        patch.object(runtime_logging, "LEGACY_LOG_DIRS", (root / "legacy-logs",)),
    ):
        yield log_dir


# What Dictate 2026.9.27 and earlier wrote: the recording indicator has no
# newline, so the next line starts on the same line after a carriage return.
OLD_FORMAT_LOG = (
    "dictate: startup at 2026-09-27T10:00:00+09:30\n"
    "\r  \x1b[91m● Recording...\x1b[0m\r  Typed: please email Alex the contract\n"
    "\r  Saved note: call the dentist about Thursday\n"
    "\r  Typed: [12 characters, not logged]\n"
    "\r  Microphone error: device busy\n"
    "dictate: exit code 1\n"
)
SCRUBBED_LOG = (
    "dictate: startup at 2026-09-27T10:00:00+09:30\n"
    "\r  \x1b[91m● Recording...\x1b[0m\r  Typed: [30 characters, not logged]\n"
    "\r  Saved note: [31 characters, not logged]\n"
    "\r  Typed: [12 characters, not logged]\n"
    "\r  Microphone error: device busy\n"
    "dictate: exit code 1\n"
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _read(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


class LegacyLogScrubTests(unittest.TestCase):
    def test_old_format_lines_redacted_and_others_untouched(self) -> None:
        self.assertEqual(runtime_logging.redact_dictated_text(OLD_FORMAT_LOG), SCRUBBED_LOG)

    def test_crlf_line_endings_are_kept(self) -> None:
        self.assertEqual(
            runtime_logging.redact_dictated_text("\r  Typed: hello there\r\nnext\r\n"),
            "\r  Typed: [11 characters, not logged]\r\nnext\r\n",
        )

    def test_last_line_without_newline_is_redacted(self) -> None:
        self.assertEqual(
            runtime_logging.redact_dictated_text("\r  Saved note: half written"),
            "\r  Saved note: [12 characters, not logged]",
        )

    def test_startup_scrubs_last_failure_and_other_dirs_but_not_active_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, _isolated_log_dirs(temp_dir) as log_dir:
            root = Path(temp_dir)
            targets = [
                log_dir / "last_failure.log",
                root / "fallback-logs" / "latest.log",
                root / "fallback-logs" / "last_failure.log",
                root / "legacy-logs" / "last_failure.log",
            ]
            for target in targets:
                _write(target, OLD_FORMAT_LOG)
            _write(log_dir / "latest.log", OLD_FORMAT_LOG)
            unrelated = log_dir / "notes.txt"
            _write(unrelated, OLD_FORMAT_LOG)

            with patch("sys.stderr", new_callable=StringIO):
                code = runtime_logging.run_with_startup_logging(lambda: 0)

            self.assertEqual(code, 0)
            for target in targets:
                self.assertEqual(_read(target), SCRUBBED_LOG, target)
            # The active latest.log is truncated by the new run, not scrubbed.
            latest = _read(log_dir / "latest.log")
            self.assertNotIn("contract", latest)
            self.assertIn("dictate: startup at", latest)
            self.assertNotIn("could not remove", latest)
            # Only latest.log / last_failure.log in Dictate's log dirs are touched.
            self.assertEqual(_read(unrelated), OLD_FORMAT_LOG)
            self.assertEqual(
                sorted(p.name for p in log_dir.iterdir()),
                ["last_failure.log", "latest.log", "notes.txt"],
            )

    def test_second_run_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, _isolated_log_dirs(temp_dir) as log_dir:
            target = log_dir / "last_failure.log"
            _write(target, OLD_FORMAT_LOG)
            self.assertEqual(runtime_logging.scrub_dictated_text_from_logs(), [])
            self.assertEqual(_read(target), SCRUBBED_LOG)
            past = 1_600_000_000
            os.utime(target, (past, past))
            inode = target.stat().st_ino

            self.assertEqual(runtime_logging.scrub_dictated_text_from_logs(), [])

            self.assertEqual(_read(target), SCRUBBED_LOG)
            self.assertEqual(target.stat().st_mtime, past)
            self.assertEqual(target.stat().st_ino, inode)

    def test_unreadable_log_warns_without_content_and_startup_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, _isolated_log_dirs(temp_dir) as log_dir:
            target = log_dir / "last_failure.log"
            _write(target, OLD_FORMAT_LOG)
            real_open = os.open

            def _deny(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
                if Path(path) == target:
                    raise PermissionError(13, "Permission denied")
                return real_open(path, *args, **kwargs)

            with (
                patch.object(runtime_logging.os, "open", _deny),
                patch("sys.stderr", new_callable=StringIO),
            ):
                code = runtime_logging.run_with_startup_logging(lambda: 0)

            self.assertEqual(code, 0)
            latest = _read(log_dir / "latest.log")
            self.assertIn(
                f"could not remove dictated text from older log {target}: Permission denied",
                latest,
            )
            self.assertEqual(_read(target), OLD_FORMAT_LOG)
            self.assertNotIn("contract", latest)
            self.assertNotIn("dentist", latest)

    def test_scrub_error_never_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, _isolated_log_dirs(temp_dir) as log_dir:
            _write(log_dir / "last_failure.log", OLD_FORMAT_LOG)
            boom = RuntimeError("Typed: secret")
            with patch.object(runtime_logging, "redact_dictated_text", side_effect=boom):
                warnings = runtime_logging.scrub_dictated_text_from_logs()
            self.assertEqual(len(warnings), 1)
            self.assertTrue(warnings[0].endswith(": RuntimeError"))
            self.assertNotIn("secret", warnings[0])

    @unittest.skipUnless(hasattr(os, "symlink") and hasattr(os, "getuid"), "POSIX symlinks")
    def test_symlinked_log_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, _isolated_log_dirs(temp_dir):
            outside = Path(temp_dir) / "outside.txt"
            _write(outside, OLD_FORMAT_LOG)
            link = Path(temp_dir) / "fallback-logs" / "last_failure.log"
            link.parent.mkdir(parents=True)
            link.symlink_to(outside)

            self.assertEqual(runtime_logging.scrub_dictated_text_from_logs(), [])

            self.assertTrue(link.is_symlink())
            self.assertEqual(_read(outside), OLD_FORMAT_LOG)


class RuntimeLoggingTests(unittest.TestCase):
    def test_run_with_startup_logging_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            with _isolated_log_dirs(temp_dir), patch(
                "sys.stderr", new_callable=StringIO
            ):
                code = runtime_logging.run_with_startup_logging(lambda: 0)
                self.assertEqual(code, 0)
                self.assertTrue((log_dir / "latest.log").exists())
                self.assertFalse((log_dir / "last_failure.log").exists())

    def test_run_with_startup_logging_nonzero_records_last_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            with _isolated_log_dirs(temp_dir), patch(
                "sys.stderr", new_callable=StringIO
            ):
                code = runtime_logging.run_with_startup_logging(lambda: 2)
                self.assertEqual(code, 2)
                self.assertTrue((log_dir / "latest.log").exists())
                self.assertTrue((log_dir / "last_failure.log").exists())

    def test_run_with_startup_logging_allows_missing_gui_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            with _isolated_log_dirs(temp_dir), patch(
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
            with _isolated_log_dirs(temp_dir), patch(
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


    def test_closing_mirrored_stderr_does_not_raise(self) -> None:
        # A library closing sys.stderr at exit used to raise AttributeError.
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir) / "logs"
            with patch.object(runtime_logging, "LOG_DIR", log_dir), patch.object(
                runtime_logging, "LATEST_LOG_PATH", log_dir / "latest.log"
            ), patch.object(runtime_logging, "LAST_FAILURE_LOG_PATH", log_dir / "last_failure.log"), patch(
                "sys.stderr", new_callable=StringIO
            ):
                def close_stderr() -> int:
                    import sys

                    print("before close", file=sys.stderr)
                    sys.stderr.close()
                    return 0

                code = runtime_logging.run_with_startup_logging(close_stderr)

            self.assertEqual(code, 0)
            latest = (log_dir / "latest.log").read_text(encoding="utf-8")
            self.assertIn("before close", latest)
            self.assertIn("dictate: exit code 0", latest)

if __name__ == "__main__":
    unittest.main()
