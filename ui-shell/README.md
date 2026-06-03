# Dictate UI Shell — Tauri 2 (Linux)

The frameless desktop window that hosts the **Quiet Console** front-end (`../ui`)
and bridges it to the Python engine. The interior never forks; this shell only
draws the window, picks the per-OS chrome, and connects the webview to the local
`ui_server`.

## What it does

1. **Detects the desktop environment** (`$XDG_CURRENT_DESKTOP` → `gnome` | `kde`)
   so the front-end wears the right window-control cluster (`classify_desktop`).
2. **Finds or starts the Python control server.** It reads the handshake file
   `$XDG_DATA_HOME/dictate/ui-server.json` (`{ url, token }`). If absent, it
   launches the server (`$DICTATE_UI_SERVER_CMD`, else `dictate-ui-server`, else
   `python3 -m dictate.ui_server`) and polls briefly for the handshake.
3. **Injects the bridge** `window.__DICTATE__ = { baseUrl, token, platform }`
   into the webview *before* page load, plus `data-shell="tauri"` so the UI fills
   the frameless window. Window controls call the Tauri window API via
   `withGlobalTauri`.

## Build requirements (NOT available in the CI sandbox)

Building or running this shell needs a native Linux toolchain that the design
sandbox does not have:

- **Rust** (stable ≥ 1.77) + Cargo
- **Tauri 2 system deps**: `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`,
  `libayatana-appindicator3-dev`, `librsvg2-dev`, `build-essential`, `curl`,
  `wget`, `file`, `libssl-dev`
- The Tauri CLI: `npm i` in this folder (installs `@tauri-apps/cli`)

### Download (no build needed)

Tagged releases ship a **self-contained** `.deb` and `.AppImage` built by CI.
They **bundle the frozen Python engine** (a PyInstaller `dictate-engine` sidecar
under the app's resources), so there is no separate Python/pip install — download,
install, launch. Speech models download on first use.

```bash
sudo apt install ./dictate_*_amd64.deb        # Debian/Ubuntu
# or
chmod +x Dictate_*.AppImage && ./Dictate_*.AppImage   # any distro
```

On launch the shell starts the bundled engine as one headless process that both
dictates (push-to-talk) and serves the control API, shows a tray icon
(**Open Settings** / **Quit**), and opens the Settings window. Closing the window
hides to the tray.

### Build it yourself (one command)

From the repo root, after the one-time setup below:

```bash
scripts/build-linux-desktop.sh
# -> ui-shell/src-tauri/target/release/bundle/{deb,appimage}/...
```

One-time setup (needs root for the apt step):

```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev libgtk-3-dev \
    libayatana-appindicator3-dev librsvg2-dev build-essential \
    curl wget file libssl-dev libxdo-dev
curl https://sh.rustup.rs -sSf | sh -s -- -y      # Rust toolchain
```

### Dev loop / Rust tests

```bash
npm --prefix ../ui run build           # build the embedded front-end once
cd ui-shell && npm install && npm run dev   # hot-reloading dev window
cargo test --manifest-path src-tauri/Cargo.toml   # DE detection + bridge tests
```

CI compiles the shell and runs `cargo test` on every push (`desktop-shell` job),
and the release workflow produces and attaches the `.deb` + AppImage.

## Why it isn't compiled here

The design-handoff environment has Node and Python (so `../ui` and the Python
`ui_server` are built and fully tested) but no Rust/Cargo and no `webkit2gtk`
development libraries. The shell is therefore authored to compile cleanly on a
standard Linux dev box and carries `#[cfg(test)]` unit tests for its pure logic
(`classify_desktop`, `build_init_script`). Everything it depends on — the built
`../ui/dist` and the `ui_server` JSON contract — is verified green in this repo.

## Files

| Path | Role |
|---|---|
| `src-tauri/tauri.conf.json` | Frameless 1100×768 window, embeds `../ui/dist`, CSP for loopback IPC |
| `src-tauri/src/lib.rs` | DE detection, server handshake/spawn, bridge injection, window build |
| `src-tauri/src/main.rs` | Thin entrypoint |
| `src-tauri/capabilities/default.json` | Window-control + OS permissions |
| `src-tauri/Cargo.toml` | Tauri 2 + `tauri-plugin-os` |
