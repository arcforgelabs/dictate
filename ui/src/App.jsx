// App.jsx — the Quiet Console shell. Holds UI state, hydrates from the Dictate
// engine over IPC when live (Tauri shell), and falls back to a self-contained
// mock + dictation demo in a plain browser.
import { useState, useEffect, useRef, useCallback } from "react";
import { Icon, ArcMark } from "./icons.jsx";
import { Dot, Kbd } from "./primitives.jsx";
import { StoreCtx, MODELS, modelById, DEMO_PHRASES } from "./store.jsx";
import { VIEWS } from "./views.jsx";
import { ListeningHUD, CommandPalette, Toasts } from "./overlays.jsx";
import TitleBar from "./platform/TitleBar.jsx";
import { ipc } from "./ipc.js";

const DEFAULT_VERSION = "2026.6.5";

export default function App() {
  const [view, setView] = useState("status");
  const [model, setModelState] = useState("faster-whisper/turbo");
  const [keys, setKeys] = useState({ openai: false, xai: false, gemini: false });
  const [shortcut, setShortcutState] = useState(["Right Ctrl"]);
  const [activation, setActivationState] = useState("hold");
  const [device] = useState("Default device");
  const [device2, setDevice2State] = useState("auto");
  const [compute] = useState("int8");
  const [hotwords, setHotwords] = useState(["AcmeWidget", "OpenClaw", "Stalwart"]);
  const [history, setHistory] = useState(() => {
    const now = Date.now();
    return [
      { id: "h1", createdAt: now - 2 * 60 * 60 * 1000, text: "Draft a short note thanking the beta testers and ask them for crash reports." },
      { id: "h2", createdAt: now - 38 * 60 * 1000, text: "Let's move the sync to Thursday and keep Friday clear for the demo build." },
      { id: "h3", createdAt: now - 6 * 60 * 1000, text: "Reminder to follow up with the Stalwart team about the OAuth scopes this afternoon." },
    ];
  });
  const [theme, setThemeState] = useState("light");
  const [startup, setStartupState] = useState(true);
  const [trayOnly, setTrayOnlyState] = useState(true);
  const [overlay, setOverlayState] = useState(true);
  const [sound, setSoundState] = useState(false);
  const [ambient, setAmbientState] = useState(true);
  const [recording, setRecording] = useState(false);
  const [typing, setTyping] = useState(false);
  const [targetText, setTargetText] = useState("");
  const [palette, setPalette] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [capturing, setCapturing] = useState(false);
  const [version, setVersion] = useState(DEFAULT_VERSION);
  const [updateStatus, setUpdateStatus] = useState({ checked: false, checking: false });
  const [platform, setPlatform] = useState("gnome");
  const [live, setLive] = useState(false);

  // ---- refs to dodge stale closures in global listeners ----
  const recRef = useRef(false); recRef.current = recording;
  const tgtRef = useRef(""); tgtRef.current = targetText;
  const actRef = useRef(activation); actRef.current = activation;
  const capRef = useRef(false); capRef.current = capturing;

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);
  useEffect(() => { document.documentElement.setAttribute("data-ambient", ambient ? "on" : "off"); }, [ambient]);

  // ---- hydrate from the engine + subscribe to live events ----
  useEffect(() => {
    setPlatform(ipc.platform());
    if (!ipc.isLive()) return;
    setLive(true);
    let cancelled = false;
    ipc.getState().then((st) => {
      if (cancelled || !st) return;
      hydrate(st);
    }).catch(() => {});
    const unsub = ipc.subscribe((ev) => {
      if (ev.type === "recording") setRecording(!!ev.active);
      else if (ev.type === "history-changed") ipc.getState().then((st) => st && setHistory(mapHistory(st)));
    });
    return () => { cancelled = true; unsub && unsub(); };
  }, []);

  const hydrate = useCallback((st) => {
    if (st.model && st.model.id) setModelState(st.model.id);
    if (st.shortcut) {
      if (Array.isArray(st.shortcut.display)) setShortcutState(st.shortcut.display);
      if (st.shortcut.activation) setActivationState(st.shortcut.activation);
    }
    if (Array.isArray(st.hotwords)) setHotwords(st.hotwords);
    setHistory(mapHistory(st));
    if (st.providers) {
      setKeys({
        openai: !!st.providers.openai?.configured,
        xai: !!st.providers.xai?.configured,
        gemini: !!st.providers.gemini?.configured,
      });
    }
    if (st.prefs) {
      if (st.prefs.theme && st.prefs.theme !== "system") setThemeState(st.prefs.theme);
      setTrayOnlyState(!!st.prefs.trayOnly);
      setOverlayState(!!st.prefs.overlay);
      setSoundState(!!st.prefs.sound);
      setAmbientState(!!st.prefs.ambient);
    }
    if (typeof st.startup === "boolean") setStartupState(st.startup);
    if (st.device?.device) setDevice2State(st.device.device);
    if (st.version) setVersion(st.version);
  }, []);

  const mapHistory = (st) =>
    (st.history || []).map((h) => ({ id: h.id, text: h.text, createdAt: h.createdAt }));

  // ---- toasts ----
  const dismiss = (id) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const toast = useCallback((msg, opts = {}) => {
    const id = "t" + Date.now() + Math.random();
    setToasts((ts) => [...ts, { id, msg, ...opts }]);
    setTimeout(() => dismiss(id), opts.undo ? 5000 : 2600);
  }, []);

  // ---- persisting mutations (optimistic local + IPC when live) ----
  const persist = (payload) => { if (ipc.isLive()) ipc.patchConfig(payload).catch(() => toast("Could not save change", { bad: true })); };

  const setModel = (id) => { setModelState(id); const m = modelById(id); persist({ model: { backend: m.backend, model: id.split("/").slice(1).join("/") } }); };
  const setShortcut = (arr) => { setShortcutState(arr); persist({ shortcut: { combo: comboToToken(arr), activation } }); };
  const setActivation = (v) => { setActivationState(v); persist({ shortcut: { activation: v } }); };
  const setTheme = (v) => { setThemeState(v); persist({ prefs: { theme: v } }); };
  const setStartup = (v) => { setStartupState(v); persist({ startup: v }); };
  const setTrayOnly = (v) => { setTrayOnlyState(v); persist({ prefs: { trayOnly: v } }); };
  const setOverlay = (v) => { setOverlayState(v); persist({ prefs: { overlay: v } }); };
  const setSound = (v) => { setSoundState(v); persist({ prefs: { sound: v } }); };
  const setAmbient = (v) => { setAmbientState(v); persist({ prefs: { ambient: v } }); };
  const setDevice2 = (v) => { setDevice2State(v); persist({ device: { device: v } }); };

  const addKey = (p) => setKeys((k) => ({ ...k, [p]: true }));
  const saveKey = (brand, key, modelId) => {
    if (ipc.isLive()) {
      ipc.saveApiKey(brand, key)
        .then(() => { addKey(brand); setModel(modelId); toast(`${providerLabel(brand)} key saved to keychain`); })
        .catch((e) => toast(e.message || "Could not save key", { bad: true }));
    } else {
      addKey(brand); setModel(modelId); toast(`${providerLabel(brand)} key saved to keychain`);
    }
  };

  const addHotword = (w) => {
    setHotwords((hw) => (hw.includes(w) ? hw : [...hw, w]));
    if (ipc.isLive()) ipc.addHotwords([w]).then((r) => r && setHotwords(r.hotwords)).catch(() => {});
  };
  const removeHotword = (w) => {
    setHotwords((hw) => hw.filter((x) => x !== w));
    if (ipc.isLive()) ipc.removeHotword(w).then((r) => r && setHotwords(r.hotwords)).catch(() => {});
  };

  const pushHistory = (text) =>
    setHistory((h) => [{ id: "h" + Date.now(), createdAt: new Date().toISOString(), text }, ...h].slice(0, 20));
  const clearHistory = () => {
    setHistory((prev) => {
      if (prev.length) toast("History cleared", { undo: () => setHistory(prev) });
      return [];
    });
    if (ipc.isLive()) ipc.clearHistory().catch(() => {});
  };

  const runDoctor = (cb) => {
    if (ipc.isLive()) { ipc.runDoctor().then(cb).catch(() => cb(mockDoctor())); }
    else cb(mockDoctor());
  };
  const checkUpdates = () => {
    setUpdateStatus((u) => ({ ...u, checking: true, error: null }));
    if (!ipc.isLive()) {
      const status = { checked: true, checking: false, currentVersion: version, latestVersion: version, updateAvailable: false };
      setUpdateStatus(status);
      toast("You're on the latest version");
      return;
    }
    ipc.checkUpdates()
      .then((status) => {
        const next = { ...(status || {}), checking: false };
        setUpdateStatus(next);
        if (next.updateAvailable && next.latestVersion) toast(`Dictate ${next.latestVersion} is available`);
        else if (next.checked) toast("You're on the latest version");
        else toast("Could not check for updates", { bad: true });
      })
      .catch((e) => {
        setUpdateStatus((u) => ({ ...u, checked: false, checking: false, error: e.message || "Could not check for updates" }));
        toast("Could not check for updates", { bad: true });
      });
  };
  const mockDoctor = () => ({
    ok: true,
    checks: [
      { label: "Microphone access", sub: "Default device responding", ok: true },
      { label: "Model loads", sub: modelById(model).name, ok: true },
      { label: "Output backend", sub: "Typing into focused app", ok: true },
      { label: "Secret store", sub: "the desktop Secret Service keyring", ok: true },
      { label: "Shortcut registered", sub: shortcut.join(" + "), ok: true },
    ],
  });

  // ---- dictation demo (mock mode only; live mode is driven by SSE) ----
  const typeText = (phrase) => {
    setTyping(true);
    const prefix = tgtRef.current ? tgtRef.current.trim() + " " : "";
    let i = 0;
    const id = setInterval(() => {
      i++;
      setTargetText(prefix + phrase.slice(0, i));
      if (i >= phrase.length) {
        clearInterval(id); setTyping(false);
        pushHistory(phrase); toast("Inserted into Notes");
      }
    }, 16);
  };
  const dictateStart = () => { if (recRef.current || live) return; setRecording(true); };
  const dictateStop = () => {
    if (!recRef.current || live) return;
    setRecording(false);
    const phrase = DEMO_PHRASES[Math.floor(Math.random() * DEMO_PHRASES.length)];
    setTimeout(() => typeText(phrase), 220);
  };
  const dictateOnce = () => { if (recRef.current || live) return; setRecording(true); setTimeout(dictateStop, 1300); };

  // ---- global keyboard: ⌘K palette + push-to-talk demo (Right Ctrl) ----
  useEffect(() => {
    const down = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); return; }
      if (capRef.current || live) return;
      if (e.code === "ControlRight" && !e.repeat) {
        e.preventDefault();
        if (actRef.current === "toggle") { recRef.current ? dictateStop() : dictateStart(); }
        else dictateStart();
      }
    };
    const up = (e) => {
      if (capRef.current || live) return;
      if (e.code === "ControlRight" && actRef.current === "hold") { e.preventDefault(); dictateStop(); }
    };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    return () => { window.removeEventListener("keydown", down, true); window.removeEventListener("keyup", up, true); };
  }, [live]);

  // ---- fit-to-viewport scaler (a real 1100×768 Tauri window stays at 1.0) ----
  const winRef = useRef(null);
  useEffect(() => {
    const fit = () => {
      const el = winRef.current; if (!el) return;
      const pad = 32, W = 1100, H = 768;
      const sc = Math.min(1, (window.innerWidth - pad) / W, (window.innerHeight - pad) / H);
      el.style.transform = `translate(-50%, -50%) scale(${sc})`;
    };
    fit(); window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  const store = {
    view, setView, model, setModel, keys, addKey, saveKey, shortcut, setShortcut, activation, setActivation,
    device, device2, setDevice2, compute, hotwords, addHotword, removeHotword,
    history, clearHistory, theme, setTheme, startup, setStartup, trayOnly, setTrayOnly,
    overlay, setOverlay, sound, setSound, ambient, setAmbient,
    recording, typing, targetText, dictateStart, dictateStop, dictateOnce,
    palette, setPalette, toasts, toast, dismiss, micConnected: true, setCapturing,
    runDoctor, version, updateStatus, checkUpdates,
  };

  const NAV = [
    { v: "status", icon: "status", label: "Status" },
    { sec: "Configure" },
    { v: "model", icon: "sliders", label: "Model" },
    { v: "ptt", icon: "keyboard", label: "Push-to-talk" },
    { v: "hotwords", icon: "hash", label: "Hotwords", badge: hotwords.length },
    { sec: "Activity" },
    { v: "history", icon: "history", label: "Recent history", badge: history.length || null },
    { sec: "App" },
    { v: "startup", icon: "power", label: "Startup" },
    { v: "advanced", icon: "gear", label: "Advanced" },
  ];
  const Current = VIEWS[view];
  const m = modelById(model);

  return (
    <StoreCtx.Provider value={store}>
      <div className={"win " + platform} ref={winRef}>
        <TitleBar platform={platform} onSearch={() => setPalette(true)} />

        <div className="shell">
          <aside className="rail">
            <div className="rail-status">
              <span className="mic"><Icon name="mic" size={19} /></span>
              <span className="meta">
                <span className="nm">Dictate <Dot live /></span>
                <span className="t-meta">{m.name.split(" · ")[0]} · {recording ? "listening" : "ready"}</span>
              </span>
            </div>
            <nav className="nav">
              {NAV.map((n, i) => n.sec
                ? <div className="nav-sec" key={i}>{n.sec}</div>
                : <button key={n.v} className={"nav-item" + (view === n.v ? " active" : "")} onClick={() => setView(n.v)}>
                    <Icon name={n.icon} size={18} /><span>{n.label}</span>
                    {n.badge ? <span className="badge tnum">{n.badge}</span> : null}
                  </button>)}
            </nav>
            <div className="rail-foot">
              <button className="iconbtn" title="Toggle theme" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
                <Icon name={theme === "dark" ? "sun" : "moon"} size={17} /></button>
              <span className="t-mono" style={{ color: "var(--subtle)" }}>v{version}</span>
            </div>
          </aside>

          <main className="content">
            <div className="scroll"><Current /></div>
          </main>
        </div>

        <ListeningHUD />
        <CommandPalette />
        <Toasts />
      </div>
    </StoreCtx.Provider>
  );
}

function providerLabel(brand) {
  return { openai: "OpenAI", xai: "xAI", gemini: "Gemini" }[brand] || brand;
}

// Display keys (["Ctrl","Shift","R"] / ["Right Ctrl"]) -> engine combo token.
function comboToToken(arr) {
  const map = { "Ctrl": "ctrl", "Ctrl (R)": "ctrl_r", "Right Ctrl": "ctrl_r", "Ctrl (L)": "ctrl_l",
    "Alt": "alt", "Shift": "shift", "Super": "super" };
  return arr.map((k) => map[k] || k.toLowerCase()).join("+");
}
