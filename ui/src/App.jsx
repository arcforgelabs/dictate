// App.jsx — Note Capture shell. Home = Breath Cradle capture surface.
// The GUI is do-it-for-them: there is no settings menu. Transcription runs on
// this machine, so the home chrome is just the update pill, the About mark and
// a Notes button; the only non-home view is the Notes list. All advanced config
// lives in the `dictate config` CLI. ⌘K palette = Notes + a few daily actions.
import { useState, useEffect, useRef, useCallback } from "react";
import { Icon, Mark } from "./icons.jsx";
import { Combo, Tooltip } from "./primitives.jsx";
import { StoreCtx, useStore, modelById, DEMO_PHRASES, formatHistoryTime } from "./store.jsx";
import { VIEWS, HomeBar, NotebookToggle } from "./views.jsx";
import { ListeningHUD, CommandPalette, Toasts } from "./overlays.jsx";
import TitleBar from "./platform/TitleBar.jsx";
import { BreathCradle, WaveTimeline } from "./visualizers.jsx";
import { ipc } from "./ipc.js";

const DEFAULT_VERSION = "2026.9.25";
const TERMINAL_TRANSCRIPT_ID_LIMIT = 64;
const WINDOWS_PLATFORM_RE = /Windows NT|Win64|Win32|WOW64/i;
const DEMO_HISTORY = () => {
  const now = Date.now();
  // Newest-first: matches the real backend ordering and pushHistory behaviour.
  return [
    { id: "h3", createdAt: now - 6 * 60 * 1000, text: "Reminder to send the meeting summary to the team this afternoon." },
    { id: "h2", createdAt: now - 38 * 60 * 1000, text: "Let's move the planning session to Thursday and keep Friday clear for focused work." },
    { id: "h1", createdAt: now - 2 * 60 * 60 * 1000, text: "Draft a short note thanking the reviewers and ask them for feedback." },
    // A meeting (diarized segments) alongside the quick records — demonstrates the
    // Meetings/Quick category filter (see docs/record-categories-spec.md).
    {
      id: "m1",
      createdAt: now - 3 * 60 * 60 * 1000,
      text: "Weekly sync",
      segments: [
        { seq: 0, speakerLabel: "Speaker 1", tStart: 0, tEnd: 8, text: "Let's kick off with a quick status round before the roadmap." },
        { seq: 1, speakerLabel: "Speaker 2", tStart: 8, tEnd: 16, text: "Auth is done and deployed to prod; sync is the next piece." },
      ],
    },
  ];
};

// Format seconds → m:ss or h:mm:ss (mirrors the design's fmt helper).
function fmtSecs(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`;
}

function initialPlatform() {
  if (typeof document !== "undefined") {
    const tagged = document.documentElement.getAttribute("data-platform");
    if (tagged) return tagged;
  }
  const bridged = ipc.platform();
  if (bridged && bridged !== "gnome") return bridged;
  if (typeof navigator !== "undefined" && WINDOWS_PLATFORM_RE.test(navigator.userAgent || "")) {
    return "win11";
  }
  return bridged || "gnome";
}

function normalizeSegments(segments) {
  if (!Array.isArray(segments)) return [];
  return segments
    .map((segment, index) => {
      const text = typeof segment?.text === "string" ? segment.text.trim() : "";
      if (!text) return null;
      const tStart = Number.isFinite(Number(segment.tStart))
        ? Number(segment.tStart)
        : Number.isFinite(Number(segment.t_start))
          ? Number(segment.t_start)
          : null;
      const tEnd = Number.isFinite(Number(segment.tEnd))
        ? Number(segment.tEnd)
        : Number.isFinite(Number(segment.t_end))
          ? Number(segment.t_end)
          : null;
      return {
        seq: Number.isFinite(Number(segment.seq)) ? Number(segment.seq) : index,
        tStart,
        tEnd,
        text,
        speakerId: segment.speakerId || segment.speaker_id || null,
        speakerLabel: segment.speakerLabel || segment.speaker_label || null,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.seq - b.seq);
}

function mapHistoryPayload(history) {
  return (history || []).map((h) => ({
    id: h.id,
    text: h.text,
    createdAt: h.createdAt,
    mode: h.mode,
    status: h.status,
    segments: normalizeSegments(h.segments),
  }));
}

function noteText(note) {
  return typeof note?.text === "string" ? note.text : "";
}

function notePlainText(note) {
  const segments = normalizeSegments(note?.segments);
  if (!segments.length) return noteText(note);
  return segments
    .map((segment) => {
      const label = segment.speakerLabel || segment.speakerId;
      return label ? `${label}: ${segment.text}` : segment.text;
    })
    .join("\n");
}

function noteMarkdown(note, titleDate) {
  const segments = normalizeSegments(note?.segments);
  if (!segments.length) return `# Note - ${titleDate}\n\n${noteText(note)}\n`;
  const lines = [`# Note - ${titleDate}`, ""];
  for (const segment of segments) {
    const label = segment.speakerLabel || segment.speakerId || "Transcript";
    const hasStart = Number.isFinite(segment.tStart);
    const hasEnd = Number.isFinite(segment.tEnd);
    const time = hasStart && hasEnd
      ? ` [${fmtSecs(segment.tStart)}-${fmtSecs(segment.tEnd)}]`
      : hasStart
        ? ` [${fmtSecs(segment.tStart)}]`
        : "";
    lines.push(`**${label}${time}:** ${segment.text}`);
  }
  return `${lines.join("\n\n")}\n`;
}

/* The transcription engine. Everything runs on this machine. */
const PRIVATE_MODEL = "parakeet/parakeet-tdt-0.6b-v2";

/* ── Update affordance: one quiet pill in the home bar. The primary action is
   the only thing shown; Skip / Later are revealed on proximity (hover/focus).
   Skip suppresses until a newer version; Later returns on next launch. ─────── */
const UPDATE_LABEL = {
  available: "Update available",
  preparing: "Preparing update…",
  downloading: "Downloading…",
  verifying: "Verifying download…",
  ready: "Update ready",
  installing: "Installing update…",
  working: "Updating…",
  restart: "Restart Dictate",
  restarting: "Restarting…",
  error: "Update failed",
};
const COMMAND_UPDATE_POLL_LIMIT = 300;
const PACKAGE_UPDATE_FAILURE_LIMIT = 3;

function formatUpdateElapsed(totalSeconds) {
  const seconds = Math.max(0, Number(totalSeconds) || 0);
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function updateLabelForPhase(phase, progress, installElapsed) {
  if (phase === "downloading") {
    return Number.isFinite(progress) ? `Downloading… ${Math.round(progress)}%` : "Downloading…";
  }
  if (phase === "installing") {
    return Number.isFinite(installElapsed)
      ? `Installing update… ${formatUpdateElapsed(installElapsed)}`
      : "Installing update…";
  }
  return UPDATE_LABEL[phase] || "Update available";
}

function mapBackendUpdatePhase(status) {
  const phase = status?.phase;
  if (phase === "preparing") return "preparing";
  if (phase === "downloading") return "downloading";
  if (phase === "verifying") return "verifying";
  if (phase === "ready") return "ready";
  if (phase === "installing") return "installing";
  if (phase === "installed" || status?.step === "restart") return "restart";
  if (phase === "failed" && status?.errorCode === "check_failed") return "check-error";
  if (phase === "failed") return "error";
  if (phase === "working") return "working";
  return null;
}

function isUpdateBusyPhase(phase) {
  return phase === "preparing"
    || phase === "downloading"
    || phase === "verifying"
    || phase === "installing"
    || phase === "working"
    || phase === "restarting";
}

function UpdatePill() {
  const s = useStore();
  if (!s.updateVisible) {
    return (
      <Tooltip label="Check for updates">
        <button
          type="button"
          className="upd-check"
          onClick={s.checkUpdates}
          disabled={!!s.updateStatus?.checking}
          aria-label="Check for updates"
          title="Check for updates"
        >
          <Icon name="refresh" size={15} />
        </button>
      </Tooltip>
    );
  }
  const phase = s.updatePhase;
  const label = updateLabelForPhase(phase, s.updateProgress, s.updateInstallElapsed);
  const busy = isUpdateBusyPhase(phase);
  return (
    <div className={"updpill phase-" + phase}>
      <div className="upd-more">
        {phase === "error" ? (
          <button className="upd-mini" onClick={s.runUpdate} title="Retry update">Retry</button>
        ) : !busy && phase !== "restart" ? (
          <>
            <button className="upd-mini" onClick={s.dismissUpdate} title="Remind me on next launch">Later</button>
            <button className="upd-mini" onClick={s.skipUpdate} title="Skip this version">Skip</button>
          </>
        ) : null}
      </div>
      <button
        className="upd-main"
        onClick={s.runUpdate}
        disabled={busy}
        title={
          phase === "ready" ? "Install and restart"
            : phase === "restart" ? "Restart Dictate"
            : phase === "error" ? "Retry update"
              : busy ? label
                : "Update Dictate"
        }
      >
        <span className="upd-dot" aria-hidden="true" />
        <span className="upd-label">{label}</span>
      </button>
      {phase === "error" && s.updateErrorReason ? (
        <span className="upd-reason" role="status">{s.updateErrorReason}</span>
      ) : null}
    </div>
  );
}

function AboutButton() {
  const s = useStore();
  return (
    <Tooltip label="Dictate">
      <button
        type="button"
        className="about-mark"
        aria-label="About Dictate"
        title="About Dictate"
        onClick={() => s.setAboutOpen(true)}
      >
        <Mark size={17} />
      </button>
    </Tooltip>
  );
}

/* About Dictate — version, engine and the update controls. Local only: there is
   no account, no plan and no cloud here, so this dialog is the whole story. */
function AboutDialog() {
  const s = useStore();
  const betaSelected = s.updateChannel === "unstable";
  const storeInstall = s.updateStatus?.installKind === "windows-store";
  const updateBusy = !!(
    s.updateStatus?.checking
    || s.updateStatus?.updating
    || isUpdateBusyPhase(s.updatePhase)
  );

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); s.setAboutOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [s]);

  const selectUpdateChannel = (channel) => {
    if (channel === s.updateChannel) return;
    if (!ipc.isLive()) {
      s.setUpdateChannel(channel);
      s.toast(channel === "unstable" ? "Beta updates selected" : "Normal updates selected");
      return;
    }
    ipc.setUpdateChannel(channel)
      .then((st) => {
        if (st?.updateChannel) s.setUpdateChannel(st.updateChannel);
        if (typeof st?.installedPackageVersion === "string") s.setInstalledPackageVersion(st.installedPackageVersion);
        s.toast(channel === "unstable" ? "Beta updates selected" : "Normal updates selected");
        s.checkUpdates();
      })
      .catch((e) => s.toast(e.message || "Could not change update channel", { bad: true }));
  };

  return (
    <div className="about-scrim" onMouseDown={() => s.setAboutOpen(false)}>
      <div
        className="about-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="about-head">
          <span className="about-logo"><Mark size={22} /></span>
          <div className="about-title-wrap">
            <div id="about-title" className="about-title">Dictate</div>
            <div className="about-sub">Version {s.version}{s.updateChannel ? ` · ${s.updateChannel}` : ""}</div>
          </div>
          <button type="button" className="ibtn" aria-label="Close" title="Close" onClick={() => s.setAboutOpen(false)}>
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="about-grid">
          {s.installedPackageVersion && (
            <div className="about-row"><span>Package</span><strong>{s.installedPackageVersion}</strong></div>
          )}
          <div className="about-row">
            <span>Updates</span>
            {storeInstall ? <strong>Microsoft Store · Stable</strong> : <div className="about-channel" role="group" aria-label="Update channel">
              <button
                type="button"
                className={!betaSelected ? "active" : ""}
                aria-pressed={!betaSelected}
                onClick={() => selectUpdateChannel("stable")}
              >
                Normal
              </button>
              <button
                type="button"
                className={betaSelected ? "active" : ""}
                aria-pressed={betaSelected}
                title="Beta updates"
                onClick={() => selectUpdateChannel("unstable")}
              >
                Beta
              </button>
            </div>}
          </div>
        </div>

        <div className="about-actions about-actions--split">
          <button type="button" className="about-secondary" disabled={updateBusy} onClick={s.checkUpdates}>
            <Icon name="refresh" size={14} />
            <span>{s.updateStatus?.checking ? "Checking" : "Check for update"}</span>
          </button>
          {s.updateStatus?.updateAvailable && (
            <button type="button" className="about-primary" disabled={updateBusy} onClick={s.runUpdate}>
              <Icon name="download" size={14} />
              <span>{
                s.updatePhase === "ready" ? "Install and restart"
                  : s.updatePhase === "restart" ? "Restart"
                    : s.updateStatus?.updating ? "Updating" : "Update"
              }</span>
            </button>
          )}
        </div>

        <div className="about-note">Transcription runs on this machine. Nothing is sent anywhere.</div>
      </div>
    </div>
  );
}

function DiscardConfirmDialog({ meeting, onCancel, onConfirm }) {
  const confirmRef = useRef(null);
  useEffect(() => {
    const t = setTimeout(() => confirmRef.current?.focus(), 40);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); onCancel(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const label = meeting ? "meeting" : "note";
  return (
    <div className="confirm-scrim" onMouseDown={onCancel}>
      <div
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="discard-title"
        aria-describedby="discard-desc"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div id="discard-title" className="confirm-title">Discard {label}?</div>
        <div id="discard-desc" className="confirm-desc">
          This recording will be deleted and won&apos;t be saved to your notes.
        </div>
        <div className="confirm-actions">
          <button type="button" className="confirm-secondary" onClick={onCancel}>Cancel</button>
          <button ref={confirmRef} type="button" className="confirm-danger" autoFocus onClick={onConfirm}>Confirm</button>
        </div>
      </div>
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
  const meeting = s.captureMode === "meeting";
  const [discardOpen, setDiscardOpen] = useState(false);
  // Getting-started teaching is per-session, not per-history: it shows on every
  // fresh launch (even with saved notes) and hides once capture begins this run.
  const gettingStarted = !s.noteRecording && !s.sessionStarted;
  // Copy-last: the most recent quick record (a dictation, not a diarized meeting).
  const isMeeting = (n) => n?.mode === "meeting"
    || (n?.mode == null && Array.isArray(n?.segments) && n.segments.length > 0);
  const recentQuick = (s.history || []).find((n) => !isMeeting(n));
  const recentQuickText = recentQuick ? (recentQuick.text || notePlainText(recentQuick)) : "";
  const recentQuickPreview = recentQuickText;
  const copyLast = () => {
    if (!recentQuickText) return;
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(recentQuickText)
        .then(() => s.toast("Copied last dictation"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };
  useEffect(() => {
    if (!s.noteRecording || !s.notePaused) setDiscardOpen(false);
  }, [s.noteRecording, s.notePaused]);
  return (
    <div className="note-home">
      {/* Home chrome: the privacy truth (the one human control) + Notes. No gear —
          the GUI is do-it-for-them; advanced config lives in `dictate config`. */}
      <HomeBar
        right={<><UpdatePill /><AboutButton /></>}
        meeting={s.updateChannel === "unstable" && !s.noteRecording ? (
          <button type="button" className="meeting-action" onClick={s.startMeetingRecording}>
            <Icon name="users" size={14} />
            <span>Meeting</span>
          </button>
        ) : null}
      />
      <div className="note-home-inner">
        {/* Cradle + feedback */}
        <div className="note-screen">
          <div className="note-capture-stack">
            <div className="note-capture-anchor">
              <div className="cradle-wrap">
                <BreathCradle
                  session={s.noteRecording}
                  active={s.noteRecording && !s.notePaused}
                  paused={s.notePaused}
                  reduced={s.reduced}
                  onStart={s.startNoteRecording}
                  onPause={meeting ? s.finishNoteRecording : s.pauseNoteRecording}
                  onResume={s.resumeNoteRecording}
                  activeLabel={meeting ? "Finish meeting" : "Pause recording"}
                />
              </div>
              <div className={"note-feedback" + (gettingStarted ? " note-feedback--intro" : "")}>
            {s.noteRecording && !s.notePaused ? (
              <>
                <div className="note-status live">{meeting ? "Meeting" : "Recording"}</div>
                <div className="note-timer t-mono">{fmtSecs(s.noteElapsed)}</div>
                {s.transcript?.text ? (
                  <div className="note-preview" aria-live="polite">
                    <span>{s.transcript.text}</span><span className="note-caret" />
                  </div>
                ) : (
                  <WaveTimeline active reduced={s.reduced} level={s.audioLevel} live={s.live} />
                )}
              </>
            ) : s.noteRecording && s.notePaused ? (
              <>
                <div className="note-status paused">
                  {s.notePauseReason === "silence" ? "Paused — no speech detected" : "Paused"}
                </div>
                <div className="note-timer t-mono">{fmtSecs(s.noteElapsed)}</div>
                <div className="note-finish-row">
                  <button type="button" className="note-finish-btn" onClick={s.finishNoteRecording}>
                    <Icon name="square" size={14} />
                    <span>{meeting ? "Finish meeting" : "Finish note"}</span>
                  </button>
                  <button
                    type="button"
                    className="note-discard-btn"
                    aria-label="Discard recording"
                    title="Discard"
                    onClick={() => setDiscardOpen(true)}
                  >
                    <Icon name="trash" size={14} />
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="note-status-sub">Click to dictate</div>
                {/* Getting started (per-session): teach the key on a fresh launch. */}
                {gettingStarted && (
                  <>
                    <div className="note-status-hint">or hold <Combo keys={s.shortcut.map(shortcutKeyLabel)} /></div>
                    <GsKeyboard />
                  </>
                )}
                {/* Once capture has begun this session, offer a one-click copy of the
                    most recent quick dictation (older ones live in the notes list). */}
                {s.sessionStarted && recentQuickText && (
                  <button type="button" className="note-copylast" onClick={copyLast}>
                    <Icon name="copy" size={13} />
                    <span className="note-copylast-content">
                      <span className="note-copylast-label">Copy last dictation</span>
                      <span className="note-copylast-preview">{recentQuickPreview}</span>
                    </span>
                  </button>
                )}
                {/* Live push-to-talk transcript — hide once history has the same note. */}
                {s.transcript?.text && !s.transcript.stale && (s.recording || !s.history?.length) && (
                  <div className="note-preview" aria-live="polite">
                    <span>{s.transcript.text}</span>
                    {s.recording && <span className="note-caret" />}
                  </div>
                )}
              </>
            )}
              </div>
            </div>
          </div>
        </div>
      </div>
      {discardOpen && (
        <DiscardConfirmDialog
          meeting={meeting}
          onCancel={() => setDiscardOpen(false)}
          onConfirm={() => {
            setDiscardOpen(false);
            s.discardNoteRecording();
          }}
        />
      )}
    </div>
  );
}

/* ── Transcribing… (indeterminate, shown between stop and note event) ── */
function NoteProcessing() {
  const s = useStore();
  const meeting = s.captureMode === "meeting";
  return (
    <div className="note-proc-wrap">
      <div className="note-proc-inner">
        <div className="note-status" style={{ marginBottom: 6 }}>Transcribing…</div>
        <div className="note-status-sub">
          {meeting ? "Separating speakers and preparing the transcript." : "Turning your words into a note."}
        </div>
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
      navigator.clipboard.writeText(notePlainText(note))
        .then(() => s.toast("Copied to clipboard"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };

  // Export dictation as a Markdown file via the OS save dialog.
  const handleExport = async () => {
    const ts = note.createdAt ? new Date(note.createdAt).toISOString().slice(0, 10) : "note";
    const name = `dictate-note-${ts}.md`;
    const md = noteMarkdown(note, ts);
    try {
      const saved = await ipc.saveTextFile(name, md);
      if (saved) s.toast("Saved as Markdown");
    } catch {
      s.toast("Could not save file", { bad: true });
    }
  };

  const closeExpanded = () => {
    s.setNoteView(null);
    s.setView(s.expandedFrom === "history" ? "history" : "home");
  };

  const backLabel = s.expandedFrom === "history" ? "Back to dictations" : "Back to capture";

  return (
    <div className="note-exp-wrap">
      <div className="notes-search note-exp-top">
        <span className="note-exp-title">{noteLabel}</span>
        <span className="notes-search-grow" aria-hidden="true" />
        <button className="ibtn" title="Copy" onClick={handleCopy}><Icon name="copy" size={16} /></button>
        <button className="ibtn" title="Export as Markdown" onClick={handleExport}><Icon name="download" size={16} /></button>
        <NotebookToggle />
      </div>
      <div className="note-exp-body">
        <button
          type="button"
          className="note-exp-back-col"
          aria-label={backLabel}
          title={backLabel}
          onClick={closeExpanded}
        >
          <span className="note-exp-back-ico" aria-hidden="true">
            <Icon name="back" size={18} />
          </span>
        </button>
        <div className="note-exp-scroll scroll">
        {normalizeSegments(note.segments).length > 0 ? (
          <div className="note-segments">
            {normalizeSegments(note.segments).map((segment) => {
              const label = segment.speakerLabel || segment.speakerId;
              const hasStart = Number.isFinite(segment.tStart);
              const hasEnd = Number.isFinite(segment.tEnd);
              return (
                <div className="note-segment" key={segment.seq}>
                  {label && <span className="note-segment-speaker">{label}</span>}
                  {(hasStart || hasEnd) && (
                    <span className="note-segment-time">
                      {hasStart ? fmtSecs(segment.tStart) : "--"}
                      {hasEnd ? `-${fmtSecs(segment.tEnd)}` : ""}
                    </span>
                  )}
                  <p className="note-segment-text">{segment.text}</p>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="note-exp-text">{noteText(note)}</p>
        )}
        </div>
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
  const [model, setModelState] = useState(PRIVATE_MODEL);
  const [meetingModel, setMeetingModelState] = useState("parakeet-pyannote/parakeet-tdt-0.6b-v2");
  const [meetingReadiness, setMeetingReadiness] = useState({ ready: true, reason: null });
  const [shortcut, setShortcutState] = useState(["Ctrl (R)"]);
  const [activation, setActivationState] = useState("hold");
  const [device] = useState("Default device");
  const [device2, setDevice2State] = useState("auto");
  const [compute, setComputeState] = useState("int8");
  const [hotwords, setHotwords] = useState([]);
  const [history, setHistory] = useState(() => (ipc.isMockMode() ? DEMO_HISTORY() : []));
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
  // Session-scoped: false on a fresh launch, true once the user has captured
  // anything this run. Not persisted — resets to false on app close/reopen, so
  // the getting-started teaching re-shows and the home copy-last hides again.
  const [sessionStarted, setSessionStarted] = useState(false);
  const [notePaused, setNotePaused] = useState(false);
  const [notePauseReason, setNotePauseReason] = useState(null);
  const [captureMode, setCaptureMode] = useState("note");
  const [noteText, setNoteText] = useState("");
  const [noteElapsed, setNoteElapsed] = useState(0); // seconds since noteRecording started
  const [audioLevel, setAudioLevel] = useState(null);
  const [transcript, setTranscript] = useState({ phase: null, text: "", stale: false });
  const [typing, setTyping] = useState(false);
  const [targetText, setTargetText] = useState("");
  const [palette, setPalette] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [capturing, setCapturing] = useState(false);
  const [version, setVersion] = useState(DEFAULT_VERSION);
  const [updateChannel, setUpdateChannel] = useState("stable");
  const [installedPackageVersion, setInstalledPackageVersion] = useState("");
  const [updateStatus, setUpdateStatus] = useState(() => mockUpdateStatus(DEFAULT_VERSION));
  // Update affordance state machine: idle → available → preparing → ready → installing (→ error).
  // The update prepares in the background so the click is instant once "ready".
  const [updatePhase, setUpdatePhase] = useState("idle");
  const [updateProgress, setUpdateProgress] = useState(null);
  const [updateInstallStartedAt, setUpdateInstallStartedAt] = useState(null);
  const [updateInstallElapsed, setUpdateInstallElapsed] = useState(null);
  const [updateErrorReason, setUpdateErrorReason] = useState(null);
  // Skip persists across launches (suppress until a newer version); Dismiss is session-only.
  const [skippedVersion, setSkippedVersion] = useState(() => {
    try { return (typeof localStorage !== "undefined" && localStorage.getItem("dictate.skippedVersion")) || null; }
    catch { return null; }
  });
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [platform, setPlatform] = useState(initialPlatform);
  const [live, setLive] = useState(false);
  // Note surface state machine: null=home, "processing"=transcribing, "expanded"=full note view
  const [noteView, setNoteView] = useState(null);
  const [currentNote, setCurrentNote] = useState(null);
  const [aboutOpen, setAboutOpen] = useState(false);
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
  const discardPendingRef = useRef(false);
  const captureModeRef = useRef("note"); captureModeRef.current = captureMode;
  // watchdogRef: 60 s safety-net timer; cleared on every normal resolution path.
  const watchdogRef = useRef(null);
  const ARCHIVE_LEAVE_MS = 220;
  const ARCHIVE_UNDO_LIMIT = 20;
  const [leavingNoteIds, setLeavingNoteIds] = useState([]);
  const leavingNoteIdsRef = useRef(new Set());
  const archiveUndoRef = useRef([]);
  const archiveTimersRef = useRef(new Map());
  const currentNoteRef = useRef(null); currentNoteRef.current = currentNote;
  const expandedFromRef = useRef("capture"); expandedFromRef.current = expandedFrom;
  const updatePollRef = useRef(null);
  const updatePollModeRef = useRef(null);
  const updatePollGenerationRef = useRef(0);
  const updateRestartRequestedRef = useRef(false);
  const installConfirmedRef = useRef(false);

  const stopUpdatePolling = () => {
    updatePollGenerationRef.current += 1;
    if (updatePollRef.current) {
      clearTimeout(updatePollRef.current);
      updatePollRef.current = null;
    }
    updatePollModeRef.current = null;
  };

  const requestUpdateRestart = (message) => {
    if (updateRestartRequestedRef.current) return;
    updateRestartRequestedRef.current = true;
    setUpdatePhase("restarting");
    setUpdateProgress(null);
    setUpdateErrorReason(null);
    stopUpdatePolling();
    if (message) toast(message);
    Promise.resolve(ipc.restartApp()).then((restarted) => {
      if (restarted) return;
      updateRestartRequestedRef.current = false;
      setUpdatePhase("restart");
      toast("Restart Dictate to finish the update", { bad: true });
    }).catch(() => {
      updateRestartRequestedRef.current = false;
      setUpdatePhase("restart");
      toast("Restart Dictate to finish the update", { bad: true });
    });
  };

  const applyPolledUpdateStatus = (status) => {
    if (!status || updateRestartRequestedRef.current) return;
    setUpdateStatus((u) => ({ ...u, ...status, checking: false, updating: false }));
    const mapped = mapBackendUpdatePhase(status);
    if (mapped === "check-error") return;
    if (mapped === "preparing") {
      setUpdatePhase("preparing");
      setUpdateProgress(null);
      setUpdateErrorReason(null);
      return;
    }
    if (mapped === "downloading") {
      setUpdatePhase("downloading");
      setUpdateProgress(Number.isFinite(status.progress) ? status.progress : null);
      setUpdateErrorReason(null);
      return;
    }
    if (mapped === "verifying") {
      setUpdatePhase("verifying");
      setUpdateProgress(null);
      setUpdateErrorReason(null);
      return;
    }
    if (mapped === "installing") {
      setUpdatePhase("installing");
      setUpdateProgress(null);
      setUpdateErrorReason(null);
      if (status.installStartedAt) setUpdateInstallStartedAt(status.installStartedAt);
      return;
    }
    if (mapped === "ready") {
      setUpdatePhase("ready");
      setUpdateProgress(null);
      setUpdateErrorReason(null);
      stopUpdatePolling();
      return;
    }
    if (mapped === "restart") {
      if (installConfirmedRef.current) {
        requestUpdateRestart("Update installed — restarting…");
      } else {
        setUpdatePhase("restart");
        stopUpdatePolling();
      }
      return;
    }
    if (mapped === "error") {
      setUpdatePhase("error");
      setUpdateProgress(null);
      setUpdateErrorReason(status.errorDetail || status.error || "Update failed");
      stopUpdatePolling();
      return;
    }
    if (updatePollModeRef.current === "package" && status.checked && !mapped) {
      setUpdatePhase(status.updateAvailable ? "available" : "idle");
      setUpdateProgress(null);
      setUpdateInstallStartedAt(null);
      setUpdateInstallElapsed(null);
      setUpdateErrorReason(null);
      stopUpdatePolling();
      return;
    }
    if (updatePollModeRef.current === "command" && status.checked && !status.updateAvailable) {
      setUpdatePhase("restart");
      setUpdateProgress(null);
      setUpdateErrorReason(null);
      stopUpdatePolling();
    }
  };

  const startUpdatePolling = (mode = "package") => {
    stopUpdatePolling();
    updatePollModeRef.current = mode;
    const generation = updatePollGenerationRef.current;
    let attempts = 0;
    let consecutiveFailures = 0;
    const recordPackageFailure = () => {
      if (mode !== "package") return false;
      consecutiveFailures += 1;
      if (
        consecutiveFailures < PACKAGE_UPDATE_FAILURE_LIMIT
        || generation !== updatePollGenerationRef.current
      ) return false;
      const detail = "Lost contact with updater. Retry the update.";
      setUpdateStatus((u) => ({ ...u, updating: false, error: detail }));
      setUpdatePhase("error");
      setUpdateProgress(null);
      setUpdateErrorReason(detail);
      stopUpdatePolling();
      return true;
    };
    const poll = async () => {
      if (generation !== updatePollGenerationRef.current || updateRestartRequestedRef.current) return;
      if (mode === "command") attempts += 1;
      if (ipc.isLive()) {
        try {
          const status = await ipc.checkUpdates();
          if (generation !== updatePollGenerationRef.current || updateRestartRequestedRef.current) return;
          const mapped = mapBackendUpdatePhase(status);
          if (mode === "package" && mapped === "check-error") {
            if (recordPackageFailure()) return;
          } else if (mode === "package" && (mapped || status?.checked)) {
            consecutiveFailures = 0;
          } else if (recordPackageFailure()) {
            return;
          }
          applyPolledUpdateStatus(status);
        } catch {
          if (recordPackageFailure()) return;
        }
      }
      if (
        mode === "command"
        && attempts >= COMMAND_UPDATE_POLL_LIMIT
        && generation === updatePollGenerationRef.current
      ) {
        const detail = "Update status timed out. Retry the update.";
        setUpdateStatus((u) => ({ ...u, updating: false, error: detail }));
        setUpdatePhase("error");
        setUpdateProgress(null);
        setUpdateErrorReason(detail);
        stopUpdatePolling();
        return;
      }
      if (generation === updatePollGenerationRef.current && updatePollModeRef.current) {
        updatePollRef.current = setTimeout(poll, 1000);
      }
    };
    updatePollRef.current = setTimeout(poll, 1000);
  };

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);
  useEffect(() => { document.documentElement.setAttribute("data-ambient", ambient ? "on" : "off"); }, [ambient]);

  useEffect(() => {
    if (updatePhase !== "installing" || !updateInstallStartedAt) {
      if (updatePhase !== "installing") setUpdateInstallElapsed(null);
      return;
    }
    const started = Date.parse(updateInstallStartedAt);
    const tick = () => {
      if (!Number.isFinite(started)) return;
      setUpdateInstallElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [updatePhase, updateInstallStartedAt]);

  useEffect(() => () => stopUpdatePolling(), []);

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
        if (ev.active) setSessionStarted(true);
        if (ev.active) setTranscript({ phase: null, text: "", stale: false });
        else setAudioLevel(null);
      }
      else if (ev.type === "note-recording") {
        if (ev.paused) {
          if (ev.mode === "meeting" || ev.mode === "note") setCaptureMode(ev.mode);
          setNoteRecording(true);
          setNotePaused(true);
          setNotePauseReason(ev.pauseReason || null);
          setAudioLevel(null);
        } else if (ev.active) {
          if (ev.mode === "meeting" || ev.mode === "note") setCaptureMode(ev.mode);
          setNoteRecording(true);
          setSessionStarted(true);
          setNotePaused(false);
          setNotePauseReason(null);
          setAudioLevel(null);
          // New recording started — clear any stale watchdog, reset note surface.
          clearWatchdog();
          setNoteView(null);
          setCurrentNote(null);
        } else {
          setNoteRecording(false);
          setNotePaused(false);
          setNotePauseReason(null);
          setAudioLevel(null);
          if (ev.mode === "meeting" || ev.mode === "note") setCaptureMode(ev.mode);
          if (ev.discarded || discardPendingRef.current) {
            discardPendingRef.current = false;
            clearWatchdog();
            setNoteView(null);
            setCurrentNote(null);
            setTranscript({ phase: null, text: "", stale: false });
          } else {
            // Recording finished — show Transcribing… and arm the safety-net watchdog.
            setNoteView("processing");
            armWatchdog();
          }
        }
      }
      else if (ev.type === "audio-level") {
        if (typeof ev.level === "number") setAudioLevel(ev.level);
      }
      else if (ev.type === "note") {
        // The backend now sends a `status` field on every terminal note outcome.
        // Old daemons without the field default to "ok" for backward compatibility.
        const status = ev.status || (ev.text ? "ok" : "empty");
        clearWatchdog();
        if (status === "ok" && typeof ev.text === "string" && ev.text) {
          setNoteText(ev.text);
          const note = {
            id: ev.id || "n" + Date.now(),
            text: ev.text,
            createdAt: ev.createdAt || new Date().toISOString(),
            mode: ev.mode || captureModeRef.current,
            segments: normalizeSegments(ev.segments),
          };
          setCurrentNote(note);
          setHistory((entries) => [note, ...entries.filter((entry) => entry.id !== note.id)].slice(0, 50));
          setExpandedFrom("capture");
          setNoteView("expanded");
          toast(note.mode === "meeting" ? "Meeting saved to Dictations" : "Conversation note saved");
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
              setExpandedFrom("capture");
              return "expanded";
            }
            return nv;
          });
        });
      }
    }, () => {
      // SSE reconnected (e.g. engine restarted after an update) — re-sync the
      // full state so history + quick-copy reflect anything missed while offline.
      ipc.getState().then((st) => { if (!cancelled && st) hydrate(st); }).catch(() => {});
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
    if (st.meetingModel && st.meetingModel.id) setMeetingModelState(st.meetingModel.id);
    if (st.meetingReadiness) setMeetingReadiness(st.meetingReadiness);
    if (st.shortcut) {
      if (Array.isArray(st.shortcut.display)) setShortcutState(st.shortcut.display);
      if (st.shortcut.activation) setActivationState(st.shortcut.activation);
    }
    if (Array.isArray(st.hotwords)) setHotwords(st.hotwords);
    setHistory(mapHistory(st));
    if (st.notes && typeof st.notes.recording === "boolean") setNoteRecording(st.notes.recording);
    if (st.notes && typeof st.notes.paused === "boolean") setNotePaused(st.notes.paused);
    if (st.notes && (st.notes.mode === "meeting" || st.notes.mode === "note")) setCaptureMode(st.notes.mode);
    if (st.notes && typeof st.notes.pauseReason === "string") setNotePauseReason(st.notes.pauseReason);
    else if (st.notes && !st.notes.paused) setNotePauseReason(null);
    if (st.prefs) {
      if (st.prefs.theme && st.prefs.theme !== "system") { explicitThemeRef.current = true; setThemeState(st.prefs.theme); }
      setTrayOnlyState(!!st.prefs.trayOnly);
      setOverlayState(!!st.prefs.overlay);
      setSoundState(!!st.prefs.sound);
      setAmbientState(!!st.prefs.ambient);
    }
    if (typeof st.startup === "boolean") setStartupState(st.startup);
    if (st.device?.device) setDevice2State(st.device.device);
    if (st.device?.compute) setComputeState(st.device.compute);
    if (st.version) setVersion(st.version);
    if (st.updateChannel) setUpdateChannel(st.updateChannel);
    if (typeof st.installedPackageVersion === "string") setInstalledPackageVersion(st.installedPackageVersion);
  }, []);

  const mapHistory = (st) => mapHistoryPayload(st.history);

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

  const archiveNote = useCallback((note) => {
    if (!note?.id || leavingNoteIdsRef.current.has(note.id)) return;
    const index = history.findIndex((n) => n.id === note.id);
    if (index < 0) return;

    leavingNoteIdsRef.current.add(note.id);
    setLeavingNoteIds((ids) => (ids.includes(note.id) ? ids : [...ids, note.id]));

    archiveUndoRef.current.push({ note, index });
    if (archiveUndoRef.current.length > ARCHIVE_UNDO_LIMIT) archiveUndoRef.current.shift();

    const cancelRemoval = () => {
      const timer = archiveTimersRef.current.get(note.id);
      if (timer) {
        clearTimeout(timer);
        archiveTimersRef.current.delete(note.id);
      }
    };

    const restoreArchivedNote = () => {
      cancelRemoval();
      leavingNoteIdsRef.current.delete(note.id);
      setLeavingNoteIds((ids) => ids.filter((id) => id !== note.id));
      setHistory((h) => {
        if (h.some((n) => n.id === note.id)) return h;
        const next = [...h];
        next.splice(Math.min(index, next.length), 0, note);
        return next;
      });
      archiveUndoRef.current = archiveUndoRef.current.filter((item) => item.note.id !== note.id);
      if (ipc.isLive()) {
        ipc.unarchiveHistoryItem(note.id).catch(() => {
          setHistory((h) => h.filter((n) => n.id !== note.id));
          toast("Could not restore note", { bad: true });
        });
      }
    };

    toast("Note archived", { undo: restoreArchivedNote });

    const timer = setTimeout(() => {
      archiveTimersRef.current.delete(note.id);
      leavingNoteIdsRef.current.delete(note.id);
      setLeavingNoteIds((ids) => ids.filter((id) => id !== note.id));
      setHistory((h) => h.filter((n) => n.id !== note.id));
      if (currentNoteRef.current?.id === note.id) {
        setNoteView(null);
        setCurrentNote(null);
        setView(expandedFromRef.current === "history" ? "history" : "home");
      }
    }, ARCHIVE_LEAVE_MS);
    archiveTimersRef.current.set(note.id, timer);

    if (ipc.isLive()) {
      ipc.archiveHistoryItem(note.id).catch(() => {
        cancelRemoval();
        leavingNoteIdsRef.current.delete(note.id);
        setLeavingNoteIds((ids) => ids.filter((id) => id !== note.id));
        archiveUndoRef.current = archiveUndoRef.current.filter((item) => item.note.id !== note.id);
        toast("Could not archive note", { bad: true });
      });
    }
  }, [history, toast]);

  const undoLastArchive = useCallback(() => {
    const stack = archiveUndoRef.current;
    if (!stack.length) return false;
    const { note, index } = stack[stack.length - 1];
    archiveUndoRef.current = stack.slice(0, -1);

    const timer = archiveTimersRef.current.get(note.id);
    if (timer) {
      clearTimeout(timer);
      archiveTimersRef.current.delete(note.id);
    }
    leavingNoteIdsRef.current.delete(note.id);
    setLeavingNoteIds((ids) => ids.filter((id) => id !== note.id));
    setHistory((h) => {
      if (h.some((n) => n.id === note.id)) return h;
      const next = [...h];
      next.splice(Math.min(index, next.length), 0, note);
      return next;
    });
    if (ipc.isLive()) {
      ipc.unarchiveHistoryItem(note.id).catch(() => {
        setHistory((h) => h.filter((n) => n.id !== note.id));
        toast("Could not restore note", { bad: true });
      });
    }
    return true;
  }, [toast]);

  const applyNoteState = (r) => {
    if (!r) return;
    if (typeof r.recording === "boolean") setNoteRecording(r.recording);
    if (typeof r.paused === "boolean") setNotePaused(r.paused);
    if (r.mode === "meeting" || r.mode === "note") setCaptureMode(r.mode);
    if (typeof r.pauseReason === "string") setNotePauseReason(r.pauseReason);
    else if (r.paused === false) setNotePauseReason(null);
  };

  const startNoteRecording = () => {
    if (noteRecording) return;
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      clearWatchdog();
      setNotePaused(false);
      setNotePauseReason(null);
      setCaptureMode("note");
      setNoteRecording(true);
      setSessionStarted(true);
      setNoteView(null);
      setCurrentNote(null);
      toast("Note recording started");
      return;
    }
    ipc.startNoteRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not start note recording", { bad: true }));
  };

  const startMeetingRecording = () => {
    if (noteRecording) return;
    if (meetingReadiness && meetingReadiness.ready === false) {
      toast(`Meeting model is not ready: ${meetingReadiness.reason || "prepare the local Meeting model first"}`, {
        bad: true,
        ms: 12_000,
      });
      return;
    }
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      clearWatchdog();
      setNotePaused(false);
      setNotePauseReason(null);
      setCaptureMode("meeting");
      setNoteRecording(true);
      setSessionStarted(true);
      setNoteView(null);
      setCurrentNote(null);
      toast("Meeting started");
      return;
    }
    setCaptureMode("meeting");
    ipc.startMeetingRecording()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not start meeting", { bad: true }));
  };

  const pauseNoteRecording = () => {
    if (!noteRecording || notePaused) return;
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
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
      if (!ipc.isMockMode()) {
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
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
      if (!ipc.isMockMode()) {
        setNotePaused(false);
        setNoteRecording(false);
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      setNotePaused(false);
      setNoteRecording(false);
      setNoteView("processing");
      armWatchdog();
      const demo = captureMode === "meeting"
        ? "Speaker 1: Let's capture the launch blockers.\nSpeaker 2: I will test the Windows build and report back tomorrow."
        : "Let's capture this as a project note. Add the follow-up action for tomorrow.";
      const demoSegments = captureMode === "meeting"
        ? [
            { seq: 0, tStart: 0, tEnd: 2.4, text: "Let's capture the launch blockers.", speakerLabel: "Speaker 1" },
            { seq: 1, tStart: 2.4, tEnd: 5.8, text: "I will test the Windows build and report back tomorrow.", speakerLabel: "Speaker 2" },
          ]
        : [];
      setTimeout(() => {
        clearWatchdog();
        const note = {
          id: "n" + Date.now(),
          text: demo,
          createdAt: new Date().toISOString(),
          mode: captureMode,
          segments: demoSegments,
        };
        setNoteText(demo);
        setCurrentNote(note);
        setHistory((entries) => [note, ...entries].slice(0, 50));
        setExpandedFrom("capture");
        setNoteView("expanded");
        toast(captureMode === "meeting" ? "Meeting saved to Dictations" : "Conversation note saved");
      }, 800);
      return;
    }
    const stop = captureMode === "meeting" ? ipc.stopMeetingRecording : ipc.stopNoteRecording;
    stop()
      .then(applyNoteState)
      .catch((e) => toast(e.message || "Could not finish recording", { bad: true }));
  };

  const discardNoteRecording = () => {
    if (!noteRecording) return;
    const reset = () => {
      setNoteRecording(false);
      setNotePaused(false);
      setNotePauseReason(null);
      setNoteView(null);
      setCurrentNote(null);
      setNoteElapsed(0);
      setTranscript({ phase: null, text: "", stale: false });
      clearWatchdog();
    };
    if (!ipc.isLive()) {
      if (!ipc.isMockMode()) {
        reset();
        toast("Dictate engine is not connected", { bad: true });
        return;
      }
      reset();
      return;
    }
    discardPendingRef.current = true;
    const discard = captureMode === "meeting" ? ipc.discardMeetingRecording : ipc.discardNoteRecording;
    discard()
      .then((r) => {
        applyNoteState(r);
        reset();
      })
      .catch((e) => {
        discardPendingRef.current = false;
        toast(e.message || "Could not discard recording", { bad: true });
      });
  };

  const toggleNoteRecording = () => {
    if (!noteRecording) startNoteRecording();
    else if (notePaused) resumeNoteRecording();
    else finishNoteRecording();
  };

  const finishNoteRef = useRef(finishNoteRecording);
  finishNoteRef.current = finishNoteRecording;
  const noteRecRef = useRef(false); noteRecRef.current = noteRecording;
  const notePausedRef = useRef(false); notePausedRef.current = notePaused;

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
        const mapped = mapBackendUpdatePhase(next);
        if (mapped === "preparing" || mapped === "downloading" || mapped === "verifying" || mapped === "installing") {
          setUpdateDismissed(false);
          applyPolledUpdateStatus(next);
          startUpdatePolling("package");
          return;
        }
        if (mapped === "error") {
          setUpdateDismissed(false);
          applyPolledUpdateStatus(next);
          return;
        }
        if (mapped === "ready" || mapped === "restart") {
          setUpdateDismissed(false);
          setUpdatePhase(mapped);
          return;
        }
        if (next.installKind === "windows-store") {
          setUpdateChannel("stable");
          toast("Checking for updates in Microsoft Store");
          startUpdate();
          return;
        }
        if (next.updateAvailable) {
          setUpdatePhase("available");
        } else if (next.checked) {
          stopUpdatePolling();
          setUpdatePhase("idle");
          setUpdateProgress(null);
          setUpdateInstallStartedAt(null);
          setUpdateInstallElapsed(null);
          setUpdateErrorReason(null);
        }
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
    setUpdateErrorReason(null);
    if (!ipc.isLive()) {
      window.open("https://github.com/arcforgelabs/dictate/releases", "_blank", "noopener,noreferrer");
      setUpdateStatus((u) => ({ ...u, updating: false }));
      toast("Opened latest release");
      return;
    }
    setUpdateDismissed(false);
    setUpdatePhase("preparing");
    setUpdateProgress(null);
    ipc.startUpdate()
      .then((flow) => {
        setUpdateStatus((u) => ({ ...u, updating: false }));
        if (
          installConfirmedRef.current
          && (flow?.mode === "installed" || (flow?.actions || []).includes("restart"))
        ) {
          requestUpdateRestart(flow?.message || "Update installed — restarting…");
          return;
        }
        if (flow?.mode === "error" || flow?.phase === "failed") {
          const detail = flow.errorDetail || flow.message || "Could not complete the update";
          setUpdateStatus((u) => ({ ...u, error: detail }));
          setUpdatePhase("error");
          setUpdateErrorReason(detail);
          toast(flow?.message || "Could not complete the update", { bad: true });
          return;
        }
        if (flow?.mode === "busy") {
          applyPolledUpdateStatus(flow);
          startUpdatePolling(flow?.installKind === "linux-package" ? "package" : "command");
          return;
        }
        if (flow?.started && flow?.installKind === "linux-package") {
          applyPolledUpdateStatus(flow);
          startUpdatePolling("package");
          return;
        }
        if (flow?.mode === "command" && flow?.started) {
          setUpdatePhase("working");
          setUpdateProgress(null);
          startUpdatePolling("command");
        } else {
          setUpdatePhase(flow?.started ? "available" : "idle");
        }
        if (flow?.url) {
          window.open(flow.url, "_blank", "noopener,noreferrer");
        }
        if (flow?.started) toast(flow?.message || "Update started");
        else toast(flow?.message || "Opened latest release");
      })
      .catch((e) => {
        setUpdateStatus((u) => ({ ...u, updating: false, error: e.message || "Could not start update" }));
        setUpdatePhase("error");
        setUpdateErrorReason(e.message || "Could not start update");
        toast("Could not start update", { bad: true });
      });
  };
  const mockDoctor = () => ({
    ok: true,
    checks: [
      { label: "Microphone access", sub: "Default device responding", ok: true },
      { label: "Model loads", sub: "Ready", ok: true },
      { label: "Output backend", sub: "Typing into focused app", ok: true },
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
    stopUpdatePolling();
    setUpdatePhase("idle");
    setUpdateProgress(null);
    setUpdateErrorReason(null);
    toast("Skipped this version");
  };
  const dismissUpdate = () => { setUpdateDismissed(true); };
  const runUpdate = () => {
    if (isUpdateBusyPhase(updatePhase)) return;
    setSkippedVersion("");
    try { localStorage.removeItem("dictate.skippedVersion"); } catch { /* ignore */ }
    if (updatePhase === "ready") installConfirmedRef.current = true;
    if (updatePhase === "restart" || updatePhase === "restarting") {
      requestUpdateRestart("Restarting Dictate…");
      return;
    }
    if (!ipc.isLive()) {
      setUpdatePhase("working");
      setTimeout(() => {
        toast("Updated — restarting…");
        setUpdateDismissed(true);
        setUpdatePhase("idle");
        setUpdateProgress(null);
      }, 1600);
      return;
    }
    setUpdateProgress(null);
    setUpdateInstallStartedAt(null);
    setUpdateInstallElapsed(null);
    setUpdateErrorReason(null);
    startUpdate();
  };

  // ---- launch-time update flow: silent check, prepare in the background ----
  useEffect(() => {
    if (!ipc.isLive()) {
      const t1 = setTimeout(() => {
        setUpdateStatus((u) => ({ ...u, updateAvailable: true, latestVersion: "2026.7.1", checked: true }));
        setUpdatePhase((p) => (p === "idle" ? "available" : p));
      }, 900);
      return () => { clearTimeout(t1); };
    }
    let cancelled = false;
    ipc.checkUpdates().then((st) => {
      if (cancelled || !st) return;
      setUpdateStatus((u) => ({ ...u, ...st }));
      if (st.installKind === "windows-store") setUpdateChannel("stable");
      const mapped = mapBackendUpdatePhase(st);
      if (mapped === "check-error") return;
      if (mapped === "error") {
        setUpdatePhase("error");
        setUpdateErrorReason(st.errorDetail || st.error || "Update failed");
        return;
      }
      if (mapped === "preparing" || mapped === "downloading" || mapped === "verifying" || mapped === "installing") {
        applyPolledUpdateStatus(st);
        startUpdatePolling("package");
        return;
      }
      if (mapped === "ready" || mapped === "restart") {
        setUpdatePhase(mapped);
        return;
      }
      if (!st.updateAvailable) return;
      setUpdatePhase("available");
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
  const dictateStart = () => { if (recRef.current || live) return; setRecording(true); setSessionStarted(true); };
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
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
        if (!archiveUndoRef.current.length) return;
        e.preventDefault();
        undoLastArchive();
        return;
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); return; }
      if (e.code === "ControlRight" && !e.repeat) {
        if (live && noteRecRef.current && !notePausedRef.current && actRef.current === "hold") {
          e.preventDefault();
          finishNoteRef.current();
          return;
        }
        if (capRef.current || live) return;
        e.preventDefault();
        if (actRef.current === "toggle") { recRef.current ? dictateStop() : dictateStart(); }
        else dictateStart();
        return;
      }
      if (capRef.current || live) return;
    };
    const up = (e) => {
      if (capRef.current || live) return;
      if (e.code === "ControlRight" && actRef.current === "hold") { e.preventDefault(); dictateStop(); }
    };
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    return () => { window.removeEventListener("keydown", down, true); window.removeEventListener("keyup", up, true); };
  }, [live, undoLastArchive]);

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

  // The pill shows while an update exists or while a completed update is waiting
  // for a clean shell+engine restart.
  const updateVisible = updatePhase !== "idle" && !updateDismissed
    && (
      !!updateStatus.updateAvailable
      || updatePhase === "restart"
      || updatePhase === "restarting"
      || updatePhase === "preparing"
      || updatePhase === "error"
      || updatePhase === "downloading"
      || updatePhase === "verifying"
      || updatePhase === "ready"
      || updatePhase === "installing"
      || updatePhase === "working"
    )
    && (!skippedVersion || updateStatus.latestVersion !== skippedVersion);

  const store = {
    view, setView, model, setModel, shortcut, setShortcut, activation, setActivation,
    device, device2, setDevice2, compute, hotwords, addHotword, removeHotword,
    history, clearHistory, archiveNote, leavingNoteIds, theme, setTheme, startup, setStartup, trayOnly, setTrayOnly,
    overlay, setOverlay, sound, setSound, ambient, setAmbient,
    recording, noteRecording, sessionStarted, notePaused, notePauseReason, captureMode, noteText,
    startNoteRecording, startMeetingRecording, pauseNoteRecording, resumeNoteRecording,
    finishNoteRecording, discardNoteRecording, toggleNoteRecording,
    transcript, typing, targetText, dictateStart, dictateStop, dictateOnce,
    palette, setPalette, toasts, toast, dismiss, micConnected: true, setCapturing,
    runDoctor, version, updateChannel, setUpdateChannel, installedPackageVersion, setInstalledPackageVersion, updateStatus, checkUpdates, startUpdate, platform,
    // Update affordance
    updatePhase, updateProgress, updateInstallElapsed, updateErrorReason, updateVisible, runUpdate, skipUpdate, dismissUpdate,
    // Note Capture additions
    noteElapsed, reduced, audioLevel, live,
    noteView, setNoteView, currentNote, setCurrentNote,
    expandedFrom, setExpandedFrom,
    meetingModel, meetingReadiness,
    aboutOpen, setAboutOpen, setHistory,
  };

  // Resolve the current settings view component (null when on capture home).
  const Current = view !== "home" ? VIEWS[view] : null;
  const nativeDecorations = typeof document !== "undefined"
    && document.documentElement.getAttribute("data-native-decorations") === "true";
  const nativeChrome = nativeDecorations || platform === "win11" || platform === "win10";

  return (
    <StoreCtx.Provider value={store}>
      <div className={"win " + platform + (nativeChrome ? " native-chrome" : "")} ref={winRef}>
        {!nativeChrome && (
          <TitleBar
            platform={platform}
            hasUpdate={!!updateStatus.updateAvailable}
          />
        )}

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
        {aboutOpen && <AboutDialog />}
        <Toasts />
      </div>
    </StoreCtx.Provider>
  );
}

// Key caps read as the brand book spells them: "Right Ctrl", not "Ctrl (R)".
function shortcutKeyLabel(k) {
  return { "Ctrl (R)": "Right Ctrl", "Ctrl (L)": "Left Ctrl" }[k] || k;
}

// Display keys (["Ctrl","Shift","R"] / ["Ctrl (R)"]) → engine combo token.
function comboToToken(arr) {
  const map = { "Ctrl": "ctrl", "Ctrl (R)": "ctrl_r", "Right Ctrl": "ctrl_r", "Ctrl (L)": "ctrl_l",
    "Alt": "alt", "Shift": "shift", "Super": "super", "D": "d" };
  return arr.map((k) => map[k] || k.toLowerCase()).join("+");
}
