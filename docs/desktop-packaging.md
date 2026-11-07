# Linux desktop packaging and CI

Dictate supports Linux local dictation. There is no official deployment or
automated release publisher. Use the maintained local scripts; no business
platform, broker, private runner or publishing credential is needed.

## Source install

On Ubuntu run `./install-ubuntu.sh` from a trusted checkout. The generic
`./install.sh` uses a per-user virtual environment and can install without
building the UI via `--no-ui`. Model preparation downloads the public local
Parakeet model; transcription itself is offline. See script `--help` for
flags before opting out of checks or model preparation.

## Local native package

`scripts/build-linux-desktop.sh` reuses the existing Tauri/PyInstaller build:

```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev \
  libayatana-appindicator3-dev librsvg2-dev build-essential curl wget file \
  libssl-dev libxdo-dev python3-dev portaudio19-dev rpm
DICTATE_BUNDLES=deb ./scripts/build-linux-desktop.sh
```

Install Rust/Cargo and npm first. The builder can also produce RPM/AppImage
artifacts; the native packages use an onedir engine, while AppImage uses
onefile. Build output is under `ui-shell/src-tauri/target/release/bundle/`.
No GitHub release or Store submission occurs when this local script runs.

## Source checks

CI uses GitHub-hosted Ubuntu runners for Python 3.11/3.12 tests, real X11 and
Wayland clipboard checks, UI tests/build/server smoke, Rust shell build/tests,
and Python/npm package validation. Secret scanning and the path-scoped offline
privacy proof remain. There are no Windows jobs or self-hosted runner gates.

The manual `desktop-bundle.yml` workflow retains the existing Linux builder,
checks that removed meeting runtimes are absent and measures a frozen-engine
cold start. It uploads temporary CI artifacts/logs only. A placeholder engine
in source CI proves shell compilation, not the packaged engine's runtime.

Historical Windows code and packaging scripts remain to avoid an unrelated,
high-risk runtime deletion. They are not supported or executed by current CI.
Historical binary/signature, npm and Store identities are not changed.
