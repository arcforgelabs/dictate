// App.jsx — Note Capture shell. Home = Breath Cradle capture surface.
// The GUI is do-it-for-them: there is no settings menu. The home carries one
// control — the privacy pill (on-device vs online) — plus a Notes button; the
// only non-home view is the Notes list. All advanced config lives in the
// `dictate config` CLI. ⌘K palette = Notes + a few daily actions.
import { useState, useEffect, useRef, useCallback } from "react";
import { Icon } from "./icons.jsx";
import { Kbd, Toggle, Tooltip } from "./primitives.jsx";
import { StoreCtx, useStore, modelById, DEMO_PHRASES, formatHistoryTime, XAI_API_KEY_AGENT_INSTRUCTIONS } from "./store.jsx";
import { VIEWS, HomeBar, NotebookToggle } from "./views.jsx";
import { ListeningHUD, CommandPalette, Toasts } from "./overlays.jsx";
import TitleBar from "./platform/TitleBar.jsx";
import { BreathCradle } from "./visualizers.jsx";
import { ipc } from "./ipc.js";

const DEFAULT_VERSION = "2026.6.23";
const TERMINAL_TRANSCRIPT_ID_LIMIT = 64;

// Format seconds → m:ss or h:mm:ss (mirrors the design's fmt helper).
function fmtSecs(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`;
}

/* ── Privacy control: one label + toggle on the home — where audio is transcribed. ── */
const ONLINE_MODEL = "xai/grok-speech-to-text";
const PRIVATE_MODEL = "faster-whisper/turbo";

function PrivacyPill() {
  const s = useStore();
  const online = s.providerMode === "online";
  const degraded = s.providerDegraded;
  const privateOn = !online || degraded;

  const onToggle = (on) => {
    if (on === privateOn) return;
    if (on) {
      s.setModel(PRIVATE_MODEL);
      return;
    }
    if (!s.keys.xai) {
      s.toast("Requires Dictate Pro or API key.", {
        bad: true,
        ms: 12_000,
        copy: XAI_API_KEY_AGENT_INSTRUCTIONS,
      });
      return;
    }
    s.setModel(ONLINE_MODEL);
  };

  return (
    <Tooltip label={privateOn ? "Private mode" : "Cloud mode"}>
      <div className={"privpill" + (degraded ? " degraded" : "")}>
        <Toggle on={privateOn} onChange={onToggle} />
        <span className="priv-icon" aria-label={privateOn ? "Private mode" : "Cloud mode"}>
          <Icon name={privateOn ? "shield" : "cloud"} size={23} />
        </span>
      </div>
    </Tooltip>
  );
}

/* ── Update affordance: one quiet pill in the home bar. The primary action is
   the only thing shown; Skip / Later are revealed on proximity (hover/focus).
   Skip suppresses until a newer version; Later returns on next launch. ─────── */
const UPDATE_LABEL = {
  available: "Update available",
  preparing: "Preparing update…",
  ready: "Update & restart",
  installing: "Updating…",
  error: "Update failed",
};
function UpdatePill() {
  const s = useStore();
  if (!s.updateVisible) return null;
  const phase = s.updatePhase;
  return (
    <div className={"updpill phase-" + phase}>
      {/* Revealed to the LEFT on proximity so the primary button never moves. */}
      <div className="upd-more">
        <button className="upd-mini" onClick={s.dismissUpdate} title="Remind me on next launch">Later</button>
        <button className="upd-mini" onClick={s.skipUpdate} title="Skip this version">Skip</button>
      </div>
      <button
        className="upd-main"
        onClick={s.runUpdate}
        disabled={phase === "installing"}
        title={phase === "ready" ? "Install the update and restart" : "Update Dictate"}
      >
        <span className="upd-dot" aria-hidden="true" />
        <span className="upd-label">{UPDATE_LABEL[phase] || "Update available"}</span>
      </button>
    </div>
  );
}

/* ── Getting-started keyboard: a quiet, aligned keyboard graphic that points at
   Right Ctrl. Shown on the empty home (no notes yet) to teach the one key. ──── */
function GsKeyboard() {
  const row = (n) => Array.from({ length: n }, (_, i) => <span className="k" key={i} />);
  return (
    <div className="gs-kbd" aria-hidden="true">
      <div className="gs-row fn">{row(13)}</div>
      <div className="gs-row">{row(13)}</div>
      <div className="gs-row">{row(11)}<span className="k wide" /></div>
      <div className="gs-row"><span className="k wide" />{row(9)}<span className="k wide" /></div>
      <div className="gs-row">
        <span className="k" /><span className="k" /><span className="k" />
        <span className="k space" /><span className="k" /><span className="k hot">Ctrl</span>
        <span className="gs-arrows">
          <span className="ar-top"><i className="ak" /></span>
          <span className="ar-bot"><i className="ak" /><i className="ak" /><i className="ak" /></span>
        </span>
      </div>
    </div>
  );
}

/* ── Capture home: header + Breath Cradle + feedback ─────────────────── */
function CaptureHome() {
  const s = useStore();
  return (
    <div className="note-home">
      {/* Home chrome: the privacy truth (the one human control) + Notes. No gear —
          the GUI is do-it-for-them; advanced config lives in `dictate config`. */}
      <HomeBar left={<PrivacyPill />} right={<UpdatePill />} />
      <div className="note-home-inner">
        {/* Cradle + feedback */}
        <div className="note-screen">
          {/* cradle-wrap: positions the one-shot flash ring relative to the cradle */}
          <div className="cradle-wrap">
            {s.flash && (
              <span className={"flashring " + s.flash.to} key={s.flash.id} aria-hidden="true" />
            )}
            <BreathCradle
              session={s.noteRecording}
              active={s.noteRecording && !s.notePaused}
              paused={s.notePaused}
              reduced={s.reduced}
              onStart={s.startNoteRecording}
              onPause={s.pauseNoteRecording}
              onResume={s.resumeNoteRecording}
            />
          </div>
          <div className="note-feedback">
            {s.noteRecording && !s.notePaused ? (
              <>
                <div className="note-status live">Recording</div>
                <div className="note-timer t-mono">{fmtSecs(s.noteElapsed)}</div>
                <div className="note-preview" aria-live="polite">
                  {s.providerDegraded
                    ? <span className="note-preview-wait">On-device transcript — ready when you finish.</span>
                    : s.transcript?.text
                      ? <><span>{s.transcript.text}</span><span className="note-caret" /></>
                      : <span className="note-preview-wait">Listening for speech…</span>}
                </div>
              </>
            ) : s.noteRecording && s.notePaused ? (
              <>
                <div className="note-status paused">Paused</div>
                <div className="note-timer t-mono">{fmtSecs(s.noteElapsed)}</div>
                <div className="note-status-sub t-mono">Hover the mic to resume, or finish the note.</div>
                <button type="button" className="note-finish-btn" onClick={s.finishNoteRecording}>
                  Finish note
                </button>
              </>
            ) : (
              <>
                <div className="note-status">Ready to dictate</div>
                <div className="note-status-sub t-mono">Press the mic and speak.</div>
                <div className="note-status-hint t-mono">or hold {s.shortcut.join(" + ")}</div>
                {/* Getting started: teach the key when there are no notes yet */}
                {(!s.history || s.history.length === 0) && <GsKeyboard />}
                {/* Live push-to-talk transcript */}
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
          {/* Degraded recording strip: amber, visible while recording on local fallback */}
          {s.noteRecording && !s.notePaused && s.providerDegraded && (
            <div className="note-longstrip amber t-mono">
              <span className="wdot" />
              On-device · reconnecting…
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Copy-last row: quiet chip below the cradle for fast reuse of the last note ── */
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
      </span>
    </button>
  );
}

/* ── Transcribing… (indeterminate, shown between stop and note event) ── */
function NoteProcessing() {
  return (
    <div className="note-proc-wrap">
      <div className="note-proc-inner">
        <div className="note-status" style={{ marginBottom: 6 }}>Transcribing…</div>
        <div className="note-status-sub t-mono">Turning your words into a note.</div>
        <div className="note-proc-bar" aria-hidden="true"><span /></div>
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

  const handleCopy = () => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(note.text)
        .then(() => s.toast("Copied to clipboard"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };

  // Export dictation as a Markdown file via the OS save dialog.
  const handleExport = async () => {
    const ts = note.createdAt ? new Date(note.createdAt).toISOString().slice(0, 10) : "note";
    const name = `dictate-note-${ts}.md`;
    const md = `# Note — ${ts}\n\n${note.text}\n`;
    try {
      const saved = await ipc.saveTextFile(name, md);
      if (saved) s.toast("Saved as Markdown");
    } catch {
      s.toast("Could not save file", { bad: true });
    }
  };

  return (
    <div className="note-exp-wrap">
      <div className="notes-search note-exp-top">
        <span className="note-exp-title">{noteLabel}</span>
        <span className="notes-search-grow" aria-hidden="true" />
        <button className="ibtn" title="Copy" onClick={handleCopy}><Icon name="copy" size={16} /></button>
        <button className="ibtn" title="Export as Markdown" onClick={handleExport}><Icon name="download" size={16} /></button>
        <NotebookToggle />
      </div>
      {/* Search + Times omitted: real data is plain text, no timestamps or speaker lines */}
      {/* TODO(backend): Add search once the engine exposes segment-level data */}
      <div className="note-exp-body scroll">
        <p className="note-exp-text">{note.text}</p>
      </div>
    </div>
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
      { id: "h3", createdAt: now - 6 * 60 * 1000, text: "Reminder to send the meeting summary to the team this afternoon." },
      { id: "h2", createdAt: now - 38 * 60 * 1000, text: "Let's move the planning session to Thursday and keep Friday clear for focused work." },
      { id: "h1", createdAt: now - 2 * 60 * 60 * 1000, text: "Draft a short note thanking the reviewers and ask them for feedback." },
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
  const [notePaused, setNotePaused] = useState(false);
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
  // Update affordance state machine: idle → available → preparing → ready → installing (→ error).
  // The update prepares in the background so the click is instant once "ready".
  const [updatePhase, setUpdatePhase] = useState("idle");
  // Skip persists across launches (suppress until a newer version); Dismiss is session-only.
  const [skippedVersion, setSkippedVersion] = useState(() => {
    try { return (typeof localStorage !== "undefined" && localStorage.getItem("dictate.skippedVersion")) || null; }
    catch { return null; }
  });
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [platform, setPlatform] = useState("gnome");
  const [live, setLive] = useState(false);
  // Note surface state machine: null=home, "processing"=transcribing, "expanded"=full note view
  const [noteView, setNoteView] = useState(null);
  const [currentNote, setCurrentNote] = useState(null);
  // Provider health: on-device is always-available floor; degraded = fell back from the online provider.
  const [providerHealthy, setProviderHealthy] = useState(true);
  const [providerStatus, setProviderStatus] = useState("ok");
  const [providerMode, setProviderMode] = useState("private");
  const [providerDegraded, setProviderDegraded] = useState(false);
  const [providerReason, setProviderReason] = useState(null);
  const [providerActive, setProviderActive] = useState(null);
  // flash: one-shot ring pulse on provider switch (local=amber, remote=green). Never silent.
  const [flash, setFlash] = useState(null);
  // expandedFrom: where the expanded view was opened from — "capture" (just dictated) or
  // "history" (notes list).
  const [expandedFrom, setExpandedFrom] = useState("capture");

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
  // Flash ring: stable refs so triggerFlash can be useCallback([]) and safe in SSE handler.
  const flashIdRef = useRef(0);
  const flashTimerRef = useRef(null);

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);
  useEffect(() => { document.documentElement.setAttribute("data-ambient", ambient ? "on" : "off"); }, [ambient]);

  // ---- note-recording elapsed timer ----
  useEffect(() => {
    if (!noteRecording || notePaused) { if (!noteRecording) setNoteElapsed(0); return; }
    const id = setInterval(() => setNoteElapsed((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [noteRecording, notePaused]);

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
        if (ev.paused) {
          setNoteRecording(true);
          setNotePaused(true);
        } else if (ev.active) {
          setNoteRecording(true);
          setNotePaused(false);
          // New recording started — clear any stale watchdog, reset note surface.
          clearWatchdog();
          setNoteView(null);
          setCurrentNote(null);
        } else {
          setNoteRecording(false);
          setNotePaused(false);
          // Recording finished — show Transcribing… and arm the safety-net watchdog.
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
          setExpandedFrom("capture");
          setNoteView("expanded");
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
      } else if (ev.type === "provider-degraded") {
        // Online provider failed — fell back to on-device. Visible switch: flash + amber toast.
        setProviderDegraded(true);
        setProviderReason(ev.reason || null);
        setProviderActive(ev.active || "faster-whisper");
        triggerFlash("local");
        toast("Switched to on-device", { tone: "amber", icon: "cloudoff" });
      } else if (ev.type === "provider-recovered") {
        // Online provider reachable again — auto-recovered. Visible switch: flash + green toast.
        setProviderDegraded(false);
        setProviderActive(ev.active || "online");
        triggerFlash("remote");
        toast("Back online", { icon: "cloud" });
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
              setExpandedFrom("capture");
              return "expanded";
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
    if (st.notes && typeof st.notes.paused === "boolean") setNotePaused(st.notes.paused);
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
    if (st.providerHealth) {
      const ph = st.providerHealth;
      setProviderHealthy(!!ph.healthy);
      setProviderStatus(ph.status || "ok");
      setProviderMode(ph.mode || "private");
      setProviderDegraded(!!ph.degraded);
      if (ph.reason !== undefined) setProviderReason(ph.reason || null);
      if (ph.active) setProviderActive(ph.active);
    }
  }, []);

  const mapHistory = (st) =>
    (st.history || []).map((h) => ({ id: h.id, text: h.text, createdAt: h.createdAt }));

  // ---- toasts ----
  const dismiss = (id) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const toast = useCallback((msg, opts = {}) => {
    const id = "t" + Date.now() + Math.random();
    setToasts((ts) => [...ts, { id, msg, ...opts }]);
    const ms = opts.ms ?? (opts.undo ? 5000 : 2600);
    setTimeout(() => dismiss(id), ms);
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
      // Return to home only if we're still stuck in processing — never abort an expanded note.
      setNoteView((nv) => {
        if (nv === "processing") toast("Transcription timed out — try again", { bad: true });
        return nv === "processing" ? null : nv;
      });
    }, 60_000);
  }, [clearWatchdog, toast]);

  // ---- persisting mutations (optimistic local + IPC when live) ----
  const persist = (payload) => { if (ipc.isLive()) ipc.patchConfig(payload).catch(() => toast("Could not save change", { bad: true })); };
  const persistOrThrow = (payload) => ipc.isLive() ? ipc.patchConfig(payload) : Promise.resolve(null);

  const setModel = (id) => {
    setModelState(id);
    const m = modelById(id);
    // Optimistically update provider mode when the model changes.
    // Private (local) models are always healthy; switching clears any degraded state immediately.
    const newMode = m.local ? "private" : "online";
    setProviderMode(newMode);
    if (m.local) { setProviderHealthy(true); setProviderDegraded(false); }
    persist({ model: { backend: m.backend, model: id.split("/").slice(1).join("/") } });
  };
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

  // triggerFlash: one-shot ring pulse on the cradle on every provider switch. Never silent.
  const triggerFlash = useCallback((to) => {
    const id = ++flashIdRef.current;
    setFlash({ to, id });
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashTimerRef.current = setTimeout(() => {
      setFlash((f) => (f && f.id === id ? null : f));
      flashTimerRef.current = null;
    }, 850);
  }, []);

  const hydrateProviderHealth = useCallback((ph) => {
    if (!ph) return;
    setProviderHealthy(!!ph.healthy);
    setProviderStatus(ph.status || "ok");
    setProviderMode(ph.mode || "private");
    setProviderDegraded(!!ph.degraded);
    if (ph.reason !== undefined) setProviderReason(ph.reason || null);
    if (ph.active) setProviderActive(ph.active);
  }, []);

  const applyNoteState = (r) => {
    if (!r) return;
    if (typeof r.recording === "boolean") setNoteRecording(r.recording);
    if (typeof r.paused === "boolean") setNotePaused(r.paused);
  };

  const startNoteRecording = () => {
    if (noteRecording) return;
    if (!ipc.isLive()) {
      clearWatchdog();
      setNotePaused(false);
      setNoteRecording(true);
      setNoteView(null);
      setCurrentNote(null);
      toast("Note recording started");
      return;
    }
    ipc.startNoteRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not start note recording", { bad: true }));
  };

  const pauseNoteRecording = () => {
    if (!noteRecording || notePaused) return;
    if (!ipc.isLive()) {
      setNotePaused(true);
      return;
    }
    ipc.pauseNoteRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not pause note recording", { bad: true }));
  };

  const resumeNoteRecording = () => {
    if (!noteRecording || !notePaused) return;
    if (!ipc.isLive()) {
      setNotePaused(false);
      return;
    }
    ipc.resumeNoteRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not resume note recording", { bad: true }));
  };

  const finishNoteRecording = () => {
    if (!noteRecording) return;
    if (!ipc.isLive()) {
      setNotePaused(false);
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
        setExpandedFrom("capture");
        setNoteView("expanded");
        toast("Conversation note saved");
      }, 800);
      return;
    }
    ipc.stopNoteRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not finish note recording", { bad: true }));
  };

  const toggleNoteRecording = () => {
    if (!noteRecording) startNoteRecording();
    else if (notePaused) resumeNoteRecording();
    else finishNoteRecording();
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
        // Installed in-app: bring the new shell + engine up together.
        if (flow?.mode === "installed" || (flow?.actions || []).includes("restart")) {
          toast(flow?.message || "Update installed — restarting…");
          ipc.restartApp();
          return;
        }
        if (flow?.mode === "error") {
          const detail = flow.errorDetail || flow.message || "Could not complete the update";
          setUpdateStatus((u) => ({ ...u, error: detail }));
          toast(flow?.message || "Could not complete the update", { bad: true });
          return;
        }
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
    // Shell + engine are one unit at one version — no separate component tracking.
    return {
      currentVersion: v, latestVersion: v, updateAvailable: false, checked: false,
      platform: "linux", installKind: "linux-package",
      phase: "current", actions: ["check", "open_docs"],
      commands: { release: "https://github.com/arcforgelabs/dictate/releases" },
    };
  }

  // ---- update affordance: skip / dismiss / run ----
  // Skip = suppress until a newer version (persisted). Dismiss = until next launch (session).
  const skipUpdate = () => {
    const v = updateStatus.latestVersion;
    if (v) { setSkippedVersion(v); try { localStorage.setItem("dictate.skippedVersion", v); } catch { /* ignore */ } }
    setUpdatePhase("idle");
    toast("Skipped this version");
  };
  const dismissUpdate = () => { setUpdateDismissed(true); };
  const runUpdate = () => {
    if (updatePhase === "installing") return;
    setUpdatePhase("installing");
    if (!ipc.isLive()) {
      // Mock: can't actually restart a browser tab — simulate the install + handoff.
      setTimeout(() => { toast("Updated — restarting…"); setUpdateDismissed(true); setUpdatePhase("idle"); }, 1600);
      return;
    }
    startUpdate(); // download (if not prepared) → pkexec install → restart_app
  };

  // ---- launch-time update flow: silent check, prepare in the background ----
  useEffect(() => {
    if (!ipc.isLive()) {
      // Mock so the affordance is reviewable on the dev server: available → preparing → ready.
      const t1 = setTimeout(() => {
        setUpdateStatus((u) => ({ ...u, updateAvailable: true, latestVersion: "2026.7.1", checked: true }));
        setUpdatePhase((p) => (p === "idle" ? "available" : p));
      }, 900);
      const t2 = setTimeout(() => setUpdatePhase((p) => (p === "available" ? "preparing" : p)), 2600);
      const t3 = setTimeout(() => setUpdatePhase((p) => (p === "preparing" ? "ready" : p)), 5200);
      return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
    }
    // Live: silent check (no toast); surface the pill if an update exists.
    let cancelled = false;
    ipc.checkUpdates().then((st) => {
      if (cancelled || !st || !st.updateAvailable) return;
      setUpdateStatus((u) => ({ ...u, ...st }));
      setUpdatePhase("available");
      // TODO(backend): a /api/update/prepare endpoint can pre-download in the
      // background and flip the phase to "ready"; until then the Update click
      // runs prepare+install in one step via startUpdate().
    }).catch(() => {});
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // The pill shows only when an update exists, isn't skipped, and isn't dismissed this session.
  const updateVisible = updatePhase !== "idle" && !updateDismissed
    && !!updateStatus.updateAvailable
    && (!skippedVersion || updateStatus.latestVersion !== skippedVersion);

  const store = {
    view, setView, model, setModel, keys, addKey, saveKey, shortcut, setShortcut, activation, setActivation,
    device, device2, setDevice2, compute, hotwords, addHotword, removeHotword,
    history, clearHistory, theme, setTheme, startup, setStartup, trayOnly, setTrayOnly,
    overlay, setOverlay, sound, setSound, ambient, setAmbient,
    recording, noteRecording, notePaused, noteText,
    startNoteRecording, pauseNoteRecording, resumeNoteRecording, finishNoteRecording, toggleNoteRecording,
    transcript, typing, targetText, dictateStart, dictateStop, dictateOnce,
    palette, setPalette, toasts, toast, dismiss, micConnected: true, setCapturing,
    runDoctor, version, updateStatus, checkUpdates, startUpdate, platform,
    // Update affordance
    updatePhase, updateVisible, runUpdate, skipUpdate, dismissUpdate,
    // Note Capture additions
    noteElapsed, reduced,
    noteView, setNoteView, currentNote, setCurrentNote,
    expandedFrom, setExpandedFrom,
    // Provider health — on-device is always available; degraded = fell back from the online provider
    providerHealthy, providerStatus, providerMode,
    providerDegraded, providerReason, providerActive,
    flash, hydrateProviderHealth,
  };

  // Resolve the current settings view component (null when on capture home).
  const Current = view !== "home" ? VIEWS[view] : null;

  return (
    <StoreCtx.Provider value={store}>
      <div className={"win " + platform} ref={winRef}>
        <TitleBar
          platform={platform}
          hasUpdate={!!updateStatus.updateAvailable}
        />

        <div className="shell">
          {view === "home" ? (
            noteView === "processing" ? <NoteProcessing /> :
            noteView === "expanded"   ? <ExpandedNote /> :
            <CaptureHome />
          ) : (
            /* The only non-home view is the Notes list — it renders its own header. */
            <div className="note-settings-wrap">
              {Current && <Current />}
            </div>
          )}
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

// Display keys (["Ctrl","Shift","R"] / ["Ctrl (R)"]) → engine combo token.
function comboToToken(arr) {
  const map = { "Ctrl": "ctrl", "Ctrl (R)": "ctrl_r", "Right Ctrl": "ctrl_r", "Ctrl (L)": "ctrl_l",
    "Alt": "alt", "Shift": "shift", "Super": "super", "D": "d" };
  return arr.map((k) => map[k] || k.toLowerCase()).join("+");
}
