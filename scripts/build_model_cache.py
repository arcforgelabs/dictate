"""Pinned revisions and the local cache for the models desktop builds bundle.

Stdlib only: the pyannote cache preflight runs with the host Python before the
build venv exists.

Each model is fetched once into ``<cache root>/<owner>--<repo>@<revision>`` and
copied into the stage dir from there. CI restores the cache root with
``actions/cache`` keyed on ``packaging/model-revisions.json``, so a build with
unchanged revisions downloads nothing and needs no Hugging Face token.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISIONS_FILE = ROOT / "packaging" / "model-revisions.json"
CACHE_DIR_ENV = "DICTATE_MODEL_CACHE_DIR"
DEFAULT_CACHE_DIR = Path("~/.cache/dictate-build-models")


def pinned_revision(repo_id: str) -> str:
    revisions = json.loads(REVISIONS_FILE.read_text(encoding="utf-8"))
    try:
        return revisions[repo_id]
    except KeyError:
        raise SystemExit(f"no pinned revision for {repo_id} in {REVISIONS_FILE}") from None


def default_cache_dir() -> Path:
    return Path(os.environ.get(CACHE_DIR_ENV) or DEFAULT_CACHE_DIR).expanduser()


def cache_path(cache_dir: str | Path, repo_id: str, revision: str) -> Path:
    return Path(cache_dir).expanduser().resolve() / f"{repo_id.replace('/', '--')}@{revision}"


def huggingface_token() -> str | None:
    return (
        os.environ.get("DICTATE_HF_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or os.environ.get("HF_TOKEN")
    )
