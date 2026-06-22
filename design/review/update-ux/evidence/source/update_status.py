"""Release update checks for Settings/About surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
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
    platform: str = ""
    install_kind: str = "manual"
    engine: dict[str, str | bool | None] | None = None
    shell: dict[str, str | bool | None] | None = None
    shell_stale: bool = False
    phase: str = "idle"
    step: str | None = None
    progress: int | None = None
    actions: list[str] | None = None
    commands: dict[str, str] | None = None
    missing_deps: list[str] | None = None
    error_code: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class UpdateFlow:
    mode: str
    started: bool
    url: str | None = None
    message: str | None = None
    platform: str = ""
    install_kind: str = "manual"
    phase: str = "idle"
    step: str | None = None
    progress: int | None = None
    actions: list[str] | None = None
    commands: dict[str, str] | None = None
    missing_deps: list[str] | None = None
    error_code: str | None = None
    error_detail: str | None = None


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
    context = _update_context()
    try:
        latest, url = _fetch_latest_release(timeout=timeout)
        update_available = is_newer_version(latest)
        shell_current = context["shell_current"] or RELEASE_VERSION
        shell_stale = is_newer_version(latest, shell_current) if latest else False
        return UpdateStatus(
            current_version=RELEASE_VERSION,
            latest_version=latest,
            update_available=update_available,
            checked=True,
            url=url,
            platform=context["platform"],
            install_kind=context["install_kind"],
            engine=_component("engine", RELEASE_VERSION, latest, context["engine_path"], update_available),
            shell=_component("shell", shell_current, latest, context["shell_path"], shell_stale),
            shell_stale=shell_stale,
            phase="available" if update_available or shell_stale else "current",
            step="ready" if update_available or shell_stale else "current",
            progress=100 if not update_available and not shell_stale else 0,
            actions=_available_actions(context["install_kind"], update_available or shell_stale),
            commands=_commands_for_context(context),
            missing_deps=[],
        )
    except Exception as exc:  # noqa: BLE001
        return UpdateStatus(
            current_version=RELEASE_VERSION,
            checked=False,
            error=str(exc),
            platform=context["platform"],
            install_kind=context["install_kind"],
            engine=_component("engine", RELEASE_VERSION, None, context["engine_path"], False),
            shell=_component(
                "shell",
                context["shell_current"] or RELEASE_VERSION,
                None,
                context["shell_path"],
                False,
            ),
            phase="failed",
            step="check",
            progress=0,
            actions=["check", "open_release"],
            commands=_commands_for_context(context),
            missing_deps=[],
            error_code="check_failed",
            error_detail=str(exc),
        )


def start_update_flow() -> UpdateFlow:
    """Start the safest available update path for this install.

    Linux packages do not currently have an in-app package manager integration,
    so packaged installs return the releases URL for the UI to open. Source
    checkouts can run the repository's own update.sh after validating the root.
    """
    context = _update_context()
    if context["install_kind"] == "linux-source":
        source_root = context["source_root"]
        if source_root is not None:
            command = ["bash", str(source_root / "update.sh")]
            subprocess.Popen(command, cwd=str(source_root))  # noqa: S603
            return UpdateFlow(
                mode="command",
                started=True,
                platform=context["platform"],
                install_kind=context["install_kind"],
                phase="working",
                step="update",
                progress=0,
                actions=["restart"],
                commands={"update": " ".join(command)},
                missing_deps=[],
                message="Started the Linux source updater.",
            )
    if context["install_kind"] == "windows-source":
        source_root = context["source_root"]
        if source_root is not None:
            command = _windows_update_command(source_root)
            subprocess.Popen(command, cwd=str(source_root))  # noqa: S603
            return UpdateFlow(
                mode="command",
                started=True,
                platform=context["platform"],
                install_kind=context["install_kind"],
                phase="working",
                step="update",
                progress=0,
                actions=["restart"],
                commands={"update": " ".join(command)},
                missing_deps=[],
                message="Started the Windows source updater.",
            )

    return UpdateFlow(
        mode="release",
        started=False,
        url=RELEASES_URL,
        platform=context["platform"],
        install_kind=context["install_kind"],
        phase="manual",
        step="release",
        progress=0,
        actions=["open_release"],
        commands=_commands_for_context(context),
        missing_deps=[],
        message=_manual_update_message(context),
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


def _platform_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return sys.platform


def _update_context() -> dict[str, object]:
    platform = _platform_key()
    source_root = _find_source_root()
    install_kind = _install_kind(platform, source_root)
    shell_path = os.environ.get("DICTATE_SHELL_PATH") or _find_shell_binary()
    shell_current = os.environ.get("DICTATE_SHELL_VERSION") or RELEASE_VERSION
    return {
        "platform": platform,
        "install_kind": install_kind,
        "source_root": source_root,
        "engine_path": str(Path(sys.executable).resolve()),
        "shell_path": shell_path,
        "shell_current": shell_current,
    }


def _install_kind(platform: str, source_root: Path | None) -> str:
    if source_root is not None:
        return f"{platform}-source" if platform in {"linux", "windows"} else "source"
    if platform == "linux":
        return "linux-package"
    if platform == "windows":
        return "windows-package"
    if platform == "mac":
        return "mac-package"
    return "manual"


def _find_shell_binary() -> str | None:
    name = "dictate-ui-shell.exe" if sys.platform.startswith("win") else "dictate-ui-shell"
    if sys.platform.startswith("win") and os.name != "nt":
        return None
    found = shutil.which(name)
    return found or None


def _component(
    name: str,
    current: str | None,
    latest: str | None,
    path: object,
    stale: bool,
) -> dict[str, str | bool | None]:
    return {
        "name": name,
        "current": current,
        "latest": latest,
        "path": str(path) if path else None,
        "stale": bool(stale),
    }


def _available_actions(install_kind: str, has_update: bool) -> list[str]:
    actions = ["check"]
    if has_update:
        actions.append("update" if install_kind.endswith("-source") else "open_release")
    actions.append("open_docs")
    return actions


def _commands_for_context(context: dict[str, object]) -> dict[str, str]:
    source_root = context.get("source_root")
    install_kind = str(context.get("install_kind") or "manual")
    if install_kind == "linux-source" and isinstance(source_root, Path):
        return {"update": f"bash {source_root / 'update.sh'}"}
    if install_kind == "windows-source" and isinstance(source_root, Path):
        return {
            "update": (
                "powershell -NoProfile -ExecutionPolicy Bypass -File "
                f'"{source_root / "update-windows.ps1"}"'
            )
        }
    return {"release": RELEASES_URL}


def _manual_update_message(context: dict[str, object]) -> str:
    install_kind = str(context.get("install_kind") or "manual")
    if install_kind == "linux-package":
        return "Open the latest Linux package from GitHub releases."
    if install_kind == "windows-package":
        return "Open the latest signed Windows installer from GitHub releases."
    if install_kind == "mac-package":
        return "Open the latest macOS package from GitHub releases."
    return "Open the latest release for this platform."


def _windows_update_command(source_root: Path) -> list[str]:
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(source_root / "update-windows.ps1"),
    ]


def _find_source_root() -> Path | None:
    for root in _candidate_source_roots():
        if _is_source_root(root):
            return root
    return None


def _is_source_root(root: Path) -> bool:
    update_script = "update-windows.ps1" if sys.platform.startswith("win") else "update.sh"
    return (
        (root / update_script).is_file()
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
