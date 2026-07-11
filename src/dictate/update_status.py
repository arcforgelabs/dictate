"""Release update checks for Settings/About surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
from types import SimpleNamespace
import subprocess
import tempfile
import sys
import urllib.error
import urllib.request

from dictate.config import load_config
from dictate.version import RELEASE_VERSION

LATEST_RELEASE_URL = "https://api.github.com/repos/arcforgelabs/dictate/releases/latest"
LATEST_TAGS_URL = "https://api.github.com/repos/arcforgelabs/dictate/tags?per_page=1"
NPM_PACKAGE_URL = "https://registry.npmjs.org/@arcforgelabs%2fdictate"
RELEASES_URL = "https://github.com/arcforgelabs/dictate/releases"
DOCUMENTATION_URL = "https://github.com/arcforgelabs/dictate#readme"
TERMS_URL = "https://arcforge.au/terms"
STORE_UPDATES_URL = "ms-windows-store://downloadsandupdates"
DISTRIBUTION_MARKER = "dictate-distribution.json"


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


def _parse_app_version(value: str | None) -> tuple[tuple[int, int, int, int], tuple[int | str, ...]] | None:
    if not value:
        return None
    text = value.strip()
    match = re.fullmatch(
        r"v?(\d{4})\.(\d{1,2})\.(\d{1,2})(?:-(?:(\d+)|([0-9A-Za-z][0-9A-Za-z.-]*)))?",
        text,
    )
    if not match:
        return None
    year, month, day, sequence, prerelease = match.groups()
    base = (int(year), int(month), int(day), int(sequence or 0))
    parts: list[int | str] = []
    if prerelease:
        for part in prerelease.split("."):
            parts.append(int(part) if part.isdigit() else part.lower())
    return base, tuple(parts)


def _compare_prerelease(left: tuple[int | str, ...], right: tuple[int | str, ...]) -> int:
    if left == right:
        return 0
    # Dictate's opt-in unstable lane intentionally treats same-base prerelease
    # builds as newer than the stable base package, because users have selected
    # the moving test channel.
    if left and not right:
        return 1
    if right and not left:
        return -1
    for l_part, r_part in zip(left, right):
        if l_part == r_part:
            continue
        if isinstance(l_part, int) and isinstance(r_part, int):
            return 1 if l_part > r_part else -1
        if isinstance(l_part, int):
            return -1
        if isinstance(r_part, int):
            return 1
        return 1 if l_part > r_part else -1
    return 1 if len(left) > len(right) else -1


def is_newer_version(latest: str | None, current: str | None = RELEASE_VERSION) -> bool:
    latest_tuple = _parse_app_version(latest)
    current_tuple = _parse_app_version(current)
    if latest_tuple is None or current_tuple is None:
        return False
    latest_base, latest_prerelease = latest_tuple
    current_base, current_prerelease = current_tuple
    if latest_base != current_base:
        return latest_base > current_base
    return _compare_prerelease(latest_prerelease, current_prerelease) > 0


def check_update_status(timeout: float = 5.0) -> UpdateStatus:
    context = _update_context()
    cfg = context["config"]
    if context["install_kind"] == "windows-store":
        current_version = context.get("package_version") or RELEASE_VERSION
    else:
        current_version = cfg.installed_package_version or context.get("package_version") or RELEASE_VERSION
    if context["install_kind"] == "windows-store":
        return UpdateStatus(
            current_version=str(current_version), checked=True, platform="windows",
            install_kind="windows-store", phase="store", step="store", progress=100,
            actions=["check", "open_store"], commands={"store": STORE_UPDATES_URL}, missing_deps=[],
            url=STORE_UPDATES_URL,
        )
    try:
        latest, url = _fetch_latest_version(_update_channel_for_context(context), timeout=timeout)
        update_available = is_newer_version(latest, current_version)
        return UpdateStatus(
            current_version=current_version,
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
            current_version=current_version,
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

    User Linux installs update without elevation via the npm bootstrap package.
    System Linux installs (.deb) download the new package from the official
    release and install it via ``pkexec`` (one polkit prompt). Source checkouts
    run the repository's own update.sh after validating the root.
    Windows updates through the Microsoft Store; macOS through its bundle.
    """
    context = _update_context()
    if context["install_kind"] == "linux-user":
        return _run_linux_user_update(context)
    if context["install_kind"] == "linux-package":
        return _run_linux_package_update(context)
    if context["install_kind"] == "windows-direct":
        return _run_windows_direct_update(context)
    if context["install_kind"] == "windows-store":
        return _open_windows_store_updates(context)
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
                actions=["check"],
                commands={"update": " ".join(command)},
                missing_deps=[],
                message="Started the Linux source updater. Reopen Dictate after it finishes.",
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
                actions=["check"],
                commands={"update": " ".join(command)},
                missing_deps=[],
                message="Started the Windows source updater. Reopen Dictate after it finishes.",
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
NPM_PACKAGE_NAME = "@arcforgelabs/dictate"
WINDOWS_INSTALLER_SUFFIX = "-setup.exe"


def _run_linux_user_update(context: dict[str, object]) -> UpdateFlow:
    """Start the no-sudo per-user updater."""
    npx = _find_npx()
    if not npx:
        return _missing_deps_flow(context, ["npx"])
    command = [npx, "-y", _npm_package_spec(), "update", "--user"]
    subprocess.Popen(command, env=_subprocess_env_for_tool(npx))  # noqa: S603
    return UpdateFlow(
        mode="command",
        started=True,
        platform=str(context["platform"]),
        install_kind=str(context["install_kind"]),
        phase="working",
        step="update",
        progress=0,
        actions=["check"],
        commands={"update": " ".join(command)},
        missing_deps=[],
        message="Started the Linux user updater. Reopen Dictate after it finishes.",
    )


def _find_npx() -> str | None:
    found = shutil.which("npx")
    if found:
        return found
    home = Path.home()
    candidates: list[Path] = [
        home / ".local" / "bin" / "npx",
        home / ".npm-global" / "bin" / "npx",
        home / ".volta" / "bin" / "npx",
        home / ".fnm" / "aliases" / "default" / "bin" / "npx",
        Path("/usr/local/bin/npx"),
        Path("/usr/bin/npx"),
    ]
    candidates.extend(home.glob(".nvm/versions/node/*/bin/npx"))
    existing = [path for path in candidates if path.is_file() and os.access(path, os.X_OK)]
    if not existing:
        return None
    existing.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return str(existing[0])


def _subprocess_env_for_tool(tool_path: str) -> dict[str, str]:
    env = dict(os.environ)
    tool_dir = str(Path(tool_path).parent)
    current_path = env.get("PATH", "")
    if tool_dir and tool_dir not in current_path.split(os.pathsep):
        env["PATH"] = tool_dir + (os.pathsep + current_path if current_path else "")
    return env


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


def _run_windows_direct_update(context: dict[str, object]) -> UpdateFlow:
    """Download and launch the installer published for the selected channel."""
    cfg = context["config"]
    current_version = (
        getattr(cfg, "installed_package_version", None)
        or context.get("package_version")
        or RELEASE_VERSION
    )
    try:
        latest, _ = _fetch_latest_version(_update_channel_for_context(context), timeout=10.0)
        if not is_newer_version(latest, current_version):
            return UpdateFlow(
                mode="current", started=False, platform="windows", install_kind="windows-direct",
                phase="current", step="current", progress=100, actions=["check"],
                commands=_commands_for_context(context), missing_deps=[], message="Dictate is up to date.",
            )
        asset_url, asset_name = _find_release_asset(
            WINDOWS_INSTALLER_SUFFIX,
            release_tag=f"v{latest}",
        )
        installer = _download_file(asset_url, asset_name)
        subprocess.Popen([str(installer), "/S", "/UPDATE"])  # noqa: S603
    except Exception as exc:  # noqa: BLE001
        return _update_failed(context, "windows_update_failed", str(exc))
    return UpdateFlow(
        mode="installer", started=True, platform="windows", install_kind="windows-direct",
        phase="working", step="update", progress=0, actions=["check"],
        commands=_commands_for_context(context), missing_deps=[],
        message="Started the Dictate installer. The app will restart when the update is complete.",
    )


def _open_windows_store_updates(context: dict[str, object]) -> UpdateFlow:
    """Hand Store-packaged builds back to the Microsoft Store update service."""
    try:
        os.startfile(STORE_UPDATES_URL)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return _update_failed(context, "store_open_failed", str(exc))
    return UpdateFlow(
        mode="store", started=True, url=STORE_UPDATES_URL, platform="windows",
        install_kind="windows-store", phase="working", step="store", progress=0,
        actions=["open_store"], commands={"store": STORE_UPDATES_URL}, missing_deps=[],
        message="Opened Microsoft Store updates. Store builds receive stable releases only.",
    )


def _find_release_asset(
    suffix: str, *, timeout: float = 10.0, release_tag: str | None = None
) -> tuple[str, str]:
    url = (
        f"https://api.github.com/repos/arcforgelabs/dictate/releases/tags/{release_tag}"
        if release_tag else LATEST_RELEASE_URL
    )
    payload = _fetch_json(url, timeout=timeout)
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


def _windows_distribution() -> str:
    """Return the updater ecosystem embedded by the Windows packager."""
    configured = os.environ.get("DICTATE_DISTRIBUTION", "").strip().lower()
    if configured in {"direct", "store"}:
        return configured
    executable = Path(sys.executable).resolve()
    candidates = [executable.parent / DISTRIBUTION_MARKER, executable.parent.parent / DISTRIBUTION_MARKER]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / DISTRIBUTION_MARKER)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        distribution = str(payload.get("distribution") or "").strip().lower()
        if distribution in {"direct", "store"}:
            return distribution
    # Existing MSI/NSIS installs predate the marker and belong to the direct lane.
    return "direct"


def _windows_distribution_metadata() -> dict[str, str]:
    executable = Path(sys.executable).resolve()
    candidates = [executable.parent / DISTRIBUTION_MARKER, executable.parent.parent / DISTRIBUTION_MARKER]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / DISTRIBUTION_MARKER)
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            return {str(key): str(value) for key, value in payload.items()}
    return {}


def _update_context() -> dict[str, object]:
    platform = _platform_key()
    source_root = _find_source_root()
    install_kind = _install_kind(platform, source_root)
    try:
        config = load_config()
    except Exception:  # noqa: BLE001
        config = SimpleNamespace(update_channel=None, installed_package_version=None)
    metadata = _windows_distribution_metadata() if platform == "windows" else {}
    return {
        "platform": platform,
        "install_kind": install_kind,
        "source_root": source_root,
        "config": config,
        "package_version": metadata.get("packageVersion"),
    }


def _install_kind(platform: str, source_root: Path | None) -> str:
    if platform == "linux":
        if _is_linux_user_install():
            return "linux-user"
        if source_root is not None:
            return "linux-source"
        return "linux-package"
    if source_root is not None:
        return f"{platform}-source" if platform in {"windows"} else "source"
    if platform == "windows":
        distribution = _windows_distribution()
        return "windows-store" if distribution == "store" else "windows-direct"
    if platform == "mac":
        return "mac-package"
    return "manual"


def _available_actions(install_kind: str, has_update: bool) -> list[str]:
    actions = ["check"]
    if has_update:
        # Direct/source installs update in-app. Store builds stay in their
        # platform ecosystem; other bundles open their release surface.
        if install_kind.endswith("-source") or install_kind in {"linux-user", "linux-package", "windows-direct"}:
            actions.append("update")
        elif install_kind == "windows-store":
            actions.append("open_store")
        else:
            actions.append("open_release")
    actions.append("open_docs")
    return actions


def _commands_for_context(context: dict[str, object]) -> dict[str, str]:
    source_root = context.get("source_root")
    install_kind = str(context.get("install_kind") or "manual")
    if install_kind == "linux-source" and isinstance(source_root, Path):
        return {"update": f"bash {source_root / 'update.sh'}"}
    if install_kind == "linux-user":
        return {"update": f"npx -y {_npm_package_spec()} update --user"}
    if install_kind == "linux-package":
        return {"update": "download latest .deb and install with pkexec/apt"}
    if install_kind == "windows-source" and isinstance(source_root, Path):
        return {
            "update": (
                "powershell -NoProfile -ExecutionPolicy Bypass -File "
                f'"{source_root / "update-windows.ps1"}"'
            )
        }
    if install_kind == "windows-direct":
        return {"update": "download and run the selected channel's Dictate setup.exe"}
    if install_kind == "windows-store":
        return {"store": STORE_UPDATES_URL}
    return {"release": RELEASES_URL}


def _manual_update_message(context: dict[str, object]) -> str:
    install_kind = str(context.get("install_kind") or "manual")
    if install_kind == "linux-package":
        return "Open the latest Linux system package from GitHub releases."
    if install_kind == "linux-user":
        return "Run the Linux user updater."
    if install_kind == "windows-direct":
        return "Download and run the latest Dictate installer for this channel."
    if install_kind == "windows-store":
        return "Open Microsoft Store updates. Store installs receive stable releases only."
    if install_kind == "mac-package":
        return "Open the latest macOS package from GitHub releases."
    return "Open the latest release for this platform."


def _npm_update_channel() -> str:
    try:
        configured = load_config().update_channel
    except Exception:  # noqa: BLE001
        configured = None
    return _resolve_update_channel(configured)


def _update_channel_for_context(context: dict[str, object]) -> str:
    if context.get("install_kind") == "windows-store":
        return "stable"
    configured = getattr(context.get("config"), "update_channel", None)
    channel = _normalize_update_channel(configured)
    if channel:
        return channel
    install_kind = str(context.get("install_kind") or "")
    if install_kind.endswith("-source"):
        return "unstable"
    return _resolve_update_channel(None)


def _resolve_update_channel(configured: str | None) -> str:
    channel = _normalize_update_channel(configured)
    if channel:
        return channel
    channel = os.environ.get("DICTATE_UPDATE_CHANNEL", "stable").strip() or "stable"
    channel = "stable" if channel == "latest" else channel
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}", channel):
        return "stable"
    return channel


def _npm_package_spec() -> str:
    return f"{NPM_PACKAGE_NAME}@{npm_dist_tag()}"


def npm_dist_tag() -> str:
    """Return the npm dist-tag for the configured app update channel."""
    channel = _npm_update_channel()
    return "latest" if channel == "stable" else channel


def _normalize_update_channel(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    channel = value.strip().lower()
    if channel == "latest":
        return "stable"
    if channel in {"stable", "unstable"}:
        return channel
    return None


def _fetch_latest_version(configured_channel: str | None, *, timeout: float) -> tuple[str, str | None]:
    channel = _resolve_update_channel(configured_channel)
    if channel == "unstable":
        return _fetch_npm_dist_tag("unstable", timeout=timeout)
    return _fetch_latest_release(timeout=timeout)


def _fetch_npm_dist_tag(tag: str, *, timeout: float) -> tuple[str, str | None]:
    payload = _fetch_json(NPM_PACKAGE_URL, timeout=timeout)
    if not isinstance(payload, dict):
        raise RuntimeError("npm registry returned an invalid package payload")
    dist_tags = payload.get("dist-tags")
    if not isinstance(dist_tags, dict):
        raise RuntimeError("npm registry returned no dist-tags")
    version = dist_tags.get(tag)
    if not isinstance(version, str) or not _parse_app_version(version):
        raise RuntimeError(f"npm dist-tag {tag!r} is not a Dictate app version")
    return version, f"https://www.npmjs.com/package/{NPM_PACKAGE_NAME}/v/{version}"


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


def _is_linux_user_install() -> bool:
    install_root = Path.home() / ".local" / "share" / "dictate"
    try:
        executable = Path(sys.executable).resolve()
    except OSError:
        executable = Path(sys.executable)
    if install_root in executable.parents:
        return True

    user_bin = Path.home() / ".local" / "bin" / "dictate"
    if user_bin.is_symlink():
        try:
            return install_root in user_bin.resolve().parents
        except OSError:
            return False
    return False


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
