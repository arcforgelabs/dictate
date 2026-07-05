// ipc.js — the bridge between the Quiet Console UI and the Dictate engine.
//
// In production the Tauri shell injects `window.__DICTATE__ = { baseUrl, token }`
// (read from the Python ui_server handshake file) and exposes window controls on
// `window.__TAURI__`. Mock mode is allowed only for dev/test/browser previews or
// an explicit VITE_DICTATE_ENABLE_MOCK=1 opt-in. Packaged shells must fail
// visibly instead of returning canned transcripts.

// The raw injected object (carries `platform` even when the server is down).
function injected() {
  return (typeof window !== "undefined" && window.__DICTATE__) || null;
}

function tauri() {
  return (typeof window !== "undefined" && window.__TAURI__) || null;
}

// A usable bridge only exists once the shell has a server URL + token.
function bridge() {
  const cfg = injected();
  return cfg && cfg.baseUrl && cfg.token ? cfg : null;
}

async function refreshBridge() {
  const t = tauri();
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

export function isShell() {
  return !!(injected() || tauri());
}

export function isMockMode() {
  if (isLive() || isShell()) return false;
  const env = import.meta.env || {};
  return !!(env.DEV || env.MODE === "test" || env.VITE_DICTATE_ENABLE_MOCK === "1");
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
  isShell,
  isMockMode,

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
  async archiveHistoryItem(id) {
    return call("POST", "/api/history/archive", { id });
  },
  async unarchiveHistoryItem(id) {
    return call("POST", "/api/history/unarchive", { id });
  },
  async startNoteRecording() {
    return call("POST", "/api/notes/start");
  },
  async stopNoteRecording() {
    return call("POST", "/api/notes/stop");
  },
  async startMeetingRecording() {
    return call("POST", "/api/meetings/start");
  },
  async stopMeetingRecording() {
    return call("POST", "/api/meetings/stop");
  },
  async discardNoteRecording() {
    return call("POST", "/api/notes/discard");
  },
  async discardMeetingRecording() {
    return call("POST", "/api/meetings/discard");
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
  //
  // Resilient to engine restarts (in-app updates, crashes): when the stream
  // drops, the engine typically comes back on a NEW port with a NEW token, so a
  // plain EventSource — which only ever retries its original URL — would stay
  // dead forever and the UI would freeze at its last snapshot. We re-resolve the
  // bridge and reopen. `onReconnect` fires after each successful *re*open so the
  // caller can re-hydrate state (history, quick-copy, …) missed while offline.
  subscribe(onEvent, onReconnect) {
    if (typeof EventSource === "undefined") return () => {};
    let src = null;
    let timer = null;
    let closed = false;
    let opened = false;

    const scheduleReconnect = () => {
      if (closed || timer) return;
      timer = setTimeout(async () => {
        timer = null;
        if (closed) return;
        await refreshBridge(); // re-resolve url+token for the (possibly new) engine
        if (!closed) openStream();
      }, 1000);
    };

    const openStream = () => {
      const cfg = bridge();
      if (!cfg) {
        scheduleReconnect();
        return;
      }
      src = new EventSource(`${cfg.baseUrl}/api/events?token=${encodeURIComponent(cfg.token)}`);
      src.onopen = () => {
        if (opened && onReconnect) {
          try {
            onReconnect();
          } catch (err) {
            /* caller re-hydrate failed; next event still updates */
          }
        }
        opened = true;
      };
      src.onmessage = (e) => {
        try {
          onEvent(JSON.parse(e.data));
        } catch (err) {
          /* ignore malformed frames */
        }
      };
      src.onerror = () => {
        // EventSource auto-retries the same (now-dead) URL; tear down and
        // re-resolve instead so a restarted engine on a new port is picked up.
        try {
          if (src) src.close();
        } catch (err) {
          /* already closed */
        }
        src = null;
        scheduleReconnect();
      };
    };

    openStream();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      try {
        if (src) src.close();
      } catch (err) {
        /* already closed */
      }
    };
  },

  // Save text through the OS-native file picker (Tauri) or a browser download fallback.
  async saveTextFile(defaultName, content) {
    const t = tauri();
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
    const t = tauri();
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
    const t = tauri();
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
