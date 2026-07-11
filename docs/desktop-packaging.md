# Desktop packaging & CI - runbook

How the desktop app (the "Quiet Console") is built, shipped, and updated -
and the non-obvious things that bit us, so the next person/agent doesn't relearn
them. Pairs with [release-versioning.md](release-versioning.md).

## Architecture

The desktop app is **two pieces that ship as one package**:

- **`ui-shell/`** - a Tauri 2 shell (Rust) that draws the frameless window + tray
  and hosts the web UI built from **`ui/`** (React/Vite). See `ui-shell/README.md`.
- **The Python engine** - the real product (STT, audio, push-to-talk, typing). It
  is **PyInstaller-frozen** (`packaging/`) into a single `dictate-engine` binary
  and embedded in the bundle as a Tauri **resource** (`bundle.resources`).

On launch the shell spawns the engine once as a headless process that **both**
dictates (`--no-tray`) and serves the control API (`DICTATE_UI_SERVER=1`,
implemented in `src/dictate/ui_server.py`). The webview talks to that server over
loopback HTTP with a bearer token written to `~/.local/share/dictate/ui-server.json`.

The desktop bundles stage the default offline resources beside the frozen
engine: Parakeet v2 int8 ONNX for regular English dictation and pyannote
Community-1 for Meeting speaker attribution. Customers should not need Hugging
Face accounts or model downloads for those bundled paths.

Hugging Face appears in the build pipeline only because pyannote Community-1 is
a gated upstream model. The build needs access to the already-approved model
once, before packaging, so it can copy the model snapshot into
`ui-shell/src-tauri/engine/models/`. Parakeet v2 int8 is public and does not
need a private token. Runtime customer installs must prefer the bundled model
paths and must not ask customers for Hugging Face credentials for the shipped
default dictation or Meeting paths.

Operator credential source: use the existing secret-management lane, such as
Bitwarden Secrets Manager materialized into GitHub Actions secrets or a
protected runner environment. The app and customer runtime must not call
Bitwarden or Hugging Face. If an internal model mirror/artifact becomes the
source of truth, update `scripts/prepare-pyannote-community-model.py` to stage
from that artifact before falling back to Hugging Face; do not reintroduce a
customer-time download.

GPU provider packages are packaging inputs, not UI choices. The default bundled
engine can run CPU Parakeet. NVIDIA builds that should exercise CUDA install the
`gpu` extra. Windows AMD validation builds install the `amd` extra, which brings
in ONNX Runtime DirectML and is verified by
`dictate doctor --stt-backend parakeet --device amd --quick`. Linux AMD
validation remains ROCm/MIGraphX-provider based and must use a runner or test
machine with an ONNX Runtime build that exposes `MIGraphXExecutionProvider` or
`ROCMExecutionProvider`.

## Build / release flow

```
scripts/build-linux-desktop.sh
  ├─ npm --prefix ui run build                 # web UI -> ui/dist
  ├─ DICTATE_ONEFILE=1 packaging/build-engine.sh  # freeze engine -> one binary
  ├─ stage engine -> ui-shell/src-tauri/engine/dictate-engine
  └─ tauri build --bundles deb
```

- **CI (`.github/workflows/ci.yml`, job `desktop-shell`)** compiles the shell and
  runs its Rust tests on every push (with a placeholder engine — no freeze).
- **Release (`.github/workflows/release.yml`, job `linux-desktop`)** runs the full
  build after the manually dispatched release workflow verifies the requested
  `v20*` tag is reachable from the default branch, then attaches the `.deb` to
  the GitHub release. RPM packaging is intentionally not part of the release lane
  because it has timed out in CI after producing the `.deb`; reintroduce it only
  after the RPM bundling path is fixed and timed.
- **Manual (`.github/workflows/desktop-bundle.yml`, `workflow_dispatch`)** builds
  the bundle and uploads artifacts + the full log — **use this to iterate on
  packaging without cutting releases.** Trigger: `gh workflow run desktop-bundle.yml`.

## Windows build / release flow

The Windows path mirrors the Linux bundle architecture, but stages
`dictate-engine.exe` and builds Tauri's Windows bundle targets:

```
scripts/build-windows-desktop.ps1
  ├─ npm --prefix ui run build
  ├─ create packaging\.build-venv-windows
  ├─ pip install -e ".[windows]" pyinstaller
  ├─ DICTATE_ONEFILE=1 pyinstaller packaging\dictate-engine.spec
  ├─ stage engine -> ui-shell\src-tauri\engine\dictate-engine.exe
  └─ tauri build --bundles msi,nsis
```

- **Release (`.github/workflows/release.yml`, job `windows-desktop`)** runs the
  full Windows build after the manually dispatched release workflow verifies the
  requested `v20*` tag is reachable from the default branch. Public stable
  Windows distribution supports Microsoft Store stable builds and direct-download
  stable/unstable builds. Direct installers are unsigned unless we later decide to pay for and
  maintain Authenticode signing.
- **Unstable (`.github/workflows/npm-unstable.yml`)** runs the same Windows
  desktop build and the Linux user encrypted-sync install smoke before moving
  the npm `unstable` dist-tag. It uploads the `.msi` and NSIS setup `.exe` as
  workflow artifacts and durable GitHub prerelease assets for the exact unstable commit.
- **Manual (`.github/workflows/windows-desktop-bundle.yml`, `workflow_dispatch`)**
  builds the Windows bundle and uploads artifacts + the full log without cutting
  a release tag. Trigger: `gh workflow run windows-desktop-bundle.yml`.
- **Manual (`.github/workflows/windows-msi-release.yml`, `workflow_dispatch`)**
  is retained as future plumbing for a paid Authenticode direct-download lane.
  It is not part of the current Windows release plan and should not block
  tester-ready or Store-ready work.
- Unsigned Windows MSI/NSIS artifacts are acceptable for early/staging testers.
  Those users will see Windows untrusted-publisher warnings and may need to
  approve the install manually. That is expected for staging builds. The stable
  public Windows path remains the Microsoft Store package tracked in
  [msstore-automation.md](msstore-automation.md).
- The Tauri shell looks for `dictate-engine.exe` on Windows and for
  `dictate-engine` elsewhere. It also reads the UI handshake from
  `%LOCALAPPDATA%\dictate`, matching `src/dictate/platform_paths.py`.
- `scripts/assert-windows-artifacts-signed.ps1` and
  `scripts/sign-windows-artifacts.ps1` exist only for the future paid
  Authenticode lane. Do not keep revisiting Windows signing configuration during
  ordinary release or staging work. We are not currently paying for that
  certificate path.

If a future revenue-backed signing lane is explicitly approved,
backfill a signed MSI onto an existing release after the signing certificate is
configured:

```bash
gh workflow run windows-msi-release.yml \
  -f release_tag=v2026.7.4 \
  -f overwrite=false
```

Use `-f overwrite=true` only when replacing a bad or superseded MSI asset on the
same immutable release tag.

## Windows Store MSIX flow

The reserved Partner Center product is `Arc Forge Dictate`
(`9P5S7747V0BP`) and its type is **MSIX or PWA app**. Tauri's built-in Windows
bundler still emits MSI/NSIS installers, so Store MSIX packaging uses
Microsoft's `winapp` CLI and a repo-owned manifest:

```
scripts/build-windows-msix-store.ps1
  ├─ run scripts\build-windows-desktop.ps1 -Bundles no-bundle
  ├─ read shared target\release\dictate-ui-shell.exe
  ├─ read shared target\release\engine\dictate-engine.exe
  ├─ stage shell + engine into the MSIX loose layout
  ├─ render packaging\msix\Package.appxmanifest.in
  ├─ winapp tool makeappx pack, or Windows SDK makeappx.exe
  └─ unpack and validate manifest identity + shell/engine payloads
```

- **Manual (`.github/workflows/windows-msix-store-bundle.yml`,
  `workflow_dispatch`)** builds `packaging/msix/out/*.msix` for Partner Center
  package validation. Trigger: `gh workflow run windows-msix-store-bundle.yml`.
- Store MSIX packaging consumes the same no-bundle Windows desktop payload that
  is used to produce the direct installer artifacts. The Store wrapper changes
  package format, identity, and manifest metadata; it does not rebuild a
  different shell/engine application stack.
- `scripts/build-windows-msix-store.ps1` prefers Microsoft's `winapp` CLI, but
  can fall back to Windows SDK `makeappx.exe` when `winapp` is not installed.
  After packing, it unpacks the MSIX and validates the Partner Center identity,
  package version, shell executable, and engine sidecar payload.
- **Manual (`.github/workflows/msstore-publish-msix.yml`, `workflow_dispatch`)**
  uses Microsoft Store Developer CLI for current-state checks, draft package
  upload, or explicit publish/commit. Use `mode=status` for read-only checks,
  `mode=draft` to upload a generated MSIX without committing, and `mode=publish`
  only after the draft should be submitted to Microsoft.
- Store publication is not triggered by GitHub release publication. After a
  release is tagged and verified, create the Store draft with `mode=draft`,
  review it in Partner Center, then use `mode=publish` when it is ready for
  Microsoft certification.
- Local VM evidence: `scripts/windows-vm-smoke.sh --vm win11-dev --mode msix
  --timeout 2400 --keep-guest-workdir` passed on 2026-07-05 after the current
  Parakeet-first installer/default, Meeting readiness, benchmark, Windows AMD
  DirectML, AMD evidence-import, and segment-aware UI changes. It produced
  `C:\Users\Public\dictate-vm-smoke\source\packaging\msix\out\ArcForgeDictate_2026.7.4.0_x64.msix`,
  smoke-tested the frozen engine binary, and validated the unpacked manifest,
  shell executable, and engine sidecar.
- Current install smoke evidence: `scripts/windows-vm-smoke.sh --vm win11-dev
  --mode install --timeout 1800 --keep-guest-workdir` passed on 2026-07-05
  after resetting the guest Dictate app-data directory, seeding a fresh config,
  compiling Python sources, running 314 focused Windows tests with 16 skips,
  verifying
  `dictate 2026.7.4`, and confirming default `dictate doctor --quick
  --type-backend pynput` reports Parakeet v2.
- Linux user encrypted-sync smoke: `scripts/linux-user-sync-smoke.sh` runs
  through `install.sh` in an isolated `$HOME`, starts the installed UI control
  server with a fake Pro gateway, opts into encrypted sync, verifies an offline
  outbox drains after the gateway returns, and asserts plaintext dictated text
  is absent from cloud sync records. CI runs this as the
  `Linux user install sync smoke` job.
- Current lifecycle smoke evidence: `scripts/windows-vm-smoke.sh --vm
  win11-dev --mode lifecycle --timeout 2400 --keep-guest-workdir` passed on
  2026-07-05 after the same fresh-config install path, update, default Parakeet
  doctor check, and uninstall.
- Windows AMD DirectML smoke evidence: `scripts/windows-vm-smoke.sh --vm
  win11-dev --mode amd --timeout 1800 --keep-guest-workdir` passed on
  2026-07-05 after the Parakeet-first installer/default and fresh-config smoke
  changes. It resets guest Dictate app data, seeds a fresh config, runs 196
  focused Windows tests with 15 skips, installs the `amd` extra, verifies
  `DmlExecutionProvider`, and runs `dictate doctor --stt-backend parakeet
  --device amd --quick --type-backend pynput` in the guest. This checks
  DirectML packaging/readiness, not Radeon performance.
- The manifest identity is pinned to Partner Center:
  `ArcForgeLabs.ArcForgeDictate` and
  `CN=56989B1A-E9FD-45E0-827B-FDB65D3C9B3C`.
- The MSIX package stages the frozen engine next to the shell executable under
  `engine\`; the Tauri shell checks both Tauri's resource directory and the
  executable directory for that sidecar.
- Microsoft Store distribution should sign the final accepted package. Any local
  MSIX signing certificate is for internal install testing only.
- If this MSIX path fails Partner Center package validation, the fallback is to
  create a separate Partner Center **EXE or MSI app** product and submit the
  signed Tauri installer through Microsoft's MSI/EXE Store flow.

## Gotchas (the expensive lessons)

### Freeze the engine **onefile**, not onedir
A PyInstaller **onedir** engine ships ~1,200 libs in `_internal/`. A **onefile**
freeze puts a single self-extracting ELF in the package, which keeps the Linux
desktop artifact simpler and avoids fragile dependency walking during bundling.
We use onefile everywhere (set in `build-linux-desktop.sh`;
`dictate-engine.spec` honours `DICTATE_ONEFILE`). Cost: ~1-2 s extraction at
launch - fine for a tray app.

### Tauri icons must be RGBA PNG
`tauri::generate_context!` panics at compile time with `icon ... is not RGBA` if
any configured icon isn't RGBA. `assets/dictate.png` is mode `LA` (grey+alpha);
regenerate `ui-shell/src-tauri/icons/*.png` as RGBA (Pillow: `.convert("RGBA")`).

### Keep optional Linux formats out of the release gate until timed
The public release workflow currently publishes the `.deb` only. RPM/AppImage
experiments belong in manual bundle workflows until they are reliable and timed;
an optional package format must not sink the primary GitHub release.

### Release pipeline must be resilient
- **npm publish is best-effort.** It used to run before `gh release create` in the
  same `bash -e` step, so an npm error (the `@arcforgelabs` scope/token not
  configured) aborted the whole job and skipped the GitHub release + installers.
  It now warns and continues. (See release-versioning.md for the token setup.)
- **`gh release create` is idempotent** — `upload --clobber` if the release exists,
  so re-running after a bundle fix doesn't fail on a duplicate.

### Windows CI is part of the matrix — avoid POSIX-isms
- `strftime("%-I"/"%-M")`: the `%-` pad flag is glibc-only and raises
  `ValueError: Invalid format string` on Windows. Build clock strings manually.
- `str(Path("/a/b"))` is `\a\b` on Windows; test assertions must compare against
  `str(Path(...))`, not hard-coded forward-slash strings.
- Tests run with stdlib **unittest** (`python -m unittest discover -s tests`), not
  pytest.

### Version bump is scripted
Use `python scripts/sync_release_version.py X` to update package metadata,
hosted installer pins, Tauri versions, and the MSI-safe WiX version from one
CalVer value. Use `--date YYYY-MM-DD --sequence N` to generate the version from
the release date instead of passing `X` directly. **Do not** touch the
parse/compare fixtures in `tests/test_update_status.py` (they use old versions as
generic logic examples). `python scripts/sync_release_version.py X --check` and
`python scripts/release_check.py --tag vX` must both pass.

### You can't build the Tauri bundle in the dev sandbox
The design/dev sandbox has Node + Python (so `ui/`, the freeze, and the Python
suites are fully buildable/testable) but **no Rust/cargo, no `webkit2gtk-4.1-dev`,
`static.crates.io` is firewalled, and sudo needs a password.** So: verify the
PyInstaller freeze locally (it needs none of those), but iterate the Tauri build
**on CI** via `desktop-bundle.yml`. Don't burn time trying to `cargo build` locally.

## Install, update, conflicts

- **Default Linux release install is per-user**. `./install.sh` installs into
  `~/.local/share/dictate`, links commands into `~/.local/bin`, and creates a
  per-user desktop launcher/autostart entry. `./update.sh` stays on this channel
  by default and does not require sudo.
- **System Linux package install is explicit**. `./install.sh --system` or
  `./update.sh --system` installs a local `.deb` into `/usr` through `pkexec` or
  `sudo`. Use this channel for managed machine-wide installs, not as the default
  developer/user update path.
- **The user install and the package both ship a daemon** and would fight over the
  push-to-talk key. `install.sh` warns when a package is installed;
  `uninstall.sh` stops a running source/user daemon and removes the
  `dictate-ui-server` symlink + logs, **preserving `~/.config/dictate` and
  history by default** (`--remove-user-data` to wipe).
- Same-version reinstall (e.g. swapping an onedir `.deb` for a onefile one with the
  same version string) needs `sudo apt install --reinstall ./<file>.deb` — apt
  skips an equal version otherwise. Download the asset first; `apt install
  ./bare-name.deb` fails with "Unsupported file" if the path doesn't exist.

## Open / known follow-ups

- **npm publishing**: the `arcforgelabs` org exists, but CI needs an **automation
  token** in the `NPM_TOKEN` secret. Until set, npm publish just warns.
- **Autostart**: on its first run the packaged engine self-registers both the
  app-menu launcher and a per-user login autostart entry
  (`~/.config/autostart/dictate.desktop`, `Exec=dictate-ui-shell`), gated by a
  `~/.local/share/dictate/.desktop-integrated` marker so it runs once and never
  overrides a user who later disables startup (`dictate config set-startup off`).
  `dictate doctor` flags a launcher/startup entry whose `Exec` target is missing
  (e.g. a stale pip-era `~/.local/bin/dictate` after migrating to the package),
  and `dictate doctor --fix` repairs it.
