"""The pyannote staging script stages from the build model cache and needs a
Hugging Face token only on a cache miss."""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TOKEN_VARS = ("DICTATE_HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "HF_TOKEN")


def _load_pyannote_script():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "prepare_pyannote_community_model", SCRIPTS / "prepare-pyannote-community-model.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


SCRIPT = _load_pyannote_script()


def _fake_snapshot_download(*, repo_id: str, revision: str, token: str, local_dir: str) -> str:
    root = Path(local_dir)
    for name in (*SCRIPT.REQUIRED_FILES, "README.md", ".cache/huggingface/download/README.md.metadata"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{repo_id}@{revision}:{name}", encoding="utf-8")
    return str(root)


class PyannoteStagingCacheTests(unittest.TestCase):
    def _run(self, *args: str, token: str | None = None) -> tuple[int, str]:
        env = {name: "" for name in TOKEN_VARS}
        if token:
            env["DICTATE_HF_TOKEN"] = token
        err = io.StringIO()
        with (
            patch.dict(os.environ, env),
            patch.object(sys, "argv", ["prepare-pyannote-community-model.py", *args]),
            redirect_stdout(io.StringIO()),
            redirect_stderr(err),
        ):
            return SCRIPT.main(), err.getvalue()

    def test_check_cache_fails_on_a_miss_without_a_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            code, err = self._run("--check-cache", "--cache-dir", temp_dir)
        self.assertEqual(code, 1)
        self.assertIn("Hugging Face token via DICTATE_HF_TOKEN, HUGGINGFACE_HUB_TOKEN, or HF_TOKEN", err)

    def test_check_cache_passes_on_a_miss_with_a_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            code, _err = self._run("--check-cache", "--cache-dir", temp_dir, token="test-token")
        self.assertEqual(code, 0)

    def test_miss_downloads_pinned_revision_then_hit_stages_without_a_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "cache"
            first = Path(temp_dir) / "first"
            second = Path(temp_dir) / "second"
            with patch("huggingface_hub.snapshot_download", side_effect=_fake_snapshot_download) as download:
                code, _ = self._run("--output", str(first), "--cache-dir", str(cache), token="test-token")
                self.assertEqual(code, 0)
                self.assertEqual(download.call_args.kwargs["revision"], SCRIPT.pinned_revision(SCRIPT.MODEL_ID))

                code, _ = self._run("--check-cache", "--cache-dir", str(cache))
                self.assertEqual(code, 0)
                code, _ = self._run("--output", str(second), "--cache-dir", str(cache))
                self.assertEqual(code, 0)
                self.assertEqual(download.call_count, 1)

            for staged in (first, second):
                for name in SCRIPT.REQUIRED_FILES:
                    self.assertTrue((staged / name).is_file(), name)
                self.assertFalse((staged / ".cache").exists())
                self.assertFalse((staged / SCRIPT.COMPLETE_MARKER).exists())
            self.assertEqual(
                sorted(p.relative_to(first).as_posix() for p in first.rglob("*")),
                sorted(p.relative_to(second).as_posix() for p in second.rglob("*")),
            )

    def test_miss_without_a_token_does_not_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("huggingface_hub.snapshot_download") as download:
            code, err = self._run("--output", str(Path(temp_dir) / "out"), "--cache-dir", temp_dir)
        self.assertEqual(code, 1)
        download.assert_not_called()
        self.assertIn("not in the build model cache", err)


if __name__ == "__main__":
    unittest.main()
