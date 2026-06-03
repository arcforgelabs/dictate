// views.jsx — the seven settings surfaces. Reads/acts through useStore().
import { useState, useEffect } from "react";
import { Icon, Brand } from "./icons.jsx";
import { Combo, Chip, Dot, Toggle, Seg, Row } from "./primitives.jsx";
import { useStore, MODELS, modelById, formatHistoryTime } from "./store.jsx";

/* ============================== STATUS ============================== */
function StatusView() {
  const s = useStore();
  const m = modelById(s.model);
  const rec = s.recording;
  return (
    <div className="view dash">
      <div className="view-head"><div className="crumb">Status</div></div>

      <div className={"hero" + (rec ? " live" : "")}>
        <div className="orb"><Icon name="mic" size={26} /></div>
        <div className="body">
          <div className="statusline">
            <Dot live />
            <span className="t-label" style={{ color: "var(--live)" }}>{rec ? "Listening" : "Ready"}</span>
            <span className="t-meta">·&nbsp; {s.micConnected ? "microphone connected" : "no microphone"}</span>
          </div>
          <h2 className="t-title">{rec ? "Listening…" : "Ready to dictate"}</h2>
          <div className="sub">Hold your shortcut, speak, and release — text types straight into the app you're using.</div>
        </div>
        <div className="keyhint">
          <span className="t-label">Hold</span>
          <Combo keys={s.shortcut} lg />
        </div>
      </div>

      <div className="dash-grid">
        <div className="dash-col">
          <div className="section">
            <div className="lead">
              <h3 className="t-heading">Try it</h3>
            </div>
            <button className="btn primary block"
              onPointerDown={s.dictateStart} onPointerUp={s.dictateStop} onPointerLeave={s.dictateStop}>
              <Icon name="mic" size={17} />{rec ? "Listening — release to insert" : "Hold to try dictation"}
            </button>
            <div className="target">
              <div className="bar"><span className="dots"><i /><i /><i /></span><span>Untitled — Notes</span></div>
              <div className="area">
                {s.targetText ? <span>{s.targetText}</span> : <span className="ph">Your dictated text appears here…</span>}
                {(rec || s.typing) && <span className="caret" />}
              </div>
            </div>
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

          <div className="card pad">
            <Row icon="device" label="Microphone" help="Audio input device">
              <button className="select">{s.device}<Icon name="chevd" size={14} style={{ color: "var(--muted)" }} /></button>
            </Row>
            <Row icon="keyboard" label="Push-to-talk" help="Hold to talk, or toggle on and off">
              <Seg options={[{ v: "hold", l: "Hold" }, { v: "toggle", l: "Toggle" }]} value={s.activation} onChange={s.setActivation} />
            </Row>
            <Row icon="power" label="Launch on sign-in" help="Start Dictate automatically">
              <Toggle on={s.startup} onChange={s.setStartup} />
            </Row>
          </div>
        </div>
      </div>
    </div>
  );
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
        <p className="t-meta">Pick how Dictate turns your speech into text. Hosted models need a key, kept in your system keychain.</p></div>

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
                      <Icon name="shield" size={14} style={{ color: "var(--live)" }} />Stored in OS secret store</span>
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
  const save = () => { if (caught) { s.setShortcut(caught); s.toast("Shortcut updated"); } setArmed(false); setCaught(null); };

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

/* ============================== HISTORY ============================== */
function HistoryView() {
  const s = useStore();
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 15000);
    return () => clearInterval(id);
  }, []);
  const copy = (it) => { try { navigator.clipboard && navigator.clipboard.writeText(it.text); } catch (e) {} s.toast("Copied to clipboard"); };
  return (
    <div className="view">
      <div className="view-head"><div className="row"><div>
        <div className="crumb">Recent history</div><h2 className="t-title">Recent dictations</h2>
        <p className="t-meta">A small local safety net — recover text if it landed in the wrong place.</p></div>
        {s.history.length > 0 && <button className="btn ghost sm danger" onClick={s.clearHistory}><Icon name="trash" size={15} />Clear</button>}
      </div></div>

      {s.history.length === 0 ? (
        <div className="card tight" style={{ textAlign: "center", padding: "44px 20px", color: "var(--muted)" }}>
          <Icon name="history" size={26} style={{ color: "var(--faint)", margin: "0 auto 10px" }} />
          <div className="t-heading" style={{ color: "var(--fg)" }}>Nothing here yet</div>
          <div className="t-meta" style={{ marginTop: 4 }}>Your recent dictations will show up here for quick recovery.</div>
        </div>
      ) : (
        <div className="card pad">
          {s.history.map((it, i) => (
            <div className="row" key={it.id}>
              <span className="ic" style={{ width: 22, height: 22, borderRadius: "50%", background: "var(--surface-2)", border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>
                <span className="t-mono" style={{ fontSize: 10.5 }}>{i + 1}</span></span>
              <div className="main">
                <div className="t-mono" style={{ color: "var(--subtle)", fontSize: 10.5 }}>{formatHistoryTime(it.createdAt)}</div>
                <div style={{ fontSize: 13.5, marginTop: 3, lineHeight: 1.45, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{it.text}</div>
              </div>
              <div className="ctrl"><button className="btn ghost sm" onClick={() => copy(it)}><Icon name="copy" size={15} />Copy</button></div>
            </div>
          ))}
        </div>
      )}
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
            <button className="btn sm" onClick={s.checkUpdates} disabled={!!s.updateStatus?.checking} style={{ opacity: s.updateStatus?.checking ? .6 : 1 }}>
              {s.updateStatus?.checking ? "Checking..." : "Check for updates"}
            </button></Row>
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
  startup: StartupView,
  advanced: AdvancedView,
};
