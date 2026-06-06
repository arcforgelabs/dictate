"""Release update checks for Settings/About surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

from dictate.version import RELEASE_VERSION

LATEST_RELEASE_URL = "https://api.github.com/repos/arcforgelabs/dictate/releases/latest"
LATEST_TAGS_URL = "https://api.github.com/repos/arcforgelabs/dictate/tags?per_page=1"
RELEASES_URL = "https://github.com/arcforgelabs/dictate/releases"
DOCUMENTATION_URL = "https://github.com/arcforgelabs/dictate#readme"
TERMS_URL = "https://arcforge.au/terms"


@dataclass(frozen=True)
class UpdateStatus:
    current_version: str
    latest_version: str | None = None
    update_available: bool = False
    checked: bool = False
    error: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class UpdateFlow:
    mode: str
    started: bool
    url: str | None = None
    message: str | None = None


def parse_calver(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    match = re.fullmatch(r"v?(\d{4})\.(\d{1,2})\.(\d{1,2})(?:-(\d+))?", value.strip())
    if not match:
        return None
    year, month, day, sequence = match.groups()
    return (int(year), int(month), int(day), int(sequence or 0))


def is_newer_version(latest: str | None, current: str | None = RELEASE_VERSION) -> bool:
    latest_tuple = parse_calver(latest)
    current_tuple = parse_calver(current)
    if latest_tuple is None or current_tuple is None:
        return False
    return latest_tuple > current_tuple


def check_update_status(timeout: float = 5.0) -> UpdateStatus:
    try:
        latest, url = _fetch_latest_release(timeout=timeout)
        return UpdateStatus(
            current_version=RELEASE_VERSION,
            latest_version=latest,
            update_available=is_newer_version(latest),
            checked=True,
            url=url,
        )
    except Exception as exc:  # noqa: BLE001
        return UpdateStatus(current_version=RELEASE_VERSION, checked=False, error=str(exc))


def start_update_flow() -> UpdateFlow:
    """Start the safest available update path for this install.

    Linux packages do not currently have an in-app package manager integration,
    so packaged installs return the releases URL for the UI to open. Source
    checkouts can run the repository's own update.sh after validating the root.
    """
    if sys.platform.startswith("linux"):
        source_root = _find_source_root()
        if source_root is not None:
            command = ["bash", str(source_root / "update.sh")]
            subprocess.Popen(command, cwd=str(source_root))  # noqa: S603
            return UpdateFlow(
                mode="command",
                started=True,
                message="Started the Linux source updater.",
            )
        return UpdateFlow(
            mode="release",
            started=False,
            url=RELEASES_URL,
            message="Open the latest Linux package from GitHub releases.",
        )

    return UpdateFlow(
        mode="release",
        started=False,
        url=RELEASES_URL,
        message="Open the latest release for this platform.",
    )


def _candidate_source_roots() -> list[Path]:
    roots = [
        Path.cwd(),
        Path(__file__).resolve().parents[2],
    ]
    executable = Path(sys.executable).resolve()
    roots.extend(executable.parents[:4])

    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def _find_source_root() -> Path | None:
    for root in _candidate_source_roots():
        if _is_source_root(root):
            return root
    return None


def _is_source_root(root: Path) -> bool:
    return (
        (root / "update.sh").is_file()
        and (root / "pyproject.toml").is_file()
        and (root / "src" / "dictate").is_dir()
    )


def _fetch_latest_release(*, timeout: float) -> tuple[str, str | None]:
    try:
        payload = _fetch_json(LATEST_RELEASE_URL, timeout=timeout)
        tag = str(payload.get("tag_name") or payload.get("name") or "")
        url = payload.get("html_url")
        if parse_calver(tag):
            return tag.lstrip("v"), str(url) if url else None
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        pass

    payload = _fetch_json(LATEST_TAGS_URL, timeout=timeout)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("No release tags returned.")
    tag = str(payload[0].get("name") or "")
    if not parse_calver(tag):
        raise RuntimeError("Latest tag is not a CalVer release.")
    return tag.lstrip("v"), None


def _fetch_json(url: str, *, timeout: float):  # noqa: ANN201
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Dictate update checker",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
