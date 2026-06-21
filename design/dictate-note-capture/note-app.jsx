// note-app.jsx — Dictate note-capture prototype (complete frontend).
// One locked model: the centered microphone IS the record button (press to start
// / press to stop). Every capture is a Note — a short dictation and a long meeting
// are the same object with different duration/states.
// Happy path + every edge: first-run/empty, mic permission denied, no device,
// transcription failure (retry + on-device fallback), on-device fallback active,
// dropped chunk during long recording, interrupted recording, processing at rest,
// note ready, expanded note.
// Light + dark are both first-class. Single breath is the only loop; reduced
// motion degrades loops to a static state-color. Tweaks expose every state.

const { useState: uS, useEffect: uE, useRef: uR, useMemo: uM } = React;

const PREVIEWS = [
  ["live", "Ready"], ["first-run", "First run (empty)"],
  ["mic-denied", "Microphone blocked"], ["no-device", "No microphone"],
  ["rec-short", "Recording — short"], ["rec-long", "Recording — long"],
  ["fallback", "On-device fallback"], ["chunk-drop", "Dropped chunk (long)"],
  ["capture-error", "Capture failed"], ["interrupted", "Interrupted"],
  ["processing", "Processing (at rest)"], ["note", "Note ready"], ["expanded", "Expanded note"],
];
const PREVIEW_SCENARIO = { "rec-short": "short", "rec-long": "long", "chunk-drop": "long" };

/* ---------- small shared pieces ---------- */
function Avatar({ sp, s = 22 }) {
  const o = SPEAKERS[sp] || SPEAKERS.you;
  return <span className="avatar" style={{ width: s, height: s, color: o.color, borderColor: o.color }}>{o.name[0]}</span>;
}
function SpeakerLine({ ln, ts }) {
  const o = SPEAKERS[ln.sp] || SPEAKERS.you;
  return (
    <div className="spk-line">
      <Avatar sp={ln.sp} />
      <div className="spk-body">
        <div className="spk-meta">
          <span className="spk-name" style={{ color: o.color }}>{o.name}</span>
          {ts && <span className="spk-ts t-mono">{fmt(ln.t)}</span>}
        </div>
        <div className="spk-text">{ln.text}</div>
      </div>
    </div>
  );
}
function Notice({ tone = "amber", icon, title, children }) {
  return (
    <div className={"notice " + tone}>
      <span className="nt-ico"><Icon n={icon} s={16} /></span>
      <div className="nt-body"><div className="nt-title">{title}</div>{children && <div className="nt-text">{children}</div>}</div>
    </div>
  );
}

/* ---------- header (one compact settings control) ---------- */
function Header({ onGear }) {
  return (
    <div className="hdr">
      <div className="brand"><span className="brand-mark"><Mark s={17} /></span><span>Dictate</span></div>
      <button className="ibtn" title="Settings" onClick={onGear}><Icon n="gear" s={17} /></button>
    </div>
  );
}

/* ---------- READY + RECORDING (one surface, the morph) ---------- */
function Capture({ a }) {
  const rec = a.screen === "recording";
  const fb = a.fallback;
  const groups = a.groups;
  const last = groups[groups.length - 1];
  const longMode = rec && (a.scenario === "long" || a.elapsed > 75);
  const spOf = (g) => SPEAKERS[g.sp] || SPEAKERS.you;

  return (
    <div className="capture">
      {rec && fb && (
        <Notice tone="amber" icon="cloudoff" title="On-device transcription">
          xAI is unreachable. Speaker labels are limited and live preview is off while offline.
        </Notice>
      )}

      <BreathCradle active={rec} reduced={a.reduce} onToggle={a.toggle} />

      <div className="feedback">
        {!rec ? (
          a.firstRun ? (
            <>
              <div className="status">Welcome to Dictate</div>
              <div className="status-sub">Press the mic and speak. Your words become a note you can read, edit, then insert anywhere.</div>
              <div className="status-hint t-mono">or hold <Keys combo="⌃+⌥+D" /></div>
              <div className="empty-hint">No notes yet — your captures will appear here.</div>
            </>
          ) : (
            <>
              <div className="status">Ready to capture</div>
              <div className="status-sub">Press the mic and speak — it becomes a note.</div>
              <div className="status-hint t-mono">or hold <Keys combo="⌃+⌥+D" /></div>
            </>
          )
        ) : (
          <>
            <div className="status live">Recording</div>
            <div className="timer t-mono">{fmt(a.elapsed)}</div>
            {fb ? (
              <div className="preview-line" aria-live="polite"><span className="pl-wait">Live preview is off on-device — transcript is ready after you stop.</span></div>
            ) : (
              <div className="preview-line" aria-live="polite">
                {last ? (<><span className="pl-name" style={{ color: spOf(last).color }}>{spOf(last).name}</span> {last.text}<span className="ts-caret" /></>) : <span className="pl-wait">Listening for speech…</span>}
              </div>
            )}
          </>
        )}
      </div>

      {longMode && !fb && (
        a.chunkDrop ? (
          <div className="longstrip amber t-mono"><span className="wdot" />Reconnecting — your audio is safe</div>
        ) : (
          <div className="longstrip t-mono"><span className="dot live" />Saved as you speak</div>
        )
      )}
    </div>
  );
}

/* ---------- STANDBY (blocked / error / interrupted — non-interactive mic) ---------- */
function Standby({ tone = "muted", icon, title, sub, hint, notice, actions }) {
  return (
    <div className="capture">
      {notice}
      <div className="recwrap">
        <div className={"recbtn " + tone} aria-hidden="true"><span className="rb-ico"><Icon n={icon} s={32} /></span></div>
      </div>
      <div className="feedback">
        <div className="status">{title}</div>
        <div className="status-sub">{sub}</div>
        {hint && <div className="status-hint t-mono">{hint}</div>}
        <div className="standby-actions">
          {actions.map((ac, i) => (
            <button key={i} className={"btn " + (ac.kind || "")} onClick={ac.on}>
              {ac.icon && <Icon n={ac.icon} s={15} />}{ac.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- PROCESSING (calm, indeterminate; long recordings only) ---------- */
function Processing({ a }) {
  const shownLines = uM(() => {
    const frac = a.proc.total ? a.proc.done / a.proc.total : 0;
    return a.script.slice(0, Math.max(1, Math.round(a.script.length * frac)));
  }, [a.proc.done, a.proc.total, a.script]);
  return (
    <div className="proc">
      <div className="proc-head">
        <div className="status">Transcribing…</div>
        <div className="status-sub">Turning your words into a note.</div>
      </div>
      {a.fallback && <Notice tone="amber" icon="cloudoff" title="On-device transcription">Running locally — speaker labels may be approximate.</Notice>}
      <div className="bar indet" aria-hidden="true"><span /></div>
      <div className="proc-lines" aria-live="polite">
        {shownLines.map((ln, i) => <SpeakerLine key={i} ln={ln} />)}
        {a.proc.done < a.proc.total && <div className="proc-working t-mono"><span className="dot live" /> transcribing…</div>}
      </div>
    </div>
  );
}

/* ---------- NOTE READY (Insert is the single primary) ---------- */
function NoteReady({ a }) {
  const [ovf, setOvf] = uS(false);
  const n = a.note;
  const speakers = uM(() => [...new Set(n.lines.map((l) => l.sp))], [n]);
  const local = !!n.local || a.onDevice;
  return (
    <div className="note">
      <div className="note-head">
        <div className="note-title">{n.title}</div>
        <div className="note-sub t-mono">
          <span><Icon n="clock" s={13} /> {fmt(n.dur)}</span>
          <span><Icon n="users" s={13} /> {speakers.length} {speakers.length === 1 ? "speaker" : "speakers"}</span>
        </div>
      </div>

      <div className="note-body">
        {n.lines.slice(0, 3).map((ln, i) => <SpeakerLine key={i} ln={ln} />)}
        {n.lines.length > 3 && <div className="note-more">+{n.lines.length - 3} more</div>}
      </div>

      {local && <Notice tone="amber" icon="cloudoff" title="Transcribed on-device">Speaker labels may be approximate — xAI was unreachable for this note.</Notice>}

      <div className="note-cta">
        <button className="btn primary block" onClick={() => a.toast("Inserted into the focused app")}><Icon n="insert" s={16} /> Insert</button>
        <div className="note-sub-actions">
          <button className="btn" onClick={() => a.go("expanded")}><Icon n="expand" s={15} /> Open note</button>
          <div className="ovf-wrap">
            <button className="btn ghost ovf" aria-label="More — Copy, Export" aria-expanded={ovf} onClick={() => setOvf((v) => !v)}><Icon n="more" s={16} /></button>
            {ovf && (
              <>
                <div className="ovf-scrim" onClick={() => setOvf(false)} />
                <div className="ovf-menu">
                  <button onClick={() => { setOvf(false); a.toast("Copied transcript"); }}><Icon n="copy" s={15} /> Copy</button>
                  <button onClick={() => { setOvf(false); a.toast("Exported as Markdown"); }}><Icon n="share" s={15} /> Export</button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <button className="newnote" onClick={() => a.go("ready")}>New note</button>
    </div>
  );
}

/* ---------- EXPANDED NOTE ---------- */
function Expanded({ a }) {
  const [q, setQ] = uS("");
  const n = a.note;
  const lines = q ? n.lines.filter((l) => (l.text + " " + (SPEAKERS[l.sp] || {}).name).toLowerCase().includes(q.toLowerCase())) : n.lines;
  return (
    <div className="exp">
      <div className="exp-top">
        <button className="ibtn" onClick={() => a.go("note")} title="Back"><Icon n="back" s={17} /></button>
        <div className="exp-title">{n.title}</div>
        <div className="exp-tools">
          <button className="ibtn" onClick={() => a.toast("Copied transcript")} title="Copy"><Icon n="copy" s={16} /></button>
          <button className="ibtn" onClick={() => a.toast("Exported as Markdown")} title="Export"><Icon n="share" s={16} /></button>
        </div>
      </div>
      <div className="exp-search">
        <Icon n="search" s={15} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search transcript" />
        <button className={"ts-toggle" + (a.timestamps ? " on" : "")} onClick={a.toggleTs}><Icon n="clock" s={13} /> Times</button>
      </div>
      <div className="exp-body">
        {lines.length === 0 && <div className="exp-empty">No matches for “{q}”.</div>}
        {lines.map((ln, i) => <SpeakerLine key={i} ln={ln} ts={a.timestamps} />)}
      </div>
    </div>
  );
}

/* ---------- gear menu (one compact settings popover) ---------- */
function GearMenu({ a, onClose }) {
  return (
    <>
      <div className="sheet-scrim" onClick={onClose} />
      <div className="menu">
        <div className="menu-head t-label">Settings</div>
        <button className="menu-row" onClick={() => a.setTweak("onDevice", !a.onDevice)} role="switch" aria-checked={a.onDevice}>
          <span className="mk">Always on-device <span className="mk-note">private</span></span>
          <span className="mv"><span className={"mswitch" + (a.onDevice ? " on" : "")} /></span>
        </button>
        <div className="menu-div" />
        <div className="menu-seg-row">
          <span className="mk">Appearance</span>
          <div className="mini-seg">
            {["light", "dark"].map((th) => <button key={th} className={a.theme === th ? "on" : ""} onClick={() => a.setTweak("theme", th)}>{th[0].toUpperCase() + th.slice(1)}</button>)}
          </div>
        </div>
        <div className="menu-div" />
        <div className="menu-foot">
          <span className="brand-mark sm"><Mark s={14} /></span>
          <span>Dictate</span>
        </div>
      </div>
    </>
  );
}

function Toasts({ items }) {
  return <div className="toasts">{items.map((t) => <div className="toast" key={t.id}><Icon n="check" s={15} /><span>{t.msg}</span></div>)}</div>;
}

/* =========================== APP =========================== */
const DEFAULTS = /*EDITMODE-BEGIN*/{ "theme": "dark", "onDevice": false, "scenario": "short", "preview": "live", "timestamps": false, "reduce": false }/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(DEFAULTS);
  const [screen, setScreen] = uS("ready");
  const [elapsed, setElapsed] = uS(0);
  const [ti, setTi] = uS(0);
  const [proc, setProc] = uS({ done: 0, total: 0 });
  const [note, setNote] = uS(null);
  const [menu, setMenu] = uS(false);
  const [toasts, setToasts] = uS([]);
  const [firstRun, setFirstRun] = uS(false);
  const [fallback, setFallback] = uS(false);
  const [chunkDrop, setChunkDrop] = uS(false);
  const timers = uR({});
  const tid = uR(0);

  const scenario = PREVIEW_SCENARIO[t.preview] || t.scenario;
  const script = scenario === "long" ? MEETING : SHORT;
  const groups = uM(() => getPartial(script, ti), [script, ti]);

  const clearTimers = () => { Object.values(timers.current).forEach((x) => { clearInterval(x); clearTimeout(x); }); timers.current = {}; };
  const toast = (msg) => { const id = ++tid.current; setToasts((x) => [...x, { id, msg }]); setTimeout(() => setToasts((x) => x.filter((t) => t.id !== id)), 2200); };

  uE(() => { document.documentElement.dataset.theme = t.theme; }, [t.theme]);
  uE(() => { document.documentElement.classList.toggle("reduce-motion", !!t.reduce); }, [t.reduce]);

  function makeNote(dur, lines, local) { return { title: lines.length > 1 ? "Team sync" : "Quick note", dur, lines, local: !!local }; }
  function buildProcessing(dur, lines, startFrac, hold, local) {
    setScreen("processing");
    const total = Math.max(1, Math.ceil(dur / 30));
    const from = Math.round(total * (startFrac || 0));
    setProc({ done: from, total });
    if (hold) return;
    const t0 = Date.now();
    timers.current.proc = setInterval(() => {
      const k = Math.min(1, (Date.now() - t0) / 2200);
      setProc({ done: Math.round(from + (total - from) * k), total });
      if (k >= 1) { clearInterval(timers.current.proc); setNote(makeNote(dur, lines, local)); timers.current.fin = setTimeout(() => setScreen("note"), 380); }
    }, 110);
  }

  // review-only preview jumps
  uE(() => {
    clearTimers();
    setFirstRun(false); setChunkDrop(false);
    const longDur = 2832, shortDur = 14;
    switch (t.preview) {
      case "live": setFallback(false); setScreen("ready"); setElapsed(0); setTi(0); break;
      case "first-run": setFallback(false); setFirstRun(true); setScreen("ready"); setElapsed(0); setTi(0); break;
      case "mic-denied": setFallback(false); setScreen("mic-denied"); break;
      case "no-device": setFallback(false); setScreen("no-device"); break;
      case "rec-short": setFallback(false); setScreen("recording"); setElapsed(8); setTi(10); break;
      case "rec-long": setFallback(false); setScreen("recording"); setElapsed(longDur); setTi(tokens(MEETING).length); break;
      case "chunk-drop": setFallback(false); setChunkDrop(true); setScreen("recording"); setElapsed(longDur); setTi(tokens(MEETING).length); break;
      case "fallback": setFallback(true); setScreen("recording"); setElapsed(22); setTi(0); break;
      case "capture-error": setScreen("capture-error"); break;
      case "interrupted": setFallback(false); setScreen("interrupted"); break;
      case "processing": setFallback(false); buildProcessing(scenario === "long" ? longDur : shortDur, script, 0.5, true); break;
      case "note": setFallback(false); setNote(makeNote(scenario === "long" ? longDur : shortDur, script)); setScreen("note"); break;
      case "expanded": setFallback(false); setNote(makeNote(scenario === "long" ? longDur : shortDur, script)); setScreen("expanded"); break;
      default: break;
    }
    return clearTimers;
    // eslint-disable-next-line
  }, [t.preview, t.scenario]);

  // recording clock + word streamer
  uE(() => {
    if (screen !== "recording") return;
    timers.current.clk = setInterval(() => setElapsed((e) => e + 1), 1000);
    if (!fallback) timers.current.str = setInterval(() => setTi((i) => Math.min(i + 1, tokens(script).length)), 430);
    return () => { clearInterval(timers.current.clk); clearInterval(timers.current.str); };
    // eslint-disable-next-line
  }, [screen, scenario, fallback]);

  const toggle = () => {
    if (screen === "recording") {
      clearTimers();
      const dur = elapsed || (scenario === "long" ? 2832 : 14);
      // felt speed: short dictations go straight to the note — no visible Processing
      if (scenario === "long" || dur > 45) buildProcessing(dur, script, 0, false, fallback);
      else { setNote(makeNote(dur, script, fallback)); setScreen("note"); }
    } else { if (t.preview !== "live") setTweak("preview", "live"); setFallback(!!t.onDevice); setElapsed(0); setTi(0); setScreen("recording"); }
  };
  const go = (s) => { clearTimers(); if (s === "ready") { setElapsed(0); setTi(0); setFallback(false); if (t.preview !== "live") setTweak("preview", "live"); } setScreen(s); };
  const resumeRecording = () => { clearTimers(); setFallback(false); setScreen("recording"); };
  const startFallback = () => { clearTimers(); setFallback(true); setElapsed(elapsed || 4); setTi(0); setScreen("recording"); toast("Switched to on-device"); };
  const keepInterrupted = () => { clearTimers(); buildProcessing(134, SHORT, 0, false, false); };

  const a = {
    screen, elapsed, scenario, reduce: t.reduce, theme: t.theme, onDevice: t.onDevice, timestamps: t.timestamps,
    firstRun, fallback, chunkDrop, groups, script, proc, note,
    setTweak, setFallback, toast, toggle, go, resumeRecording, startFallback, keepInterrupted,
    toggleTs: () => setTweak("timestamps", !t.timestamps),
  };

  return (
    <div className="app">
      <Header onGear={() => setMenu(true)} />
      <div className="screen">
        {(screen === "ready" || screen === "recording") && <Capture a={a} />}
        {screen === "mic-denied" && (
          <Standby tone="muted" icon="micoff"
            title="Microphone access is off"
            sub="Dictate needs the microphone to hear you. Turn it on in System Settings → Privacy & Security → Microphone."
            actions={[
              { label: "Open System Settings", kind: "primary", icon: "gear", on: () => toast("Opening System Settings…") },
              { label: "Try again", kind: "ghost", icon: "refresh", on: () => go("ready") },
            ]} />
        )}
        {screen === "no-device" && (
          <Standby tone="muted" icon="device"
            title="No microphone found"
            sub="Connect a microphone and Dictate will use it automatically."
            actions={[
              { label: "Check again", kind: "primary", icon: "refresh", on: () => toast("No microphone detected yet") },
            ]} />
        )}
        {screen === "capture-error" && (
          <Standby tone="warn" icon="alert"
            title="Couldn’t reach xAI"
            sub="The connection dropped while transcribing. Your audio is safe on this device."
            actions={[
              { label: "Retry", kind: "primary", icon: "refresh", on: resumeRecording },
              { label: "Use on-device instead", kind: "ghost", icon: "lock", on: startFallback },
            ]} />
        )}
        {screen === "interrupted" && (
          <Standby tone="muted" icon="mic"
            title="Recording interrupted"
            sub="Dictate kept what it captured before it stopped — 2:14. Keep it as a note or discard it."
            actions={[
              { label: "Keep as note", kind: "primary", icon: "check", on: keepInterrupted },
              { label: "Discard", kind: "ghost", icon: "trash", on: () => go("ready") },
            ]} />
        )}
        {screen === "processing" && <Processing a={a} />}
        {screen === "note" && note && <NoteReady a={a} />}
        {screen === "expanded" && note && <Expanded a={a} />}
      </div>

      {menu && <GearMenu a={a} onClose={() => setMenu(false)} />}
      <Toasts items={toasts} />

      <TweaksPanel title="Tweaks">
        <TweakSection label="Review states" />
        <TweakSelect label="State" value={t.preview}
          options={PREVIEWS.map(([value, label]) => ({ value, label }))}
          onChange={(v) => setTweak("preview", v)} />
        <TweakRadio label="Scenario" value={t.scenario} options={["short", "long"]} onChange={(v) => setTweak("scenario", v)} />
        <TweakSection label="Theme & motion" />
        <TweakRadio label="Appearance" value={t.theme} options={["light", "dark"]} onChange={(v) => setTweak("theme", v)} />
        <TweakToggle label="Reduce motion" value={t.reduce} onChange={(v) => setTweak("reduce", v)} />
        <TweakButton label="Reset to ready" onClick={() => { setTweak("preview", "live"); go("ready"); }} />
      </TweaksPanel>
    </div>
  );
}

Object.assign(window, { App });
