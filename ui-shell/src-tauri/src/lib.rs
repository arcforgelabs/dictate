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
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::{Mutex, OnceLock};
use std::thread::sleep;
use std::time::Duration;

use serde::Deserialize;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};

#[derive(Deserialize, Debug, Clone)]
struct Handshake {
    url: String,
    token: String,
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

fn read_handshake() -> Option<Handshake> {
    let path = data_dir()?.join("ui-server.json");
    let raw = fs::read_to_string(path).ok()?;
    serde_json::from_str::<Handshake>(&raw).ok()
}

/// The bundled engine launcher, if this is a packaged build.
fn bundled_engine(app: &tauri::App) -> Option<PathBuf> {
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

fn engine_resource_dirs(app: &tauri::App) -> Vec<PathBuf> {
    let mut dirs = Vec::new();
    if let Ok(res) = app.path().resource_dir() {
        dirs.push(res);
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(parent) = exe.parent() {
            let parent = parent.to_path_buf();
            if !dirs.iter().any(|dir| dir == &parent) {
                dirs.push(parent);
            }
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
fn spawn_engine(app: &tauri::App) {
    // 1) Packaged: one process dictates + serves.
    if let Some(bin) = bundled_engine(app) {
        if let Ok(child) = Command::new(&bin)
            .arg("--no-tray")
            .env("DICTATE_UI_SERVER", "1")
            .spawn()
        {
            *engine_child_slot().lock().unwrap() = Some(child);
            return;
        }
    }
    // 2) Custom override.
    if let Ok(custom) = env::var("DICTATE_UI_SERVER_CMD") {
        if !custom.trim().is_empty() {
            let mut parts = custom.split_whitespace();
            if let Some(first) = parts.next() {
                if let Ok(child) = Command::new(first).args(parts).spawn() {
                    *engine_child_slot().lock().unwrap() = Some(child);
                    return;
                }
            }
        }
    }
    // 3) Dev/pip: the lightweight control server (a separate `dictate` tray, if
    //    installed, handles dictation), then the full engine as a last resort.
    if let Ok(child) = Command::new("dictate-ui-server").spawn() {
        *engine_child_slot().lock().unwrap() = Some(child);
        return;
    }
    if let Ok(child) = Command::new("dictate")
        .arg("--no-tray")
        .env("DICTATE_UI_SERVER", "1")
        .spawn()
    {
        *engine_child_slot().lock().unwrap() = Some(child);
    }
}

/// Return a live handshake, starting the engine and polling briefly if needed.
fn ensure_engine(app: &tauri::App) -> Option<Handshake> {
    if let Some(h) = read_handshake() {
        return Some(h);
    }
    spawn_engine(app);
    for _ in 0..80 {
        sleep(Duration::from_millis(100));
        if let Some(h) = read_handshake() {
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
fn build_init_script(platform: &str, bridge: Option<&Handshake>) -> String {
    let dictate = match bridge {
        Some(h) => format!(
            "window.__DICTATE__ = {{ baseUrl: {}, token: {}, platform: {} }};",
            json_str(&h.url),
            json_str(&h.token),
            json_str(platform),
        ),
        None => format!("window.__DICTATE__ = {{ platform: {} }};", json_str(platform)),
    };
    format!(
        "{dictate}\n\
         document.documentElement.setAttribute('data-shell','tauri');\n\
         document.documentElement.setAttribute('data-platform',{});",
        json_str(platform)
    )
}

fn json_str(s: &str) -> String {
    serde_json::to_string(s).unwrap_or_else(|_| "\"\"".to_string())
}

fn show_settings(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_os::init())
        .setup(|app| {
            let platform = detect_platform();
            let bridge = ensure_engine(app);
            let init = build_init_script(&platform, bridge.as_ref());

            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Dictate")
                .inner_size(1100.0, 768.0)
                .min_inner_size(900.0, 620.0)
                .decorations(false)
                .transparent(true)
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
        };
        let script = build_init_script("kde", Some(&h));
        assert!(script.contains("http://127.0.0.1:8765"));
        assert!(script.contains("secret"));
        assert!(script.contains("'data-shell','tauri'"));
        assert!(script.contains("\"kde\""));
    }

    #[test]
    fn init_script_without_bridge_still_sets_platform() {
        let script = build_init_script("gnome", None);
        assert!(script.contains("window.__DICTATE__ = { platform: \"gnome\" }"));
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
}
