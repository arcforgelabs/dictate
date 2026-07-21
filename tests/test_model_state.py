from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dictate import model_state
from dictate.model_state import (
    get_model_error,
    is_model_prepared,
    mark_model_failed,
    mark_model_prepared,
)
from dictate.platform_paths import user_data_dir


class ModelStateTests(unittest.TestCase):
    def test_state_path_uses_platform_data_dir(self) -> None:
        """STATE_PATH must go through platform_paths, not a hardcoded POSIX path.

        Previously it was Path.home() / ".local" / "share" / "dictate", which on
        Windows lands in a hidden non-standard directory instead of
        %LOCALAPPDATA%.
        """
        self.assertEqual(model_state.STATE_PATH, user_data_dir() / "model-state.json")
        self.assertNotIn(".local", model_state.STATE_PATH.parts)
        self.assertNotIn("share", model_state.STATE_PATH.parts)

    def test_resolve_state_path_windows_uses_user_data_dir(self) -> None:
        with patch("dictate.platform_paths.sys.platform", "win32"):
            with patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\sam\AppData\Local"}):
                self.assertEqual(
                    model_state._resolve_state_path(),
                    Path(r"C:\Users\sam\AppData\Local") / "dictate" / "model-state.json",
                )

    def test_resolve_state_path_non_windows_keeps_legacy_literal_independent_of_xdg(self) -> None:
        """Non-Windows must NEVER change: zero Linux/macOS behavior change is required.

        Even with XDG_DATA_HOME set (which would move user_data_dir()'s return
        value), the resolved state path must stay the exact old hardcoded
        literal so existing prepared-model flags aren't silently reset.
        """
        with patch("dictate.platform_paths.sys.platform", "linux"):
            with patch.dict("os.environ", {"XDG_DATA_HOME": "/custom/xdg/data"}):
                self.assertEqual(
                    model_state._resolve_state_path(),
                    Path.home() / ".local" / "share" / "dictate" / "model-state.json",
                )
                self.assertEqual(model_state._resolve_state_path(), model_state.LEGACY_STATE_PATH)

    def test_windows_legacy_state_migrates_when_new_path_absent(self) -> None:
        """One-time migration: existing Windows users must not lose their
        prepared-model cache when the app starts reading from %LOCALAPPDATA%."""
        with tempfile.TemporaryDirectory() as temp_dir:
            new_path = Path(temp_dir) / "new" / "model-state.json"
            legacy_path = Path(temp_dir) / "legacy" / "model-state.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(
                json.dumps({"prepared": ["nemo-canary|nvidia/canary-1b|cuda|int8"], "errors": {}}),
                encoding="utf-8",
            )
            self.assertFalse(new_path.exists())

            with (
                patch("dictate.model_state.STATE_PATH", new_path),
                patch("dictate.model_state.LEGACY_STATE_PATH", legacy_path),
                patch("dictate.model_state.is_windows", return_value=True),
            ):
                state = model_state.load_model_state(path=new_path)

            self.assertIn("nemo-canary|nvidia/canary-1b|cuda|int8", state.prepared)
            # Read-only fallback: neither file was created/modified.
            self.assertFalse(new_path.exists())
            self.assertTrue(legacy_path.is_file())

    def test_non_windows_does_not_migrate_from_legacy_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            new_path = Path(temp_dir) / "new" / "model-state.json"
            legacy_path = Path(temp_dir) / "legacy" / "model-state.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(json.dumps({"prepared": ["x|y|z|w"], "errors": {}}), encoding="utf-8")

            with (
                patch("dictate.model_state.STATE_PATH", new_path),
                patch("dictate.model_state.LEGACY_STATE_PATH", legacy_path),
                patch("dictate.model_state.is_windows", return_value=False),
            ):
                state = model_state.load_model_state(path=new_path)

            self.assertEqual(state.prepared, set())

    def test_migration_does_not_apply_to_caller_supplied_override_paths(self) -> None:
        """The legacy fallback is scoped to the real default STATE_PATH only,
        not to arbitrary override paths callers (like tests) pass in -- so
        tests stay isolated from whatever the real legacy file contains."""
        with tempfile.TemporaryDirectory() as temp_dir:
            other_path = Path(temp_dir) / "some-other-path.json"
            legacy_path = Path(temp_dir) / "legacy" / "model-state.json"
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(json.dumps({"prepared": ["x|y|z|w"], "errors": {}}), encoding="utf-8")

            with (
                patch("dictate.model_state.LEGACY_STATE_PATH", legacy_path),
                patch("dictate.model_state.is_windows", return_value=True),
            ):
                state = model_state.load_model_state(path=other_path)

            self.assertEqual(state.prepared, set())

    def test_state_round_trips_non_ascii_error_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "model-state.json"
            mark_model_failed(
                backend="nemo-canary",
                model="nvidia/canary-1b",
                device="cuda",
                compute_type="int8",
                error_message="échec du téléchargement — délai dépassé",
                path=state_path,
            )
            self.assertEqual(
                get_model_error(
                    backend="nemo-canary",
                    model="nvidia/canary-1b",
                    device="cuda",
                    compute_type="int8",
                    path=state_path,
                ),
                "échec du téléchargement — délai dépassé",
            )

    def test_mark_prepared_sets_ready_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "model-state.json"
            mark_model_prepared(
                backend="nemo-canary",
                model="nvidia/canary-1b-flash",
                device="auto",
                compute_type="int8",
                path=state_path,
            )
            self.assertTrue(
                is_model_prepared(
                    backend="nemo-canary",
                    model="nvidia/canary-1b-flash",
                    device="auto",
                    compute_type="int8",
                    path=state_path,
                )
            )

    def test_mark_failed_clears_ready_flag_and_records_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "model-state.json"
            mark_model_prepared(
                backend="nemo-canary",
                model="nvidia/canary-1b",
                device="cuda",
                compute_type="int8",
                path=state_path,
            )
            mark_model_failed(
                backend="nemo-canary",
                model="nvidia/canary-1b",
                device="cuda",
                compute_type="int8",
                error_message="download timeout",
                path=state_path,
            )
            self.assertFalse(
                is_model_prepared(
                    backend="nemo-canary",
                    model="nvidia/canary-1b",
                    device="cuda",
                    compute_type="int8",
                    path=state_path,
                )
            )
            self.assertEqual(
                get_model_error(
                    backend="nemo-canary",
                    model="nvidia/canary-1b",
                    device="cuda",
                    compute_type="int8",
                    path=state_path,
                ),
                "download timeout",
            )


if __name__ == "__main__":
    unittest.main()
