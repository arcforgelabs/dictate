"""Release update checks for Settings/About surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
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
    # Dictate ships the shell and engine as ONE unit at ONE version (the .deb,
    # the MS Store package, the macOS bundle). There is no separate engine/shell
    # version or staleness — they always update together.
    current_version: str
    latest_version: str | None = None
    update_available: bool = False
    checked: bool = False
    error: str | None = None
    url: str | None = None
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
        return UpdateStatus(
            current_version=RELEASE_VERSION,
            latest_version=latest,
            update_available=update_available,
            checked=True,
            url=url,
            platform=context["platform"],
            install_kind=context["install_kind"],
            phase="available" if update_available else "current",
            step="ready" if update_available else "current",
            progress=0 if update_available else 100,
            actions=_available_actions(context["install_kind"], update_available),
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

    A packaged Linux install (.deb) updates in-app and as one unit: download the
    new package from the official release, install it via ``pkexec`` (one polkit
    prompt), then the shell restarts so the new shell + engine come up together.
    Source checkouts run the repository's own update.sh after validating the root.
    Windows updates through the Microsoft Store; macOS through its bundle.
    """
    context = _update_context()
    if context["install_kind"] == "linux-package":
        return _run_linux_package_update(context)
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


DEB_ASSET_SUFFIX = "_amd64.deb"
_DOWNLOAD_TIMEOUT = 600.0


def _run_linux_package_update(context: dict[str, object]) -> UpdateFlow:
    """Download the latest .deb and install it via pkexec; the shell restarts."""
    if not shutil.which("pkexec"):
        return _missing_deps_flow(context, ["pkexec"])
    try:
        asset_url, asset_name = _find_release_asset(DEB_ASSET_SUFFIX)
    except Exception as exc:  # noqa: BLE001
        return _update_failed(
            context, "no_asset", f"Could not find a .deb in the latest release: {exc}"
        )
    try:
        deb_path = _download_file(asset_url, asset_name)
    except Exception as exc:  # noqa: BLE001
        return _update_failed(context, "download_failed", str(exc))
    try:
        result = _install_deb(deb_path)
    except Exception as exc:  # noqa: BLE001
        return _update_failed(context, "install_failed", str(exc))
    finally:
        try:
            deb_path.unlink()
        except OSError:
            pass
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or f"installer exited {result.returncode}"
        # pkexec returns 126 (dialog dismissed) / 127 (auth failed) on cancel.
        code = "cancelled" if result.returncode in (126, 127) else "install_failed"
        return _update_failed(context, code, detail)
    return UpdateFlow(
        mode="installed",
        started=True,
        platform=str(context["platform"]),
        install_kind=str(context["install_kind"]),
        phase="installed",
        step="restart",
        progress=100,
        actions=["restart"],
        commands={},
        missing_deps=[],
        message="Update installed — restarting Dictate.",
    )


def _find_release_asset(suffix: str, *, timeout: float = 10.0) -> tuple[str, str]:
    payload = _fetch_json(LATEST_RELEASE_URL, timeout=timeout)
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        raise RuntimeError("release has no downloadable assets")
    for asset in assets:
        name = str(asset.get("name") or "")
        url = asset.get("browser_download_url")
        if name.endswith(suffix) and url:
            return str(url), name
    raise RuntimeError(f"no asset ending in {suffix}")


def _download_file(url: str, name: str, *, timeout: float = _DOWNLOAD_TIMEOUT) -> Path:
    dest_dir = Path(tempfile.gettempdir()) / "dictate-update"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    request = urllib.request.Request(url, headers={"User-Agent": "Dictate updater"})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as fh:
        shutil.copyfileobj(response, fh)
    return dest


def _install_deb(deb_path: Path) -> "subprocess.CompletedProcess[str]":
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    return subprocess.run(  # noqa: S603
        ["pkexec", "apt-get", "install", "-y", str(deb_path)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _update_failed(context: dict[str, object], code: str, detail: str) -> UpdateFlow:
    return UpdateFlow(
        mode="error",
        started=False,
        platform=str(context.get("platform") or ""),
        install_kind=str(context.get("install_kind") or "manual"),
        phase="failed",
        step="update",
        progress=0,
        actions=["check", "open_release"],
        commands={"release": RELEASES_URL},
        missing_deps=[],
        message="Could not complete the update.",
        error_code=code,
        error_detail=detail,
    )


def _missing_deps_flow(context: dict[str, object], deps: list[str]) -> UpdateFlow:
    joined = ", ".join(deps)
    return UpdateFlow(
        mode="error",
        started=False,
        platform=str(context.get("platform") or ""),
        install_kind=str(context.get("install_kind") or "manual"),
        phase="failed",
        step="deps",
        progress=0,
        actions=["open_release"],
        commands={"release": RELEASES_URL},
        missing_deps=deps,
        message=f"Missing required tool: {joined}.",
        error_code="missing_deps",
        error_detail=f"Install {joined} to update in-app, or download the package manually.",
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
    return {
        "platform": platform,
        "install_kind": install_kind,
        "source_root": source_root,
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


def _available_actions(install_kind: str, has_update: bool) -> list[str]:
    actions = ["check"]
    if has_update:
        # In-app update for source checkouts and the Linux .deb; Windows (Store)
        # and macOS (bundle) still open the release page.
        if install_kind.endswith("-source") or install_kind == "linux-package":
            actions.append("update")
        else:
            actions.append("open_release")
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
