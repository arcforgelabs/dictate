// Dictate — Quiet Console shell (Tauri 2).
//
// The shell is deliberately thin: it draws a frameless window, detects the Linux
// desktop environment so the front-end can wear the right chrome, locates (or
// starts) the Python `ui_server`, and injects the `{ baseUrl, token, platform }`
// bridge into the webview before the page loads. All product logic stays in the
// Python engine; the webview is the design-system control surface.

use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::thread::sleep;
use std::time::Duration;

use serde::Deserialize;
use tauri::{WebviewUrl, WebviewWindowBuilder};

#[derive(Deserialize, Debug, Clone)]
struct Handshake {
    url: String,
    token: String,
}

/// Map `$XDG_CURRENT_DESKTOP` (or similar) to the chrome variant the UI draws.
/// GNOME-likes get the close-only Adwaita cluster; KDE/Plasma gets Breeze; any
/// other Linux session falls back to the GNOME default per the design notes.
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

/// Resolve the current platform string for the front-end.
fn detect_platform() -> String {
    if cfg!(target_os = "macos") {
        return "mac".to_string();
    }
    if cfg!(target_os = "windows") {
        // Win 11 vs 10 is decided by build number; the shell defaults to win11
        // and the front-end chrome is otherwise identical bar corners/Mica.
        return "win11".to_string();
    }
    let de = env::var("XDG_CURRENT_DESKTOP")
        .or_else(|_| env::var("XDG_SESSION_DESKTOP"))
        .or_else(|_| env::var("DESKTOP_SESSION"))
        .unwrap_or_default();
    classify_desktop(&de).to_string()
}

/// `$XDG_DATA_HOME/dictate` (or `~/.local/share/dictate`) — where the Python
/// side writes the `ui-server.json` handshake.
fn data_dir() -> Option<PathBuf> {
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
    data_dir().map(|d| d.join("ui-server.json"))
}

fn read_handshake() -> Option<Handshake> {
    let path = handshake_path()?;
    let raw = fs::read_to_string(path).ok()?;
    serde_json::from_str::<Handshake>(&raw).ok()
}

/// Start the Python control server if no live handshake is present. Tries, in
/// order: `$DICTATE_UI_SERVER_CMD`, the `dictate-ui-server` console script, then
/// `python3 -m dictate.ui_server`.
fn spawn_server() {
    if let Ok(custom) = env::var("DICTATE_UI_SERVER_CMD") {
        if !custom.trim().is_empty() {
            let mut parts = custom.split_whitespace();
            if let Some(bin) = parts.next() {
                let _ = Command::new(bin).args(parts).spawn();
                return;
            }
        }
    }
    if Command::new("dictate-ui-server").spawn().is_ok() {
        return;
    }
    let _ = Command::new("python3")
        .args(["-m", "dictate.ui_server"])
        .spawn();
}

/// Return a live handshake, spawning the server and polling briefly if needed.
fn ensure_server() -> Option<Handshake> {
    if let Some(h) = read_handshake() {
        return Some(h);
    }
    spawn_server();
    for _ in 0..50 {
        sleep(Duration::from_millis(100));
        if let Some(h) = read_handshake() {
            return Some(h);
        }
    }
    None
}

/// JS injected before page load: the bridge object + the shell/platform markers
/// the stylesheet keys off. `platform` is always present; `baseUrl`/`token` only
/// when the server was reachable (otherwise the UI runs in its mock mode).
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

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_os::init())
        .setup(|app| {
            let platform = detect_platform();
            let bridge = ensure_server();
            let init = build_init_script(&platform, bridge.as_ref());

            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Dictate")
                .inner_size(1060.0, 728.0)
                .min_inner_size(900.0, 620.0)
                .decorations(false)
                .transparent(true)
                .resizable(true)
                .initialization_script(&init)
                .build()?;

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the Dictate UI shell");
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
}
