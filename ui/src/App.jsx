// App.jsx — Note Capture shell. Home = Breath Cradle capture surface.
// Settings views are reached via the gear menu (⚙) or ⌘K palette; they render
// full-window with a back button. The rail + Status dashboard are gone.
// IPC contract, overlays (ListeningHUD / ⌘K / Toasts), platform TitleBar,
// StoreCtx, and all settings views are untouched.
import { useState, useEffect, useRef, useCallback } from "react";
import { Icon } from "./icons.jsx";
import { Kbd } from "./primitives.jsx";
import { StoreCtx, useStore, MODELS, modelById, DEMO_PHRASES, formatHistoryTime } from "./store.jsx";
import { VIEWS } from "./views.jsx";
import { ListeningHUD, CommandPalette, Toasts } from "./overlays.jsx";
import TitleBar from "./platform/TitleBar.jsx";
import { BreathCradle } from "./visualizers.jsx";
import { ipc } from "./ipc.js";

const DEFAULT_VERSION = "2026.6.22";
const TERMINAL_TRANSCRIPT_ID_LIMIT = 64;

// Human-readable labels for settings views (used in the back-nav bar).
const VIEW_LABELS = {
  status: "Status", model: "Model", ptt: "Push-to-talk", hotwords: "Hotwords",
  history: "Recent history", update: "App update", startup: "Startup", advanced: "Advanced",
};

// Format seconds → m:ss or h:mm:ss (mirrors the design's fmt helper).
function fmtSecs(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`;
}

/* ── Copy-last row: quiet recovery chip below the cradle (home only) ─── */
function CopyLastNote() {
  const s = useStore();
  if (!s.history || s.history.length === 0 || s.noteRecording) return null;
  const latest = s.history[0];
  const handleCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(latest.text)
        .then(() => s.toast("Copied last note"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    } else {
      s.toast("Clipboard not available", { bad: true });
    }
  };
  return (
    <button className="lastcap" onClick={handleCopy} title="Copy the last note">
      <span className="lc-ico"><Icon name="copy" size={15} /></span>
      <span className="lc-body">
        <span className="lc-text">{latest.text}</span>
        <span className="lc-meta t-mono">Last note · {formatHistoryTime(latest.createdAt)} · tap to copy</span>
      </span>
    </button>
  );
}

/* ── Capture home: header + Breath Cradle + feedback ─────────────────── */
function CaptureHome() {
  const s = useStore();
  return (
    <div className="note-home">
      {/* Stage 3: no in-app header — the cradle sits directly under the TitleBar chrome */}
      <div className="note-home-inner">
        {/* Cradle + feedback */}
        <div className="note-screen">
          <BreathCradle
            active={s.noteRecording}
            reduced={s.reduced}
            onToggle={s.toggleNoteRecording}
          />
          <div className="note-feedback">
            {s.noteRecording ? (
              <>
                <div className="note-status live">Recording</div>
                <div className="note-timer t-mono">{fmtSecs(s.noteElapsed)}</div>
                <div className="note-preview" aria-live="polite">
                  {s.transcript?.text
                    ? <><span>{s.transcript.text}</span><span className="note-caret" /></>
                    : <span className="note-preview-wait">Listening for speech…</span>}
                </div>
              </>
            ) : (
              <>
                <div className="note-status">Ready to capture</div>
                <div className="note-status-sub">Press the mic and speak — it becomes a note.</div>
                {/* Live push-to-talk transcript also surfaces here */}
                {s.transcript?.text && !s.transcript.stale && (
                  <div className="note-preview" aria-live="polite">
                    <span>{s.transcript.text}</span>
                    {s.recording && <span className="note-caret" />}
                  </div>
                )}
              </>
            )}
          </div>
          {/* Copy-last: quiet row beneath the cradle; hidden while recording or when empty */}
          <CopyLastNote />
        </div>
      </div>
    </div>
  );
}

/* ── Transcribing… (indeterminate, shown between stop and note event) ── */
function NoteProcessing() {
  return (
    <div className="note-proc-wrap">
      <div className="note-proc-inner">
        <div className="note-status" style={{ marginBottom: 6 }}>Transcribing…</div>
        <div className="note-status-sub">Turning your words into a note.</div>
        <div className="note-proc-bar" aria-hidden="true"><span /></div>
      </div>
    </div>
  );
}

/* ── Note ready: Insert · Open note · overflow (Copy / Export) ──────── */
function NoteReady() {
  const s = useStore();
  const [ovfOpen, setOvfOpen] = useState(false);
  const note = s.currentNote;
  if (!note) return null;

  const noteLabel = note.createdAt ? `Note · ${formatHistoryTime(note.createdAt)}` : "Note";

  // TODO(backend): No /api/insert endpoint exists in ui_server.py — the typing
  // daemon path (outputs.py) is invoked internally and is not reachable via HTTP
  // from the webview. Until a POST /api/insert route is added to ui_server.py +
  // backed by UiBackend.insert_text(), "Insert" copies to clipboard instead.
  const handleInsert = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(note.text)
        .then(() => s.toast("Copied — paste it where you want"))
        .catch(() => s.toast("Could not copy to clipboard", { bad: true }));
    } else {
      s.toast("Clipboard not available", { bad: true });
    }
  };

  const handleCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(note.text)
        .then(() => { setOvfOpen(false); s.toast("Copied to clipboard"); })
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };

  const handleExport = () => {
    const ts = note.createdAt ? new Date(note.createdAt).toISOString().slice(0, 10) : "note";
    const md = `# Note — ${ts}\n\n${note.text}\n`;
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `note-${ts}.md`; a.click();
    URL.revokeObjectURL(url);
    setOvfOpen(false);
    s.toast("Exported as Markdown");
  };

  return (
    <div className="note-ready-wrap">
      <div className="note-ready-inner">
        {/* Minimal header */}
        <div className="note-hdr">
          <span className="note-ready-label">{noteLabel}</span>
        </div>

        {/* Note text preview (max 4 lines) */}
        <div className="note-ready-body">
          <p className="note-ready-text">{note.text}</p>
        </div>

        {/* Action hierarchy: Insert (single filled primary) > Open note > overflow */}
        <div className="note-ready-cta">
          <button className="btn primary block note-insert-btn" onClick={handleInsert}>
            <Icon name="copy" size={15} /> Insert
          </button>
          <div className="note-ready-sub">
            <button className="btn sm" onClick={() => { s.setExpandedFrom("ready"); s.setNoteView("expanded"); }}>
              <Icon name="external" size={14} /> Open note
            </button>
            <div className="ovf-wrap" style={{ position: "relative" }}>
              <button className="btn sm ghost" aria-label="More — Copy, Export"
                aria-expanded={ovfOpen} onClick={() => setOvfOpen((v) => !v)}>
                <Icon name="more" size={15} />
              </button>
              {ovfOpen && (
                <>
                  <div className="ovf-scrim" onClick={() => setOvfOpen(false)} />
                  <div className="ovf-menu">
                    <button onClick={handleCopy}><Icon name="copy" size={14} /> Copy</button>
                    <button onClick={handleExport}><Icon name="download" size={14} /> Export</button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        <button className="note-new-btn" onClick={() => s.setNoteView(null)}>New note</button>
      </div>
    </div>
  );
}

/* ── Expanded note: full scrollable text + Copy / Export ──────────────── */
function ExpandedNote() {
  const s = useStore();
  const note = s.currentNote;
  if (!note) return null;

  const noteLabel = note.createdAt ? `Note · ${formatHistoryTime(note.createdAt)}` : "Note";

  // Back routing: return to the notes list when opened from there, else to note-ready.
  const handleBack = () => {
    if (s.expandedFrom === "history") {
      s.setNoteView(null);
      s.setView("history");
    } else {
      s.setNoteView("ready");
    }
  };

  const handleCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(note.text)
        .then(() => s.toast("Copied to clipboard"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };

  const handleExport = () => {
    const ts = note.createdAt ? new Date(note.createdAt).toISOString().slice(0, 10) : "note";
    const md = `# Note — ${ts}\n\n${note.text}\n`;
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `note-${ts}.md`; a.click();
    URL.revokeObjectURL(url);
    s.toast("Exported as Markdown");
  };

  return (
    <div className="note-exp-wrap">
      <div className="note-exp-top">
        <button className="ibtn" title="Back" onClick={handleBack}>
          <Icon name="back" size={17} />
        </button>
        <span className="note-exp-title">{noteLabel}</span>
        <div className="note-exp-tools">
          <button className="ibtn" title="Copy" onClick={handleCopy}><Icon name="copy" size={16} /></button>
          <button className="ibtn" title="Export as Markdown" onClick={handleExport}><Icon name="download" size={16} /></button>
        </div>
      </div>
      {/* Search + Times omitted: real data is plain text, no timestamps or speaker lines */}
      {/* TODO(backend): Add search once the engine exposes segment-level data */}
      <div className="note-exp-body scroll">
        <p className="note-exp-text">{note.text}</p>
      </div>
    </div>
  );
}

/* ── Gear menu: on-device toggle · appearance · settings links ────────── */
function GearMenu({ onClose }) {
  const s = useStore();
  const onDevice = modelById(s.model).local;

  const toggleOnDevice = () => {
    if (onDevice) {
      // Switch to the first hosted model that has a key configured.
      const hosted = MODELS.find((m) => !m.local && s.keys[m.brand]);
      if (hosted) {
        s.setModel(hosted.id);
      } else {
        // No provider key is configured — guide the user instead of silently no-op'ing.
        s.toast("Add a provider key first — set one in Model settings.");
        s.setView("model");
        onClose();
      }
    } else {
      s.setModel("faster-whisper/turbo");
    }
  };

  const goTo = (v) => { s.setView(v); onClose(); };

  const settingsItems = [
    { v: "model", label: "Model" },
    { v: "ptt", label: "Push-to-talk" },
    { v: "hotwords", label: "Hotwords" },
    { v: "history", label: "Recent history" },
    { v: "update", label: "App update" },
    { v: "startup", label: "Startup" },
    { v: "advanced", label: "Advanced" },
    { v: "status", label: "Status" },
  ];

  return (
    <>
      {/* Invisible scrim — click outside menu to dismiss */}
      <div className="gear-scrim" onClick={onClose} />
      <div className="gear-menu" role="dialog" aria-label="Settings menu">
        <div className="gear-head t-label">Settings</div>

        {/* Always on-device toggle */}
        <button
          className="gear-row"
          role="switch"
          aria-checked={onDevice}
          onClick={toggleOnDevice}
        >
          <span className="gear-mk">
            Always on-device <span className="gear-mk-note">private</span>
          </span>
          <span className="gear-mv">
            <span className={"gear-switch" + (onDevice ? " on" : "")} />
          </span>
        </button>

        <div className="gear-div" />

        {/* Appearance segmented control */}
        <div className="gear-seg-row">
          <span className="gear-mk">Appearance</span>
          <div className="gear-mini-seg">
            {["light", "dark"].map((th) => (
              <button
                key={th}
                className={s.theme === th ? "on" : ""}
                onClick={() => s.setTheme(th)}
              >
                {th[0].toUpperCase() + th.slice(1)}
              </button>
            ))}
          </div>
        </div>

        <div className="gear-div" />

        {/* Settings navigation entries */}
        {(() => {
          const hasUpdate = !!(s.updateStatus?.updateAvailable || s.updateStatus?.shellStale);
          return settingsItems.map(({ v, label }) => (
            <button key={v} className="gear-row" onClick={() => goTo(v)}>
              <span className="gear-mk">{label}</span>
              {/* Quiet update dot on the "App update" row only */}
              {v === "update" && hasUpdate && <span className="update-dot update-dot-row" aria-label="Update available" />}
              <Icon name="chev" size={15} style={{ color: "var(--subtle)", marginLeft: v === "update" && hasUpdate ? "8px" : "auto" }} />
            </button>
          ));
        })()}
      </div>
    </>
  );
}

/* ======================================================================
   App — root component
   ====================================================================== */
export default function App() {
  // "home" = Breath Cradle capture surface; any VIEWS key = that settings view.
  const [view, setView] = useState("home");
  const [model, setModelState] = useState("faster-whisper/turbo");
  const [keys, setKeys] = useState({ openai: false, xai: false, gemini: false });
  const [shortcut, setShortcutState] = useState(["Ctrl (R)"]);
  const [activation, setActivationState] = useState("hold");
  const [device] = useState("Default device");
  const [device2, setDevice2State] = useState("auto");
  const [compute] = useState("int8");
  const [hotwords, setHotwords] = useState(["AcmeWidget", "OpenClaw", "Stalwart"]);
  const [history, setHistory] = useState(() => {
    const now = Date.now();
    // Newest-first: matches the real backend ordering and pushHistory behaviour.
    return [
      { id: "h3", createdAt: now - 6 * 60 * 1000, text: "Reminder to follow up with the Stalwart team about the OAuth scopes this afternoon." },
      { id: "h2", createdAt: now - 38 * 60 * 1000, text: "Let's move the sync to Thursday and keep Friday clear for the demo build." },
      { id: "h1", createdAt: now - 2 * 60 * 60 * 1000, text: "Draft a short note thanking the beta testers and ask them for crash reports." },
    ];
  });
  // Default to system color scheme when no explicit pref is saved (Stage 3 parity with prototype).
  const [theme, setThemeState] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return "light";
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [startup, setStartupState] = useState(true);
  const [trayOnly, setTrayOnlyState] = useState(true);
  const [overlay, setOverlayState] = useState(true);
  const [sound, setSoundState] = useState(false);
  const [ambient, setAmbientState] = useState(true);
  const [recording, setRecording] = useState(false);
  const [noteRecording, setNoteRecording] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [noteElapsed, setNoteElapsed] = useState(0); // seconds since noteRecording started
  const [transcript, setTranscript] = useState({ phase: null, text: "", stale: false });
  const [typing, setTyping] = useState(false);
  const [targetText, setTargetText] = useState("");
  const [palette, setPalette] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [capturing, setCapturing] = useState(false);
  const [version, setVersion] = useState(DEFAULT_VERSION);
  const [updateStatus, setUpdateStatus] = useState(() => mockUpdateStatus(DEFAULT_VERSION));
  const [platform, setPlatform] = useState("gnome");
  const [live, setLive] = useState(false);
  const [gearOpen, setGearOpen] = useState(false);
  // Note surface state machine: null=home, "processing"=transcribing, "ready"=note, "expanded"=full view
  const [noteView, setNoteView] = useState(null);
  const [currentNote, setCurrentNote] = useState(null);
  // expandedFrom: where the expanded view was opened from — "ready" (note-ready surface) or
  // "history" (notes list). Controls what the back button does when leaving ExpandedNote.
  const [expandedFrom, setExpandedFrom] = useState("ready");

  // Detect prefers-reduced-motion for the BreathCradle.
  const [reduced, setReduced] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (e) => setReduced(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Track whether the user has explicitly picked a theme (Light/Dark via gear or loaded from prefs).
  // Only the system follower uses this; an explicit pick must always win.
  const explicitThemeRef = useRef(false);

  // Live-follow the OS color scheme, but only when no explicit user pref is set — mirrors the
  // reduced-motion listener pattern. An explicit pick (or a saved pref on hydration) locks the theme.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e) => {
      if (!explicitThemeRef.current) setThemeState(e.matches ? "dark" : "light");
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // ---- refs to dodge stale closures in global listeners ----
  const recRef = useRef(false); recRef.current = recording;
  const tgtRef = useRef(""); tgtRef.current = targetText;
  const actRef = useRef(activation); actRef.current = activation;
  const capRef = useRef(false); capRef.current = capturing;
  const transcriptIdRef = useRef(null);
  const terminalTranscriptIdsRef = useRef(new Set());
  const terminalTranscriptIdOrderRef = useRef([]);
  // noteViewRef: stale-closure-safe read of noteView inside the SSE handler.
  const noteViewRef = useRef(null); noteViewRef.current = noteView;
  // watchdogRef: 60 s safety-net timer; cleared on every normal resolution path.
  const watchdogRef = useRef(null);

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);
  useEffect(() => { document.documentElement.setAttribute("data-ambient", ambient ? "on" : "off"); }, [ambient]);

  // ---- note-recording elapsed timer ----
  useEffect(() => {
    if (!noteRecording) { setNoteElapsed(0); return; }
    const id = setInterval(() => setNoteElapsed((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [noteRecording]);

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
      if (ev.type === "recording") {
        setRecording(!!ev.active);
        if (ev.active) setTranscript({ phase: null, text: "", stale: false });
      }
      else if (ev.type === "note-recording") {
        setNoteRecording(!!ev.active);
        if (ev.active) {
          // New recording started — clear any stale watchdog, reset note surface.
          clearWatchdog();
          setNoteView(null);
          setCurrentNote(null);
        } else {
          // Recording stopped — show Transcribing… and arm the safety-net watchdog.
          setNoteView("processing");
          armWatchdog();
        }
      }
      else if (ev.type === "note") {
        // The backend now sends a `status` field on every terminal note outcome.
        // Old daemons without the field default to "ok" for backward compatibility.
        const status = ev.status || (ev.text ? "ok" : "empty");
        clearWatchdog();
        if (status === "ok" && typeof ev.text === "string" && ev.text) {
          setNoteText(ev.text);
          const note = { id: ev.id || "n" + Date.now(), text: ev.text, createdAt: ev.createdAt || new Date().toISOString() };
          setCurrentNote(note);
          setNoteView("ready");
          toast("Conversation note saved");
        } else if (status === "empty") {
          setNoteView(null);
          toast("No speech detected", { bad: true });
        } else if (status === "failed") {
          setNoteView(null);
          toast("Couldn't transcribe — try again", { bad: true });
        }
      }
      else if (ev.type === "transcript") {
        const eventId = Number.isInteger(ev.recording_id) ? ev.recording_id : null;
        if (eventId !== null && transcriptIdRef.current !== null && eventId < transcriptIdRef.current) {
          if (transcriptIdRef.current - eventId > TERMINAL_TRANSCRIPT_ID_LIMIT) resetTranscriptOrdering();
          else return;
        }
        if (eventId !== null && terminalTranscriptIdsRef.current.has(eventId) && ev.phase !== "final" && !ev.stale) return;
        if (eventId !== null) transcriptIdRef.current = eventId;
        if (eventId !== null && (ev.phase === "final" || ev.stale)) markTerminalTranscriptId(eventId);
        if (ev.stale) {
          // Belt-and-suspenders: _fail_recording_session fires a stale transcript
          // AND a note "failed" event. Resolve the view here (silent — the note
          // "failed" handler is the authoritative toaster to avoid a duplicate).
          // Old daemons without note "failed": UI unblocks but no toast; the 60 s
          // watchdog was also cleared here so it won't double-fire.
          if (noteViewRef.current === "processing") {
            clearWatchdog();
            setNoteView(null);
          }
          setTranscript({ phase: ev.phase || "final", text: "", stale: true });
        } else if (typeof ev.text === "string") {
          setTranscript({ phase: ev.phase || "partial", text: ev.text, stale: false });
        }
      } else if (ev.type === "history-changed") {
        ipc.getState().then((st) => {
          if (!st) return;
          const entries = mapHistory(st);
          setHistory(entries);
          // Fallback: if still waiting for a "note" event, resolve from latest history.
          setNoteView((nv) => {
            if (nv === "processing" && entries.length > 0) {
              clearWatchdog();
              setCurrentNote(entries[0]);
              return "ready";
            }
            return nv;
          });
        });
      }
    });
    return () => { cancelled = true; resetTranscriptOrdering(); clearWatchdog(); unsub && unsub(); };
  }, []);

  const resetTranscriptOrdering = () => {
    transcriptIdRef.current = null;
    terminalTranscriptIdsRef.current.clear();
    terminalTranscriptIdOrderRef.current = [];
  };

  const markTerminalTranscriptId = (id) => {
    const terminalIds = terminalTranscriptIdsRef.current;
    if (!terminalIds.has(id)) {
      terminalIds.add(id);
      terminalTranscriptIdOrderRef.current.push(id);
    }
    while (terminalTranscriptIdOrderRef.current.length > TERMINAL_TRANSCRIPT_ID_LIMIT) {
      const expired = terminalTranscriptIdOrderRef.current.shift();
      if (!terminalTranscriptIdOrderRef.current.includes(expired)) terminalIds.delete(expired);
    }
  };

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
    if (st.notes && typeof st.notes.recording === "boolean") setNoteRecording(st.notes.recording);
    if (st.prefs) {
      if (st.prefs.theme && st.prefs.theme !== "system") { explicitThemeRef.current = true; setThemeState(st.prefs.theme); }
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

  // ---- Note-surface watchdog (60 s safety net for missing terminal events) ----
  // clearWatchdog and armWatchdog are stable (useCallback with [] / [clearWatchdog,toast])
  // so the SSE useEffect can safely close over them even though it has [] deps.
  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) { clearTimeout(watchdogRef.current); watchdogRef.current = null; }
  }, []);
  const armWatchdog = useCallback(() => {
    clearWatchdog();
    watchdogRef.current = setTimeout(() => {
      watchdogRef.current = null;
      // Return to home only if we're still stuck in processing — never abort a ready/expanded note.
      setNoteView((nv) => {
        if (nv === "processing") toast("Transcription timed out — try again", { bad: true });
        return nv === "processing" ? null : nv;
      });
    }, 60_000);
  }, [clearWatchdog, toast]);

  // ---- persisting mutations (optimistic local + IPC when live) ----
  const persist = (payload) => { if (ipc.isLive()) ipc.patchConfig(payload).catch(() => toast("Could not save change", { bad: true })); };
  const persistOrThrow = (payload) => ipc.isLive() ? ipc.patchConfig(payload) : Promise.resolve(null);

  const setModel = (id) => { setModelState(id); const m = modelById(id); persist({ model: { backend: m.backend, model: id.split("/").slice(1).join("/") } }); };
  const setShortcut = async (arr) => {
    const previous = shortcut;
    setShortcutState(arr);
    try {
      await persistOrThrow({ shortcut: { combo: comboToToken(arr), activation } });
    } catch (e) {
      setShortcutState(previous);
      toast("Could not save change", { bad: true });
      throw e;
    }
  };
  const setActivation = (v) => { setActivationState(v); persist({ shortcut: { activation: v } }); };
  const setTheme = (v) => { explicitThemeRef.current = true; setThemeState(v); persist({ prefs: { theme: v } }); };
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

  const toggleNoteRecording = () => {
    if (!ipc.isLive()) {
      if (noteRecording) {
        // Stop: show Processing surface briefly, then resolve to note-ready.
        setNoteRecording(false);
        setNoteView("processing");
        armWatchdog();
        const demo = "Let's capture this as a project note. Add the follow-up action for tomorrow.";
        setTimeout(() => {
          clearWatchdog();
          const note = { id: "n" + Date.now(), text: demo, createdAt: new Date().toISOString() };
          setNoteText(demo);
          setCurrentNote(note);
          pushHistory(demo);
          setNoteView("ready");
          toast("Conversation note saved");
        }, 800);
      } else {
        clearWatchdog();
        setNoteRecording(true);
        setNoteView(null);
        setCurrentNote(null);
        toast("Note recording started");
      }
      return;
    }
    ipc.toggleNoteRecording()
      .then((r) => setNoteRecording(!!r.recording))
      .catch((e) => toast(e.message || "Could not toggle note recording", { bad: true }));
  };

  const runDoctor = (cb) => {
    if (ipc.isLive()) { ipc.runDoctor().then(cb).catch(() => cb(mockDoctor())); }
    else cb(mockDoctor());
  };
  const checkUpdates = () => {
    setUpdateStatus((u) => ({ ...u, checking: true, error: null }));
    if (!ipc.isLive()) {
      const status = { ...mockUpdateStatus(version), checked: true, checking: false };
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
  const startUpdate = () => {
    setUpdateStatus((u) => ({ ...u, updating: true, error: null }));
    if (!ipc.isLive()) {
      window.open("https://github.com/arcforgelabs/dictate/releases", "_blank", "noopener,noreferrer");
      setUpdateStatus((u) => ({ ...u, updating: false }));
      toast("Opened latest release");
      return;
    }
    ipc.startUpdate()
      .then((flow) => {
        setUpdateStatus((u) => ({ ...u, updating: false }));
        if (flow?.url) {
          window.open(flow.url, "_blank", "noopener,noreferrer");
        }
        toast(flow?.message || (flow?.started ? "Update started" : "Opened latest release"));
      })
      .catch((e) => {
        setUpdateStatus((u) => ({ ...u, updating: false, error: e.message || "Could not start update" }));
        toast("Could not start update", { bad: true });
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

  function mockUpdateStatus(v) {
    return {
      currentVersion: v, latestVersion: v, updateAvailable: false, checked: false,
      platform: "linux", installKind: "linux-package",
      engine: { name: "engine", current: v, latest: v, path: "~/.local/bin/dictate", stale: false },
      shell: { name: "shell", current: v, latest: v, path: "/usr/bin/dictate-ui-shell", stale: false },
      shellStale: false, phase: "current", actions: ["check", "open_docs"],
      commands: { release: "https://github.com/arcforgelabs/dictate/releases" },
    };
  }

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

  // ---- global keyboard: ⌘K palette + push-to-talk demo (Ctrl (R)) ----
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
    recording, noteRecording, noteText, toggleNoteRecording,
    transcript, typing, targetText, dictateStart, dictateStop, dictateOnce,
    palette, setPalette, toasts, toast, dismiss, micConnected: true, setCapturing,
    runDoctor, version, updateStatus, checkUpdates, startUpdate, platform,
    // Note Capture additions
    gearOpen, setGearOpen, noteElapsed, reduced,
    noteView, setNoteView, currentNote, setCurrentNote,
    expandedFrom, setExpandedFrom,
  };

  // Resolve the current settings view component (null when on capture home).
  const Current = view !== "home" ? VIEWS[view] : null;

  return (
    <StoreCtx.Provider value={store}>
      <div className={"win " + platform} ref={winRef}>
        <TitleBar
          platform={platform}
          onSearch={() => setPalette(true)}
          onGear={() => setGearOpen(true)}
          hasUpdate={!!(updateStatus.updateAvailable || updateStatus.shellStale)}
        />

        <div className="shell">
          {view === "home" ? (
            noteView === "processing" ? <NoteProcessing /> :
            noteView === "ready"      ? <NoteReady /> :
            noteView === "expanded"   ? <ExpandedNote /> :
            <CaptureHome />
          ) : (
            /* Settings view: full-window with a back button returning to capture home.
               The notes list (history) renders its own header and takes full height. */
            <div className="note-settings-wrap">
              {view === "history" ? (
                /* Notes list: own .notes-top header, no shared bar. */
                Current && <Current />
              ) : (
                <>
                  <div className="note-settings-bar">
                    <button className="btn ghost sm" onClick={() => setView("home")}>
                      <Icon name="back" size={15} />Back
                    </button>
                    <span className="note-settings-title">{VIEW_LABELS[view] || view}</span>
                  </div>
                  <div className="scroll">
                    {Current && <Current />}
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* GearMenu: position:absolute anchors to .win just below the titlebar */}
        {gearOpen && <GearMenu onClose={() => setGearOpen(false)} />}
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

// Display keys (["Ctrl","Shift","R"] / ["Ctrl (R)"]) → engine combo token.
function comboToToken(arr) {
  const map = { "Ctrl": "ctrl", "Ctrl (R)": "ctrl_r", "Right Ctrl": "ctrl_r", "Ctrl (L)": "ctrl_l",
    "Alt": "alt", "Shift": "shift", "Super": "super" };
  return arr.map((k) => map[k] || k.toLowerCase()).join("+");
}
