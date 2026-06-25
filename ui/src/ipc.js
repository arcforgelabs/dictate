// ipc.js — the bridge between the Quiet Console UI and the Dictate engine.
//
// In production the Tauri shell injects `window.__DICTATE__ = { baseUrl, token }`
// (read from the Python ui_server handshake file) and exposes window controls on
// `window.__TAURI__`. When neither is present — a plain browser, dev, or a test
// runner — we fall back to a self-contained mock so the UI is fully runnable
// standalone.

// The raw injected object (carries `platform` even when the server is down).
function injected() {
  return (typeof window !== "undefined" && window.__DICTATE__) || null;
}

// A usable bridge only exists once the shell has a server URL + token.
function bridge() {
  const cfg = injected();
  return cfg && cfg.baseUrl && cfg.token ? cfg : null;
}

async function refreshBridge() {
  const t = typeof window !== "undefined" ? window.__TAURI__ : null;
  const invoke = t && t.core && t.core.invoke;
  if (!invoke) return null;
  let next;
  try {
    next = await invoke("refresh_bridge");
  } catch (e) {
    return null;
  }
  if (!next || !next.baseUrl || !next.token) return null;
  window.__DICTATE__ = { ...(injected() || {}), ...next };
  return bridge();
}

export function isLive() {
  return !!bridge();
}

async function call(method, path, body, retry = true) {
  const cfg = bridge();
  if (!cfg) throw new Error("not-live");
  const headers = { Authorization: `Bearer ${cfg.token}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(cfg.baseUrl + path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    if (retry && await refreshBridge()) return call(method, path, body, false);
    throw e;
  }
  let data = null;
  try {
    data = await res.json();
  } catch (e) {
    data = null;
  }
  if (!res.ok) {
    if (retry && res.status === 401 && await refreshBridge()) {
      return call(method, path, body, false);
    }
    const message = (data && data.error) || `${res.status} ${res.statusText}`;
    throw new Error(message);
  }
  return data;
}

export const ipc = {
  isLive,

  // Platform: "gnome" | "kde" | "win11" | "win10" | "mac" | "linux".
  // Read from the injected object directly so the chrome is correct even when
  // the server handshake hasn't completed yet.
  platform() {
    const cfg = injected();
    if (cfg && cfg.platform) return cfg.platform;
    return "gnome"; // sensible Linux default for browser preview
  },

  async getState() {
    return call("GET", "/api/state");
  },
  async patchConfig(payload) {
    return call("PATCH", "/api/config", payload);
  },
  async addHotwords(words) {
    return call("POST", "/api/hotwords", { words });
  },
  async removeHotword(word) {
    return call("DELETE", "/api/hotwords", { word });
  },
  async clearHistory() {
    return call("DELETE", "/api/history");
  },
  async startNoteRecording() {
    return call("POST", "/api/notes/start");
  },
  async stopNoteRecording() {
    return call("POST", "/api/notes/stop");
  },
  async pauseNoteRecording() {
    return call("POST", "/api/notes/pause");
  },
  async resumeNoteRecording() {
    return call("POST", "/api/notes/resume");
  },
  async toggleNoteRecording() {
    return call("POST", "/api/notes/toggle");
  },
  async saveApiKey(backend, apiKey) {
    return call("POST", "/api/api-keys", { backend, apiKey });
  },
  async clearApiKey(backend) {
    return call("DELETE", "/api/api-keys", { backend });
  },
  async runDoctor() {
    return call("POST", "/api/doctor");
  },
  async checkUpdates() {
    return call("GET", "/api/update-status");
  },
  async startUpdate() {
    return call("POST", "/api/update");
  },

  // Server-sent events: live recording / status pushes from the daemon.
  subscribe(onEvent) {
    const cfg = bridge();
    if (!cfg || typeof EventSource === "undefined") return () => {};
    const src = new EventSource(`${cfg.baseUrl}/api/events?token=${encodeURIComponent(cfg.token)}`);
    src.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data));
      } catch (err) {
        /* ignore malformed frames */
      }
    };
    return () => src.close();
  },

  // Save text through the OS-native file picker (Tauri) or a browser download fallback.
  async saveTextFile(defaultName, content) {
    const t = typeof window !== "undefined" ? window.__TAURI__ : null;
    const invoke = t && t.core && t.core.invoke;
    if (invoke) {
      return invoke("save_text_file", { defaultName, content });
    }
    const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    try {
      const a = document.createElement("a");
      a.href = url;
      a.download = defaultName;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
      return true;
    } finally {
      URL.revokeObjectURL(url);
    }
  },

  // Relaunch the app after an in-app update installed a new package.
  async restartApp() {
    const t = typeof window !== "undefined" ? window.__TAURI__ : null;
    const invoke = t && t.core && t.core.invoke;
    if (!invoke) return false;
    try {
      await invoke("restart_app");
      return true;
    } catch (e) {
      return false;
    }
  },

  // Window controls — wired to the Tauri current window when available.
  async windowControl(action) {
    const t = typeof window !== "undefined" ? window.__TAURI__ : null;
    if (!t) return false;
    try {
      const win = t.window.getCurrentWindow ? t.window.getCurrentWindow() : t.window.getCurrent();
      if (action === "minimize") await win.minimize();
      else if (action === "maximize") await win.toggleMaximize();
      else if (action === "close") await win.close();
      return true;
    } catch (e) {
      return false;
    }
  },
};
