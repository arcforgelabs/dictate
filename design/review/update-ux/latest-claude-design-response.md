# Claude Design Watch Result

Status: complete
Captured: 2026-06-19T02:49:59.790Z
URL: https://claude.ai/design/p/2309408a-2350-4da0-bb4c-c03c7cfee48a?file=dictate-app%2FDictate+Settings.html

---

sName="advanced-update">
          <summary>Advanced — update from a terminal</summary>
          <div className="command-row">
            <code>{u.commands?.update || u.commands?.release || "No local command available for this install."}</code>
            {(u.commands?.update || u.commands?.release) && <button className="btn sm" onClick={copyCommand}>Copy</button>}
          </div>
        </details>
      </div>
    </div>
  );
}

function VersionRow({ label, path, current, latest, stale }) {
  return (
    <div className="version-row">
      <div>
        <div className="lbl">{label}</div>
        <div className="help">{path || "Not detected"}</div>
      </div>
      <div className="version-values">
        <Chip live={!stale}>{current || "unknown"}</Chip>
        {stale && latest ? <><Icon name="chev" size={14} style={{ color: "var(--subtle)" }} /><Chip>{latest}</Chip></> : null}
      </div>
    </div>
  );
}

function phaseTitle(phase, manual) {
  if (phase === "checking") return "Checking for updates";
  if (phase === "working") return manual ? "Opening the latest release" : "Updating the app";
  if (phase === "restart") return "Restart to finish";
  if (phase === "current") return "Everything is current";
  return manual ? "Update available" : "Update the app";
}

function phaseCopy(phase, installKind, latest, current) {
  if (phase === "checking") return "Looking for the latest Dictate release and comparing the engine with this app window.";
  if (phase === "working") return "Dictate has started the safest updater available for this install.";
  if (phase === "restart") return `The new v${latest} app window is installed. Restart Dictate to switch over; your settings and history are kept.`;
  if (phase === "current") return "The engine and app window are already aligned.";
  if (installKind.includes("windows") && !installKind.endsWith("-source")) return "Download and run the latest signed Windows installer. Dictate does not have an in-app Tauri updater wired yet.";
  if (installKind.includes("linux") && !installKind.endsWith("-source")) return "Open the latest Linux package, then install it with your package manager or replace the AppImage.";
  return `Brings this window from v${current || "old"} to v${latest}.`;
}

function failureTitle(u, installKind) {
  if (u.errorCode === "build_deps_missing" || installKind === "linux-source") return "Couldn't rebuild the app window";
  if (u.errorCode === "webview2_missing") return "Microsoft Edge WebView2 Runtime is required";
  return "Could not update Dictate";
}

function failureCopy(u, installKind) {
  if (u.errorCode === "build_deps_missing" || installKind === "linux-source") return "The engine updated fine, but building the desktop window needs system packages that are not installed.";
  if (u.errorCode === "webview2_missing") return "Install the WebView2 Runtime, then run the Dictate installer again.";
  return u.errorDetail || u.error || "Try again, or open the latest release and install it manual
```

src/dictate/ui_server.py — emitted update status fields:
```python
def get_update_status(self) -> dict[str, Any]:
        status = self.check_update_status()
        return {
            "currentVersion": status.current_version,
            "latestVersion": status.latest_version,
            "updateAvailable": status.update_available,
            "checked": status.checked,
            "error": status.error,
            "url": status.url,
            "platform": status.platform,
            "installKind": status.install_kind,
            "engine": status.engine,
            "shell": status.shell,
            "shellStale": status.shell_stale,
            "phase": status.phase,
            "step": status.step,
            "progress": status.progress,
            "actions": status.actions or [],
            "commands": status.commands or {},
            "missingDeps": status.missing_deps or [],
            "errorCode": status.error_code,
            "errorDetail": status.error_detail,
        }

    def start_update(self) -> dict[str, Any]:
        try:
            flow = self.start_update_flow()
        except Exception as exc:  # noqa: BLE001
            raise ApiError(500, f"could not start update: {exc}") from exc
        return {
            "mode": flow.mode,
            "started": flow.started,
            "url": flow.url,
            "message": flow.message,
            "platform": flow.platform,
            "installKind": flow.install_kind,
            "phase": flow.phase,
            "step": flow.step,
            "progress": flow.progress,
            "actions": flow.actions or [],
            "commands": flow.commands or {},
            "missingDeps": flow.missing_deps or [],
            "errorCode": flow.error_code,
            "errorDetail": flow.error_detail,
        }

    @staticmethod
    def _safe(fn: Callable[[], Any], default: Any) -> Any:
        try:
         
```

src/dictate/update_status.py — install-kind branching:
```python
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



```

The screenshot evidence files are under design/review/update-ux/evidence/*.png and text captures are adjacent. Please now provide FINAL REVIEW: with P0-P3 findings, or say no P0-P2 found if clean.

Evidence landed in-project. Let me inspect the screenshots and text captures.

Listing files ×3
Listed files in evidence
Listed files in design
Dictate Design System




Opus 4.8
Dictate Settings
Mark up
Comments
Edit
Hide tweaks
100%
Present
Share
S
