<p align="center">
  <img src="https://raw.githubusercontent.com/arcforgelabs/dictate/master/assets/dictate.png" alt="Dictate" width="128" height="128">
</p>

# Dictate

Linux desktop dictation that types into the focused app. Press your configured
push-to-talk shortcut, speak, and release. You can also record a longer note
and recover or export it from local history.

**Local only.** No account, subscription, API key or hosted transcription.
Audio and transcripts stay on your machine. Dictate runs Parakeet on the CPU,
not a GPU. See [VISION.md](VISION.md) for product scope.

Dictate is a **Linux-only open-source personal app**, developed when there is
time. There is no official deployment or automated release publishing.
Windows code, previously published binaries and Store identifiers are retained
as historical material, not supported installation channels.

## Install on Linux

From a trusted checkout:

```bash
git clone https://github.com/arcforgelabs/dictate.git
cd dictate
./install-ubuntu.sh
```

On other distributions use `./install.sh` after installing the audio and
desktop prerequisites for your distribution. The per-user installer uses
`~/.local/share/dictate`, creates a launcher and prepares the local model.
The optional desktop shell build needs Rust/Cargo, npm and WebKitGTK
development libraries. See [desktop packaging](docs/desktop-packaging.md).

To build a Linux package locally:

```bash
DICTATE_BUNDLES=deb ./scripts/build-linux-desktop.sh
sudo apt install ./ui-shell/src-tauri/target/release/bundle/deb/*.deb
```

This is a local build, not an official deployment. Previously published GitHub
release packages and `@arcforgelabs/dictate` remain available as historical
snapshots. Existing npm/jsDelivr URLs and updater compatibility are preserved;
there is no npm rename or new publish. Those snapshots do not necessarily
contain the current source.

## Use

Open Dictate from the Linux launcher, hold your configured shortcut, speak and
release. Dictation is pasted into the focused app, then the clipboard is
restored. The tray and desktop window also provide capture controls and history.

```bash
dictate
dictate --no-tray
dictate --once
dictate --once --copy
dictate doctor --quick
dictate doctor --quick --fix
dictate doctor --check-model-load
```

Advanced configuration remains available through the CLI:

```bash
dictate config show
dictate --stt-backend parakeet --model parakeet-tdt-0.6b-v3
dictate --add-hotword AcmeWidget
dictate --list-hotwords
```

The default is Parakeet TDT 0.6B v2 for English; v3 supports 25 European
languages. Source installs prepare model files locally. Transcription itself
does not use the network. Meetings and speaker labelling are shelved (#140).
Old meeting settings migrate away while saved transcripts remain in history.

## Update and uninstall

To update a checkout installation, pull the intended revision, then run:

```bash
./update.sh
```

To uninstall instead:

```bash
./uninstall.sh
```

Use `--remove-user-data` only when you also want to remove config, logs,
history and downloaded models. A locally built Debian package can be removed
with `sudo apt purge dictate`; that leaves user data intact.

The app's existing updater still discovers historical npm/GitHub release
channels. No new version is published automatically from this source. Existing
installed versions and release assets are not rewritten by the pipeline cleanup.

## Local state and safety

- Configuration: `~/.config/dictate/config.yaml`.
- History, notes and models: `~/.local/share/dictate/`.
- Repository defaults contain no personal hotwords.
- Dictation can be sensitive; check logs and reports before sharing them.
- Check important transcriptions before relying on them.
- Support and maintenance are best-effort.

The account, subscription, cloud-sync and hosted-transcription code was removed
on 2026-09-19. See [the local-only audit](docs/local-only-audit.md).

## Develop and build

- [Contributing](CONTRIBUTING.md) and [agent instructions](AGENTS.md).
- [React/Vite UI](ui/README.md): `cd ui && npm run dev` runs the local mock UI.
- [Tauri Linux shell](ui-shell/README.md).
- [Desktop packaging and CI](docs/desktop-packaging.md).
- [Source/release policy](docs/RELEASING.md).
- [Local transcription plan](docs/TRANSCRIPTION_PLAN.md).
- [Personal ownership transfer](docs/personal-ownership-transfer.md).
- [Security policy](SECURITY.md).

Documentation is maintained in this repository's `docs/` folder. The former
business docs mirror is not updated by this repository. `docs/docs.json` is
the documentation index; [archive](docs/archive/README.md) and release pages
retain earlier decisions without defining current support.

## License

MIT. See [LICENSE](LICENSE).
