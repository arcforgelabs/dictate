// views.jsx — the seven settings surfaces. Reads/acts through useStore().
import { useState, useEffect, useMemo } from "react";
import { Icon, Brand } from "./icons.jsx";
import { Combo, Chip, Dot, Toggle, Seg, Row } from "./primitives.jsx";
import { useStore, MODELS, modelById, formatHistoryTime } from "./store.jsx";

/* ============================== STATUS ============================== */
function StatusView() {
  const s = useStore();
  const m = modelById(s.model);
  const rec = s.recording;
  const recordingActive = !!s.noteRecording;
  const statusLabel = recordingActive ? "Recording" : rec ? "Listening" : "Ready";
  return (
    <div className="view dash">
      <div className="view-head"><div className="crumb">Status</div></div>

      <div className={"hero" + (rec || recordingActive ? " live" : "")}>
        <div className="orb"><Icon name="mic" size={26} /></div>
        <div className="body">
          <div className="statusline">
            <Dot live />
            <span className="t-label" style={{ color: rec || recordingActive ? "var(--live)" : "var(--subtle)" }}>{statusLabel}</span>
            <span className="t-meta">·&nbsp; {s.micConnected ? "microphone connected" : "no microphone"}</span>
          </div>
          <h2 className="t-title">{recordingActive ? "Recording nearby speech" : rec ? "Quick dictation is listening" : "Ready"}</h2>
          <div className="sub">{recordingActive
            ? "Stop recording to transcribe the raw conversation with speaker labels."
            : "Use quick dictation to insert text, or Record to capture a longer conversation."}</div>
          {s.transcript?.text ? (
            <div className="t-meta" style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
              <span className="t-label" style={{ color: "var(--fg)" }}>
                {s.transcript.phase === "final" ? "Final transcript" : "Live transcript"}
              </span>
              <span>{s.transcript.text}</span>
            </div>
          ) : null}
        </div>
        <div className="keyhint">
          <span className="t-label">Hold</span>
          <Combo keys={s.shortcut} lg />
        </div>
      </div>

      {s.updateStatus?.shellStale ? (
        <button className="update-banner" onClick={() => s.setView("update")}>
          <span className="banner-dot"><Dot amber /></span>
          <span className="banner-main">
            <span className="banner-title">Engine updated — app window still old</span>
            <span className="banner-copy">This window is still the v{s.updateStatus.shell?.current || "old"} build. Update the app to catch up.</span>
          </span>
          <span className="btn sm">Update</span>
        </button>
      ) : null}

      <div className="dash-grid">
        <div className="dash-col">
          <div className="section">
            <div className="lead">
              <h3 className="t-heading">Capture</h3>
            </div>
            <div className="capture-actions">
              <button className={"action-tile" + (rec ? " active" : "")}
                onPointerDown={s.dictateStart} onPointerUp={s.dictateStop} onPointerLeave={s.dictateStop}>
                <span className="tile-ic"><Icon name="mic" size={18} /></span>
                <span className="tile-main">
                  <span className="tile-title">{rec ? "Listening" : "Quick dictation"}</span>
                  <span className="tile-sub">{rec ? "Release to insert text" : "Types into the focused app"}</span>
                </span>
                <Combo keys={s.shortcut} />
              </button>
              <button className={"action-tile" + (s.noteRecording ? " active danger" : "")}
                onClick={s.toggleNoteRecording}>
                <span className="tile-ic"><Icon name={s.noteRecording ? "square" : "clock"} size={18} /></span>
                <span className="tile-main">
                  <span className="tile-title">{s.noteRecording ? "Stop recording" : "Record conversation"} <Chip>xAI · speaker labels</Chip></span>
                  <span className="tile-sub">{s.noteRecording ? "Transcribe and save raw notes" : "Saved to history as a transcript · audio goes to xAI"}</span>
                </span>
              </button>
            </div>
            <div className="target">
              <div className="bar"><span className="dots"><i /><i /><i /></span><span>Untitled — Notes</span></div>
              <div className="area">
                {s.targetText ? <span>{s.targetText}</span> : <span className="ph">Your dictated text appears here…</span>}
                {(rec || s.typing) && <span className="caret" />}
              </div>
            </div>
            {(s.noteRecording || s.noteText) && (
              <div className="note-result">
                <div className="t-label" style={{ color: s.noteRecording ? "var(--live)" : "var(--subtle)", marginBottom: 8 }}>
                  {s.noteRecording ? "Recording" : "Latest recording"}
                </div>
                <div style={{ whiteSpace: "pre-wrap", fontSize: 13.5, lineHeight: 1.45 }}>
                  {s.noteRecording ? "Listening nearby. Stop to transcribe and save the raw dictation." : s.noteText}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="dash-col">
          <button className="minic modelcard" onClick={() => s.setView("model")}>
            <div className="top"><span className="t-label">Transcription model</span><Icon name="chev" size={15} style={{ color: "var(--faint)" }} /></div>
            <div className="modelrow">
              <span className="brand">{m.brand ? <Brand name={m.brand} /> : <Icon name="cpu" size={18} />}</span>
              <span className="mname">
                <span className="v">{m.name.split(" · ")[0]}{m.local ? <Chip live>LOCAL</Chip> : <Chip>{m.provider.toUpperCase()}</Chip>}</span>
              </span>
            </div>
          </button>

          <div className="section">
            <div className="lead"><h3 className="t-heading">Capture</h3></div>
            <div className="card pad">
              <Row icon="device" label="Microphone" help="Audio input device">
                <button className="select">{s.device}<Icon name="chevd" size={14} style={{ color: "var(--muted)" }} /></button>
              </Row>
            </div>
          </div>

          <div className="section">
            <div className="lead"><h3 className="t-heading">App</h3></div>
            <div className="card pad">
              <Row icon="power" label="Launch on sign-in" help="Start Dictate automatically">
                <Toggle on={s.startup} onChange={s.setStartup} />
              </Row>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================ APP UPDATE ============================ */
function UpdateView() {
  const s = useStore();
  const u = s.updateStatus || {};
  const engine = u.engine || { current: u.currentVersion || s.version, latest: u.latestVersion, path: "~/.local/bin/dictate" };
  const shell = u.shell || { current: u.currentVersion || s.version, latest: u.latestVersion, path: "/usr/bin/dictate-ui-shell" };
  const latest = u.latestVersion || engine.latest || shell.latest || s.version;
  const shellStale = !!u.shellStale || !!shell.stale;
  const phase = u.updating ? "working" : u.checking ? "checking" : u.phase || (u.updateAvailable || shellStale ? "available" : "current");
  const installKind = u.installKind || "manual";
  const isSource = installKind.endsWith("-source");
  const hasUpdateCommand = !!u.commands?.update;
  const hasReleaseUrl = !!u.commands?.release;
  const primaryLabel = phase === "restart" ? "How to restart"
    : phase === "checking" ? "Checking..."
      : phase === "working" ? "Updating..."
        : u.updateAvailable || shellStale ? isSource ? "Update app" : "Open release"
          : "Check again";
  const primaryAction = phase === "restart" ? () => s.toast("Quit and reopen Dictate to finish the update.")
    : u.updateAvailable || shellStale ? s.startUpdate : s.checkUpdates;
  const failed = phase === "failed" || !!u.errorCode;
  const manual = !isSource;
  const updateSteps = updateStepCopy(installKind);
  const copyCommand = () => {
    const cmd = u.commands?.update || u.commands?.release || "";
    try { navigator.clipboard && navigator.clipboard.writeText(cmd); } catch (e) {}
    if (cmd) s.toast(hasUpdateCommand ? "Copied update command" : "Copied release URL");
  };

  return (
    <div className="view">
      <div className="view-head">
        <div className="crumb">App update</div>
        <h2 className="t-title">App update</h2>
        <p className="t-meta">Dictate updates in two parts — the background engine and this app window. Both should be on the same version.</p>
      </div>

      <div className="version-panel card tight">
        <VersionRow label="Engine" path={engine.path} current={engine.current} latest={latest} stale={!!engine.stale} />
        <VersionRow label="App window" path={shell.path} current={shell.current} latest={latest} stale={shellStale} />
      </div>

      {shellStale ? (
        <div className="update-callout">
          <div className="t-label">Action needed</div>
          <h3>Engine updated, app window still old</h3>
          <p>The engine is on v{engine.current || latest}, but this window is still the v{shell.current || "old"} build packaged in {shell.path || "the desktop shell"}. Update the app so the window matches, then restart.</p>
        </div>
      ) : null}

      <div className="card tight update-card">
        <div>
          <h3 className="t-heading">{failed ? failureTitle(u, installKind) : phaseTitle(phase, manual)}</h3>
          <p className="t-meta">{failed ? failureCopy(u, installKind) : phaseCopy(phase, installKind, latest, shell.current)}</p>
        </div>

        {failed && missingDeps(u).length ? (
          <div className="deps">
            <div className="t-label">Missing build dependencies</div>
            <div className="dep-list">{missingDeps(u).map((d) => <span key={d}>{d}</span>)}</div>
          </div>
        ) : null}

        <div className="update-steps">
          {updateSteps.map((step, i) => (
            <div className="step" key={step}><span>{i + 1}</span>{step}</div>
          ))}
        </div>

        <div className="row-actions" style={{ justifyContent: "flex-start" }}>
          <button className="btn primary" onClick={primaryAction} disabled={!!u.checking || !!u.updating}>
            <Icon name={phase === "restart" ? "power" : "download"} size={16} />{primaryLabel}
          </button>
          <button className="btn" onClick={s.checkUpdates} disabled={!!u.checking}>Check again</button>
        </div>

        <details className="advanced-update">
          <summary>{hasUpdateCommand ? "Advanced — update from a terminal" : "Release page"}</summary>
          <div className="command-row">
            <code>{hasUpdateCommand ? u.commands.update : hasReleaseUrl ? u.commands.release : "No local updater or release URL is available for this install."}</code>
            {(hasUpdateCommand || hasReleaseUrl) && <button className="btn sm" onClick={copyCommand}>Copy</button>}
          </div>
        </details>
      </div>
    </div>
  );
}

function VersionRow({ label, path, current, latest, stale }) {
  return (
    <div className="version-row">
      <div>
        <div className="lbl">{label}</div>
        <div className="help">{path || "Not detected"}</div>
      </div>
      <div className="version-values">
        <Chip live={!stale}>{current || "unknown"}</Chip>
        {stale && latest ? <><Icon name="chev" size={14} style={{ color: "var(--subtle)" }} /><Chip>{latest}</Chip></> : null}
      </div>
    </div>
  );
}

function phaseTitle(phase, manual) {
  if (phase === "checking") return "Checking for updates";
  if (phase === "working") return manual ? "Opening the latest release" : "Updating the app";
  if (phase === "restart") return "Restart to finish";
  if (phase === "current") return "Everything is current";
  return manual ? "Update available" : "Update the app";
}

function phaseCopy(phase, installKind, latest, current) {
  if (phase === "checking") return "Looking for the latest Dictate release and comparing the engine with this app window.";
  if (phase === "working") return "Dictate has started the safest updater available for this install.";
  if (phase === "restart") return `The new v${latest} app window is installed. Restart Dictate to switch over; your settings and history are kept.`;
  if (phase === "current") return "The engine and app window are already aligned.";
  if (installKind.includes("windows") && !installKind.endsWith("-source")) return "Download and run the latest signed Windows installer. Dictate does not have an in-app Tauri updater wired yet.";
  if (installKind.includes("linux") && !installKind.endsWith("-source")) return "Open the latest Linux package, then install it with your package manager or replace the AppImage.";
  return `Brings this window from v${current || "old"} to v${latest}.`;
}

function updateStepCopy(installKind) {
  if (installKind.endsWith("-source")) return ["Run the source updater", "Refresh the desktop app files", "Restart so the new window loads"];
  if (installKind.includes("windows")) return ["Download the latest signed installer", "Run the installer", "Restart so the new window loads"];
  if (installKind.includes("linux")) return ["Download the latest Linux package", "Install it with your package manager", "Restart so the new window loads"];
  return ["Download the latest signed package", "Install the package", "Restart so the new window loads"];
}

function failureTitle(u, installKind) {
  if (u.errorCode === "build_deps_missing" || installKind === "linux-source") return "Couldn't rebuild the app window";
  if (u.errorCode === "webview2_missing") return "Microsoft Edge WebView2 Runtime is required";
  return "Could not update Dictate";
}

function failureCopy(u, installKind) {
  if (u.errorCode === "build_deps_missing" || installKind === "linux-source") return "The engine updated fine, but building the desktop window needs system packages that are not installed.";
  if (u.errorCode === "webview2_missing") return "Install the WebView2 Runtime, then run the Dictate installer again.";
  return u.errorDetail || u.error || "Try again, or open the latest release and install it manually.";
}

function missingDeps(u) {
  if (Array.isArray(u.missingDeps)) return u.missingDeps;
  if (u.errorCode === "build_deps_missing") return ["libwebkit2gtk-4.1-dev", "librsvg2-dev"];
  return [];
}

/* =============================== MODEL =============================== */
function ModelView() {
  const s = useStore();
  const [draftFor, setDraftFor] = useState(null);
  const [val, setVal] = useState("");
  const hasKey = (m) => m.local || s.keys[m.brand];

  const choose = (m) => {
    if (hasKey(m)) { s.setModel(m.id); }
    else { setDraftFor(m.id); setVal(""); }
  };
  const saveKey = (m) => {
    if (val.trim().length < 6) { s.toast("That key looks too short", { bad: true }); return; }
    s.saveKey(m.brand, val.trim(), m.id);
    setDraftFor(null);
  };

  return (
    <div className="view">
      <div className="view-head"><div className="crumb">Model</div><h2 className="t-title">Transcription model</h2>
        <p className="t-meta">Pick how Dictate turns speech into text. Hosted models need a key, stored locally by Dictate.</p></div>

      <div className="opts">
        {MODELS.map((m) => {
          const sel = s.model === m.id, key = hasKey(m);
          return (
            <div key={m.id} style={{ display: "flex", flexDirection: "column" }}>
              <button className={"opt" + (sel ? " sel" : "")} onClick={() => choose(m)}>
                <span className="radio" />
                <span className="brand">{m.brand ? <Brand name={m.brand} /> : <Icon name="cpu" size={17} />}</span>
                <span className="main">
                  <span className="ot">{m.name}{m.local && <Chip live>LOCAL</Chip>}</span>
                  <span className="od">{m.desc}</span>
                </span>
                {m.local ? null : key ? <Chip live>CONNECTED</Chip> : <Chip>NEEDS KEY</Chip>}
              </button>
              {draftFor === m.id && (
                <div className="card tight" style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 12 }}>
                  <div className="field">
                    <label className="t-label">{m.keyName}</label>
                    <div className="input">
                      <Icon name="key" size={16} style={{ color: "var(--muted)" }} />
                      <input className="mono" autoFocus placeholder={m.keyPrefix + "································"}
                        value={val} onChange={(e) => setVal(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && saveKey(m)} />
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <button className="btn primary sm" onClick={() => saveKey(m)}>Save &amp; select</button>
                    <button className="btn ghost sm" onClick={() => setDraftFor(null)}>Cancel</button>
                    <span className="t-meta" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
                      <Icon name="shield" size={14} style={{ color: "var(--live)" }} />Stored locally</span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {modelById(s.model).local && (
        <div className="section">
          <div className="lead"><Icon name="cpu" size={17} style={{ color: "var(--muted)" }} /><h3 className="t-heading">Local compute</h3></div>
          <div className="card pad">
            <Row label="Device" help="Where the local model runs">
              <Seg options={[{ v: "auto", l: "Auto" }, { v: "cpu", l: "CPU" }, { v: "gpu", l: "GPU" }]} value={s.device2} onChange={s.setDevice2} />
            </Row>
            <Row label="Precision" help="Lower precision is faster and lighter">
              <button className="select">{s.compute}<Icon name="chevd" size={14} style={{ color: "var(--muted)" }} /></button>
            </Row>
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================ PUSH-TO-TALK ============================ */
function PttView() {
  const s = useStore();
  const [armed, setArmed] = useState(false);
  const [caught, setCaught] = useState(null);
  useEffect(() => { s.setCapturing(armed); return () => s.setCapturing(false); }, [armed]);
  useEffect(() => {
    if (!armed) return;
    const onKey = (e) => {
      e.preventDefault();
      if (e.key === "Escape") { setArmed(false); setCaught(null); return; }
      const m = [];
      if (e.ctrlKey) m.push(e.code === "ControlRight" ? "Ctrl (R)" : "Ctrl");
      if (e.altKey) m.push("Alt"); if (e.shiftKey) m.push("Shift"); if (e.metaKey) m.push("Super");
      const k = e.key;
      if (!["Control", "Alt", "Shift", "Meta"].includes(k)) m.push(k.length === 1 ? k.toUpperCase() : k);
      if (m.length) setCaught(m);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [armed]);
  const save = async () => {
    if (caught) {
      try {
        await s.setShortcut(caught);
        s.toast("Shortcut updated");
      } catch (e) {
        // The store already restored the previous shortcut and showed the error.
      }
    }
    setArmed(false);
    setCaught(null);
  };

  return (
    <div className="view">
      <div className="view-head"><div className="crumb">Push-to-talk</div><h2 className="t-title">Push-to-talk shortcut</h2>
        <p className="t-meta">The key you hold while speaking. Release to transcribe and insert.</p></div>

      <div className={"capture" + (armed ? " armed" : "")}>
        <div className="keys">
          {armed ? (caught ? <Combo keys={caught} lg /> : <span className="t-meta">Press a key combination…</span>)
            : <Combo keys={s.shortcut} lg />}
        </div>
        <div className="t-meta">{armed ? "Listening for keys — Esc to cancel" : "Current shortcut"}</div>
        <div style={{ display: "flex", gap: 10 }}>
          {armed
            ? <><button className="btn primary sm" disabled={!caught} onClick={save} style={{ opacity: caught ? 1 : .5 }}>Save shortcut</button>
                <button className="btn ghost sm" onClick={() => { setArmed(false); setCaught(null); }}>Cancel</button></>
            : <button className="btn sm" onClick={() => { setArmed(true); setCaught(null); }}><Icon name="keyboard" size={15} />Rebind</button>}
        </div>
      </div>

      <div className="card pad">
        <Row icon="bolt" label="Activation" help="Hold the key down, or tap once to start and again to stop">
          <Seg options={[{ v: "hold", l: "Hold" }, { v: "toggle", l: "Toggle" }]} value={s.activation} onChange={s.setActivation} />
        </Row>
        <Row icon="wave" label="Insertion" help="How transcribed text reaches the focused app">
          <button className="select">Type at cursor<Icon name="chevd" size={14} style={{ color: "var(--muted)" }} /></button>
        </Row>
      </div>
    </div>
  );
}

/* ============================= HOTWORDS ============================= */
function HotwordsView() {
  const s = useStore();
  const [val, setVal] = useState("");
  const add = () => { const w = val.trim(); if (w) { s.addHotword(w); setVal(""); } };
  return (
    <div className="view">
      <div className="view-head"><div className="crumb">Hotwords {s.hotwords.length}</div><h2 className="t-title">Hotwords</h2>
        <p className="t-meta">Names and terms the model should always spell correctly — product names, people, jargon.</p></div>
      <div className="card tight" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="words">
          {s.hotwords.map((w) => (
            <span key={w} className="word">{w}<button onClick={() => s.removeHotword(w)} aria-label={"Remove " + w}><Icon name="x" size={13} /></button></span>
          ))}
          {s.hotwords.length === 0 && <span className="t-meta">No hotwords yet.</span>}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <div className="word-input" style={{ flex: 1, maxWidth: 260 }}>
            <Icon name="plus" size={14} style={{ color: "var(--subtle)" }} />
            <input placeholder="Add a word…" value={val} style={{ width: "100%" }}
              onChange={(e) => setVal(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
          </div>
          <button className="btn sm" onClick={add} disabled={!val.trim()} style={{ opacity: val.trim() ? 1 : .5 }}>Add word</button>
        </div>
      </div>
      <p className="t-meta" style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <Icon name="pin" size={14} style={{ color: "var(--subtle)" }} />Hotwords stay on this device and are never packaged or synced.</p>
    </div>
  );
}

/* ============================== HISTORY (Notes list + search) ============================== */

// Highlight the first case-insensitive match of q inside text with a .hl span.
function hilite(text, q) {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text;
  return <>{text.slice(0, i)}<mark className="hl">{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

function HistoryView() {
  const s = useStore();
  const [q, setQ] = useState("");
  const [, tick] = useState(0);

  // Refresh relative timestamps every 15 s without a full re-render.
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 15000);
    return () => clearInterval(id);
  }, []);

  const all = s.history || [];
  const filtered = useMemo(() => {
    if (!q) return all;
    const sq = q.toLowerCase();
    return all.filter((n) => n.text.toLowerCase().includes(sq));
  }, [q, all]);

  // Open a history note in the ExpandedNote read view; back will return here.
  const openNote = (note) => {
    s.setCurrentNote(note);
    s.setExpandedFrom("history");
    s.setView("home");
    s.setNoteView("expanded");
  };

  const copyNote = (note) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(note.text)
        .then(() => s.toast("Copied to clipboard"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };

  const empty = all.length === 0;

  return (
    <div className="notes">
      {/* Own header: back → capture home, title. */}
      <div className="notes-top">
        <button className="ibtn" title="Back" onClick={() => s.setView("home")}>
          <Icon name="back" size={17} />
        </button>
        <div className="notes-title">Notes</div>
      </div>

      {/* Search field — autofocused, with ×-clear when non-empty */}
      <div className="notes-search">
        <Icon name="search" size={15} />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search notes"
          aria-label="Search notes"
        />
        {q && (
          <button className="ibtn sm" onClick={() => setQ("")} title="Clear search">
            <Icon name="x" size={15} />
          </button>
        )}
      </div>

      {/* Notes list — three states: empty-ever / no-results / rows */}
      <div className="notes-list">
        {empty ? (
          <div className="notes-blank">
            <span className="nb-ico"><Icon name="history" size={22} /></span>
            <div className="nb-title">Your notes will appear here</div>
            <div className="nb-sub">Every dictation is saved as a note you can search and reuse.</div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="notes-blank">
            <div className="nb-title">No notes match &ldquo;{q}&rdquo;.</div>
            <div className="nb-sub">Try a different word.</div>
          </div>
        ) : (
          filtered.map((note) => (
            <div
              className="note-row"
              key={note.id}
              role="button"
              tabIndex={0}
              onClick={() => openNote(note)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNote(note); } }}
            >
              <div className="nr-body">
                {/* 2-line-clamped preview with search highlight on the first match */}
                <div className="nr-text">{hilite(note.text, q)}</div>
                <div className="nr-meta t-mono">
                  <span>{formatHistoryTime(note.createdAt)}</span>
                </div>
              </div>
              {/* Per-row copy — revealed on hover/focus-within via CSS */}
              <button
                className="ibtn nr-copy"
                title="Copy note"
                onClick={(e) => { e.stopPropagation(); copyNote(note); }}
              >
                <Icon name="copy" size={16} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ============================== STARTUP ============================== */
function StartupView() {
  const s = useStore();
  return (
    <div className="view">
      <div className="view-head"><div className="crumb">Startup</div><h2 className="t-title">Startup &amp; behaviour</h2></div>
      <div className="card pad">
        <Row icon="power" label="Launch on sign-in" help="Start Dictate automatically when you log in">
          <Toggle on={s.startup} onChange={s.setStartup} /></Row>
        <Row icon="device" label="Start in the tray" help="Open quietly to the tray instead of showing this window">
          <Toggle on={s.trayOnly} onChange={s.setTrayOnly} /></Row>
        <Row icon="mic" label="Show listening overlay" help="Display the floating pill while you dictate">
          <Toggle on={s.overlay} onChange={s.setOverlay} /></Row>
        <Row icon="bolt" label="Play a sound cue" help="A soft tick when recording starts and stops">
          <Toggle on={s.sound} onChange={s.setSound} /></Row>
      </div>
    </div>
  );
}

/* ============================== ADVANCED ============================== */
function AdvancedView() {
  const s = useStore();
  const [checks, setChecks] = useState(null);
  const canStartUpdate = !!s.updateStatus?.updateAvailable && !s.updateStatus?.checking;
  const updateHelp = (() => {
    const u = s.updateStatus || {};
    if (u.checking) return `Version ${s.version} · checking`;
    if (u.updateAvailable && u.latestVersion) return `Version ${s.version} · ${u.latestVersion} available`;
    if (u.checked) return `Version ${s.version} · up to date`;
    if (u.error) return `Version ${s.version} · unable to check`;
    return `Version ${s.version} · not checked`;
  })();
  const runDoctor = () => {
    setChecks(null);
    s.runDoctor((report) => {
      const base = report.checks || [];
      setChecks(base.map((b) => ({ ...b, ok: false })));
      base.forEach((b, i) => setTimeout(() =>
        setChecks((cs) => cs.map((c, j) => (j === i ? { ...c, ok: b.ok } : c))), 500 + i * 550));
      setTimeout(() => s.toast(report.ok ? "Doctor: all checks passed" : "Doctor: some checks need attention"),
        500 + base.length * 550);
    });
  };
  return (
    <div className="view">
      <div className="view-head"><div className="crumb">Advanced</div><h2 className="t-title">Advanced</h2></div>

      <div className="section">
        <div className="lead"><h3 className="t-heading">Appearance</h3></div>
        <div className="card pad">
          <Row icon={s.theme === "dark" ? "moon" : "sun"} label="Theme" help="Warm light or warm dark — both first-class">
            <Seg options={[{ v: "light", l: "Light" }, { v: "dark", l: "Dark" }]} value={s.theme} onChange={s.setTheme} /></Row>
          <Row icon="wave" label="Ambient motion" help="The gentle breathing glow on a live agent">
            <Toggle on={s.ambient} onChange={s.setAmbient} /></Row>
        </div>
      </div>

      <div className="section">
        <div className="lead"><Icon name="shield" size={17} style={{ color: "var(--muted)" }} /><h3 className="t-heading">Diagnostics</h3>
          <button className="btn sm" style={{ marginLeft: "auto" }} onClick={runDoctor}><Icon name="status" size={15} />Run doctor</button></div>
        <div className="card tight">
          {!checks ? <div className="t-meta">Run a quick check of microphone, model, output, secret store and shortcut.</div>
            : <div className="checks">{checks.map((c, i) => (
              <div className="check" key={i}>
                <span className={"st " + (c.ok ? "ok" : "run")}>{c.ok ? <Icon name="check" size={13} /> : <Icon name="refresh" size={13} />}</span>
                <div className="main"><div>{c.label}</div><div className="sub">{c.sub}</div></div>
              </div>))}</div>}
        </div>
      </div>

      <div className="section">
        <div className="lead"><h3 className="t-heading">About</h3></div>
        <div className="card pad">
          <Row icon="download" label="Dictate" help={updateHelp}>
            <div className="row-actions">
              <button className="btn sm" onClick={s.checkUpdates} disabled={!!s.updateStatus?.checking} style={{ opacity: s.updateStatus?.checking ? .6 : 1 }}>
                {s.updateStatus?.checking ? "Checking..." : "Check for updates"}
              </button>
              {canStartUpdate ? (
                <button className="btn primary sm" onClick={s.startUpdate} disabled={!!s.updateStatus?.updating} style={{ opacity: s.updateStatus?.updating ? .6 : 1 }}>
                  {s.updateStatus?.updating ? "Starting..." : "Update"}
                </button>
              ) : null}
            </div></Row>
        </div>
      </div>

      <div className="section">
        <div className="lead"><h3 className="t-heading" style={{ color: "var(--danger)" }}>Danger zone</h3></div>
        <div className="card pad">
          <Row label="Reset settings" help="Restore every option to its default">
            <button className="btn sm danger" onClick={() => s.toast("Settings reset to defaults")}>Reset</button></Row>
          <Row label="Uninstall Dictate" help="Remove the app. Add --remove-user-data to also clear config and history">
            <button className="btn sm danger" onClick={() => s.toast("Uninstall is handled by the installer")}>Uninstall</button></Row>
        </div>
      </div>
    </div>
  );
}

export const VIEWS = {
  status: StatusView,
  model: ModelView,
  ptt: PttView,
  hotwords: HotwordsView,
  history: HistoryView,
  update: UpdateView,
  startup: StartupView,
  advanced: AdvancedView,
};
