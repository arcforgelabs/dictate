// Dictate — Quiet Console shell (Tauri 2).
//
// The packaged app is launch-and-go: this shell bundles the frozen Python engine
// (`dictate-engine`, a PyInstaller sidecar under resources/engine/), starts it as
// one headless process that both dictates and serves the control API, draws a
// tray icon (Open Settings / Quit), and shows the Settings window — all without a
// separate Python install. In a dev/pip environment it falls back to the
// `dictate-engine` / `dictate-ui-server` / `dictate` binaries on PATH.

use std::env;
use std::fs;
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{Mutex, OnceLock};
use std::thread::sleep;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, RunEvent, Runtime, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_dialog::DialogExt;

#[derive(Deserialize, Debug, Clone)]
struct Handshake {
    url: String,
    token: String,
    pid: Option<u32>,
    // The engine's own version. The shell restarts the engine when this differs
    // from its own version, so shell + engine never run mismatched code after an
    // update (e.g. a stale engine orphaned by an abnormal shell exit).
    version: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct BridgePayload {
    base_url: String,
    token: String,
    platform: String,
}

// The spawned engine process, killed when the app exits.
static ENGINE_CHILD: OnceLock<Mutex<Option<Child>>> = OnceLock::new();

fn engine_child_slot() -> &'static Mutex<Option<Child>> {
    ENGINE_CHILD.get_or_init(|| Mutex::new(None))
}

/// Map `$XDG_CURRENT_DESKTOP` (or similar) to the chrome variant the UI draws.
pub fn classify_desktop(value: &str) -> &'static str {
    let v = value.to_ascii_lowercase();
    if v.contains("kde") || v.contains("plasma") {
        "kde"
    } else if v.contains("gnome")
        || v.contains("unity")
        || v.contains("pantheon")
        || v.contains("cinnamon")
    {
        "gnome"
    } else {
        "gnome"
    }
}

fn detect_platform() -> String {
    if cfg!(target_os = "macos") {
        return "mac".to_string();
    }
    if cfg!(target_os = "windows") {
        return "win11".to_string();
    }
    let de = env::var("XDG_CURRENT_DESKTOP")
        .or_else(|_| env::var("XDG_SESSION_DESKTOP"))
        .or_else(|_| env::var("DESKTOP_SESSION"))
        .unwrap_or_default();
    classify_desktop(&de).to_string()
}

fn data_dir() -> Option<PathBuf> {
    if cfg!(target_os = "windows") {
        if let Ok(local) = env::var("LOCALAPPDATA") {
            if !local.is_empty() {
                return Some(PathBuf::from(local).join("dictate"));
            }
        }
        if let Ok(roaming) = env::var("APPDATA") {
            if !roaming.is_empty() {
                return Some(PathBuf::from(roaming).join("dictate"));
            }
        }
        if let Ok(profile) = env::var("USERPROFILE") {
            if !profile.is_empty() {
                return Some(PathBuf::from(profile).join("AppData/Local/dictate"));
            }
        }
    }
    if let Ok(xdg) = env::var("XDG_DATA_HOME") {
        if !xdg.is_empty() {
            return Some(PathBuf::from(xdg).join("dictate"));
        }
    }
    env::var("HOME")
        .ok()
        .map(|h| PathBuf::from(h).join(".local/share/dictate"))
}

fn handshake_path() -> Option<PathBuf> {
    data_dir().map(|dir| dir.join("ui-server.json"))
}

fn read_handshake() -> Option<Handshake> {
    let path = handshake_path()?;
    let raw = fs::read_to_string(path).ok()?;
    serde_json::from_str::<Handshake>(&raw).ok()
}

fn remove_handshake() {
    if let Some(path) = handshake_path() {
        let _ = fs::remove_file(path);
    }
}

fn handshake_port(url: &str) -> Option<u16> {
    let without_scheme = url
        .strip_prefix("http://")
        .or_else(|| url.strip_prefix("https://"))?;
    let authority = without_scheme.split('/').next()?;
    let (host, port) = authority.rsplit_once(':')?;
    if host != "127.0.0.1" && host != "localhost" {
        return None;
    }
    port.parse().ok()
}

fn process_exists(pid: u32) -> bool {
    #[cfg(target_os = "linux")]
    {
        return std::path::Path::new("/proc").join(pid.to_string()).exists();
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = pid;
        true
    }
}

fn handshake_is_live(handshake: &Handshake) -> bool {
    if let Some(pid) = handshake.pid {
        if !process_exists(pid) {
            return false;
        }
    }
    let Some(port) = handshake_port(&handshake.url) else {
        return false;
    };
    let addr = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port));
    TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
}

fn read_live_handshake() -> Option<Handshake> {
    let h = read_handshake()?;
    if handshake_is_live(&h) {
        return Some(h);
    }
    remove_handshake();
    None
}

/// The bundled engine launcher, if this is a packaged build.
fn bundled_engine<R: Runtime, M: Manager<R>>(app: &M) -> Option<PathBuf> {
    for base in engine_resource_dirs(app) {
        for name in engine_binary_names() {
            let candidate = base.join("engine").join(name);
            if candidate.exists() {
                return Some(candidate);
            }
        }
    }
    None
}

fn engine_resource_dirs<R: Runtime, M: Manager<R>>(app: &M) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(exe) = env::current_exe() {
        if let Some(parent) = exe.parent() {
            dirs.push(parent.to_path_buf());
        }
    }
    if let Ok(res) = app.path().resource_dir() {
        if !dirs.iter().any(|dir| dir == &res) {
            dirs.push(res);
        }
    }
    dirs
}

fn engine_binary_names() -> &'static [&'static str] {
    if cfg!(target_os = "windows") {
        &["dictate-engine.exe", "dictate-engine"]
    } else {
        &["dictate-engine"]
    }
}

/// Start the engine: the bundled sidecar as a headless dictation daemon that
/// also serves the control API; otherwise a PATH fallback for dev/pip installs.
fn spawn_engine<R: Runtime, M: Manager<R>>(app: &M) {
    let mut slot = engine_child_slot().lock().unwrap();
    if let Some(child) = slot.as_mut() {
        match child.try_wait() {
            Ok(None) => return,
            Ok(Some(_)) | Err(_) => {
                *slot = None;
            }
        }
    }

    let shell_version = env!("CARGO_PKG_VERSION");
    let shell_path = env::current_exe().ok();
    // 1) Packaged: one process dictates + serves.
    if let Some(bin) = bundled_engine(app) {
        let mut cmd = Command::new(&bin);
        cmd.arg("--no-tray").env("DICTATE_UI_SERVER", "1");
        cmd.env("DICTATE_SHELL_VERSION", shell_version);
        if let Some(path) = shell_path.as_ref() {
            cmd.env("DICTATE_SHELL_PATH", path);
        }
        if let Ok(child) = cmd.spawn() {
            *slot = Some(child);
            return;
        }
    }
    // 2) Custom override.
    if let Ok(custom) = env::var("DICTATE_UI_SERVER_CMD") {
        if !custom.trim().is_empty() {
            let mut parts = custom.split_whitespace();
            if let Some(first) = parts.next() {
                let mut cmd = Command::new(first);
                cmd.args(parts).env("DICTATE_SHELL_VERSION", shell_version);
                if let Some(path) = shell_path.as_ref() {
                    cmd.env("DICTATE_SHELL_PATH", path);
                }
                if let Ok(child) = cmd.spawn() {
                    *slot = Some(child);
                    return;
                }
            }
        }
    }
    // 3) Dev/pip: the lightweight control server (a separate `dictate` tray, if
    //    installed, handles dictation), then the full engine as a last resort.
    let mut ui_server = Command::new("dictate-ui-server");
    ui_server.env("DICTATE_SHELL_VERSION", shell_version);
    if let Some(path) = shell_path.as_ref() {
        ui_server.env("DICTATE_SHELL_PATH", path);
    }
    if let Ok(child) = ui_server.spawn() {
        *slot = Some(child);
        return;
    }
    let mut dictate = Command::new("dictate");
    dictate.arg("--no-tray").env("DICTATE_UI_SERVER", "1");
    dictate.env("DICTATE_SHELL_VERSION", shell_version);
    if let Some(path) = shell_path.as_ref() {
        dictate.env("DICTATE_SHELL_PATH", path);
    }
    if let Ok(child) = dictate.spawn() {
        *slot = Some(child);
    }
}

/// True when the live engine reports the same version as this shell. An engine
/// with no version (or a different one) is a stale orphan from a previous build.
fn handshake_version_matches(h: &Handshake, shell_version: &str) -> bool {
    h.version.as_deref() == Some(shell_version)
}

/// Terminate an engine we did not spawn (an external orphan), by pid.
fn kill_pid(pid: u32) {
    #[cfg(not(target_os = "windows"))]
    {
        let _ = Command::new("kill").arg("-TERM").arg(pid.to_string()).status();
        for _ in 0..20 {
            if !process_exists(pid) {
                return;
            }
            sleep(Duration::from_millis(50));
        }
        let _ = Command::new("kill").arg("-KILL").arg(pid.to_string()).status();
    }
    #[cfg(target_os = "windows")]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/F", "/T"])
            .status();
    }
}

/// Best-effort path to the engine's daemon lock dir (mirrors process_lock.py).
fn daemon_lock_dir() -> Option<PathBuf> {
    if cfg!(target_os = "windows") {
        return data_dir().map(|d| d.join("dictate-daemon.lockdir"));
    }
    env::var("XDG_RUNTIME_DIR")
        .ok()
        .filter(|v| !v.is_empty())
        .map(|v| PathBuf::from(v).join("dictate-daemon.lockdir"))
}

/// Stop a stale (wrong-version) engine and clear its handshake + lock so a fresh
/// engine of this version can take over cleanly.
fn takeover_stale_engine(handshake: &Handshake) {
    if let Some(pid) = handshake.pid {
        kill_pid(pid);
    }
    remove_handshake();
    if let Some(lockdir) = daemon_lock_dir() {
        let _ = fs::remove_dir_all(lockdir);
    }
}

/// Return a live handshake, starting the engine and polling briefly if needed.
///
/// The shell and engine always run the same version. If a live handshake points
/// at an engine reporting a different version — a stale orphan left by an
/// abnormal shell exit or an in-place update — stop it and start a fresh one so
/// the two never run mismatched code.
fn ensure_engine<R: Runtime, M: Manager<R>>(app: &M) -> Option<Handshake> {
    let shell_version = env!("CARGO_PKG_VERSION");
    if let Some(h) = read_live_handshake() {
        if handshake_version_matches(&h, shell_version) {
            return Some(h);
        }
        takeover_stale_engine(&h);
    }
    spawn_engine(app);
    for _ in 0..80 {
        sleep(Duration::from_millis(100));
        if let Some(h) = read_live_handshake() {
            return Some(h);
        }
    }
    None
}

fn kill_engine() {
    if let Some(mut child) = engine_child_slot().lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

/// JS injected before page load: the bridge object + the shell/platform markers
/// the stylesheet keys off.
fn build_init_script(platform: &str, bridge: Option<&Handshake>, native_decorations: bool) -> String {
    let dictate = match bridge {
        Some(h) => format!(
            "window.__DICTATE__ = {{ baseUrl: {}, token: {}, platform: {} }};",
            json_str(&h.url),
            json_str(&h.token),
            json_str(platform),
        ),
        None => format!(
            "window.__DICTATE__ = {{ platform: {} }};",
            json_str(platform)
        ),
    };
    format!(
        "{dictate}\n\
         document.documentElement.setAttribute('data-shell','tauri');\n\
         document.documentElement.setAttribute('data-platform',{});\n\
         document.documentElement.setAttribute('data-native-decorations',{});",
        json_str(platform),
        json_str(if native_decorations { "true" } else { "false" })
    )
}

fn json_str(s: &str) -> String {
    serde_json::to_string(s).unwrap_or_else(|_| "\"\"".to_string())
}

#[tauri::command]
fn refresh_bridge(app: tauri::AppHandle) -> Option<BridgePayload> {
    let platform = detect_platform();
    ensure_engine(&app).map(|h| BridgePayload {
        base_url: h.url,
        token: h.token,
        platform,
    })
}

/// Relaunch the shell after an in-app update installed a new package. Stopping
/// the engine first and re-exec'ing the (now-updated) shell binary brings shell
/// and engine back up together at the new version.
#[tauri::command]
fn restart_app(app: tauri::AppHandle) {
    kill_engine();
    app.restart();
}

/// Native save dialog + write — GTK on Linux, Win32 on Windows, etc.
#[tauri::command]
async fn save_text_file(
    app: tauri::AppHandle,
    default_name: String,
    content: String,
) -> Result<bool, String> {
    let picked = app
        .dialog()
        .file()
        .set_file_name(&default_name)
        .add_filter("Markdown", &["md"])
        .blocking_save_file();
    let Some(file_path) = picked else {
        return Ok(false);
    };
    let path = file_path.into_path().map_err(|e| e.to_string())?;
    fs::write(&path, content.as_bytes()).map_err(|e| e.to_string())?;
    Ok(true)
}

fn show_settings(app: &tauri::AppHandle) {
    let _ = ensure_engine(app);
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            show_settings(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_os::init())
        .invoke_handler(tauri::generate_handler![refresh_bridge, restart_app, save_text_file])
        .setup(|app| {
            let platform = detect_platform();
            let bridge = ensure_engine(app);
            let native_decorations = env::var("DICTATE_CUSTOM_CHROME").unwrap_or_default() != "1";
            let init = build_init_script(&platform, bridge.as_ref(), native_decorations);

            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Dictate")
                .inner_size(1100.0, 768.0)
                .min_inner_size(900.0, 620.0)
                .decorations(native_decorations)
                .transparent(!native_decorations)
                .resizable(true)
                .initialization_script(&init)
                .build()?;

            // Tray icon: the always-there surface. Closing the window hides to
            // the tray; Quit stops the engine and exits.
            let open = MenuItem::with_id(app, "open", "Open Settings", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Dictate", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit])?;
            TrayIconBuilder::with_id("main")
                .tooltip("Dictate")
                .icon(app.default_window_icon().cloned().unwrap())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "open" => show_settings(app),
                    "quit" => {
                        kill_engine();
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_settings(tray.app_handle());
                    }
                })
                .build(app)?;

            // Closing the window hides it to the tray instead of quitting.
            if let Some(window) = app.get_webview_window("main") {
                let handle = window.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = handle.hide();
                    }
                });
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the Dictate UI shell")
        .run(|_app, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                kill_engine();
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_kde() {
        assert_eq!(classify_desktop("KDE"), "kde");
        assert_eq!(classify_desktop("plasma"), "kde");
        assert_eq!(classify_desktop("X-Cinnamon:KDE"), "kde");
    }

    #[test]
    fn classifies_gnome_and_default() {
        assert_eq!(classify_desktop("GNOME"), "gnome");
        assert_eq!(classify_desktop("ubuntu:GNOME"), "gnome");
        assert_eq!(classify_desktop("pantheon"), "gnome");
        assert_eq!(classify_desktop(""), "gnome");
        assert_eq!(classify_desktop("sway"), "gnome");
    }

    #[test]
    fn init_script_carries_bridge() {
        let h = Handshake {
            url: "http://127.0.0.1:8765".into(),
            token: "secret".into(),
            pid: None,
            version: None,
        };
        let script = build_init_script("kde", Some(&h), true);
        assert!(script.contains("http://127.0.0.1:8765"));
        assert!(script.contains("secret"));
        assert!(script.contains("'data-shell','tauri'"));
        assert!(script.contains("data-native-decorations"));
        assert!(script.contains("\"true\""));
        assert!(script.contains("\"kde\""));
    }

    #[test]
    fn init_script_without_bridge_still_sets_platform() {
        let script = build_init_script("gnome", None, false);
        assert!(script.contains("window.__DICTATE__ = { platform: \"gnome\" }"));
        assert!(script.contains("data-native-decorations"));
        assert!(script.contains("\"false\""));
        assert!(!script.contains("baseUrl"));
    }

    #[test]
    fn engine_binary_candidates_match_platform() {
        if cfg!(target_os = "windows") {
            assert_eq!(engine_binary_names()[0], "dictate-engine.exe");
        } else {
            assert_eq!(engine_binary_names(), &["dictate-engine"]);
        }
    }

    #[test]
    fn extracts_loopback_handshake_port() {
        assert_eq!(handshake_port("http://127.0.0.1:8765"), Some(8765));
        assert_eq!(
            handshake_port("http://localhost:38769/api/state"),
            Some(38769)
        );
        assert_eq!(handshake_port("https://example.com:443"), None);
        assert_eq!(handshake_port("not a url"), None);
    }

    #[test]
    fn rejects_missing_linux_pid() {
        if cfg!(target_os = "linux") {
            let h = Handshake {
                url: "http://127.0.0.1:9".into(),
                token: "secret".into(),
                pid: Some(u32::MAX),
                version: None,
            };
            assert!(!handshake_is_live(&h));
        }
    }

    #[test]
    fn version_guard_matches_only_exact_version() {
        let mk = |v: Option<&str>| Handshake {
            url: "http://127.0.0.1:1".into(),
            token: "t".into(),
            pid: None,
            version: v.map(|s| s.to_string()),
        };
        assert!(handshake_version_matches(&mk(Some("2026.6.23")), "2026.6.23"));
        // A different version is a stale orphan -> not a match.
        assert!(!handshake_version_matches(&mk(Some("2026.6.20")), "2026.6.23"));
        // A versionless handshake (pre-update engine) -> not a match.
        assert!(!handshake_version_matches(&mk(None), "2026.6.23"));
    }
}
