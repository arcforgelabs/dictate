// overlays.jsx — listening HUD, command palette (⌘K), toast stack.
const { useState: oS, useEffect: oE, useRef: oR, useMemo: oM } = React;

function ListeningHUD() {
  const s = useStore();
  const [t, setT] = oS(0);
  oE(() => {
    if (!s.recording) { setT(0); return; }
    const start = Date.now();
    const id = setInterval(() => setT((Date.now() - start) / 1000), 100);
    return () => clearInterval(id);
  }, [s.recording]);
  const mm = String(Math.floor(t / 60)).padStart(1, "0"), ss = String(Math.floor(t % 60)).padStart(2, "0");
  return (
    <div className={"hud" + (s.recording && s.overlay ? " show" : "")}>
      <div className="hud-pill">
        <span className="reckdot" />
        <Wave active={s.recording} bars={16} h={22} />
        <span className="txt">Listening</span>
        <span className="timer">{mm}:{ss}</span>
        {s.activation === "hold"
          ? <span className="rel">release to insert</span>
          : <span className="rel">tap to stop</span>}
      </div>
    </div>
  );
}

function CommandPalette() {
  const s = useStore();
  const [q, setQ] = oS("");
  const [cur, setCur] = oS(0);
  const inputRef = oR(null);
  oE(() => { if (s.palette) { setQ(""); setCur(0); setTimeout(() => inputRef.current && inputRef.current.focus(), 40); } }, [s.palette]);

  const items = oM(() => {
    const nav = [
      ["status", "Status", "status"], ["sliders", "Model", "model"], ["keyboard", "Push-to-talk", "ptt"],
      ["hash", "Hotwords", "hotwords"], ["history", "Recent history", "history"],
      ["gear", "Advanced", "advanced"],
    ].map(([icon, label, view]) => ({ icon, label, group: "Go to", run: () => s.setView(view) }));
    const actions = [
      { icon: "mic", label: "Try dictation", group: "Actions", run: () => { s.setView("status"); s.dictateOnce(); } },
      { icon: s.theme === "dark" ? "sun" : "moon", label: s.theme === "dark" ? "Switch to light" : "Switch to dark", group: "Actions", run: () => s.setTheme(s.theme === "dark" ? "light" : "dark") },
      { icon: "status", label: "Run doctor", group: "Actions", run: () => s.setView("advanced") },
      { icon: "trash", label: "Clear recent history", group: "Actions", run: () => s.clearHistory() },
    ];
    const models = MODELS.map(m => ({ icon: null, brand: m.brand, label: "Use " + m.name, meta: m.provider, group: "Models", run: () => { s.setView("model"); if (m.local || s.keys[m.brand]) s.setModel(m.id); } }));
    const all = [...nav, ...actions, ...models];
    if (!q.trim()) return all;
    const lq = q.toLowerCase();
    return all.filter(i => i.label.toLowerCase().includes(lq) || (i.meta || "").toLowerCase().includes(lq));
  }, [q, s.theme, s.keys]);

  oE(() => { if (cur >= items.length) setCur(Math.max(0, items.length - 1)); }, [items.length]);

  const exec = i => { const it = items[i]; if (it) { it.run(); s.setPalette(false); } };
  const onKey = e => {
    if (e.key === "ArrowDown") { e.preventDefault(); setCur(c => Math.min(items.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCur(c => Math.max(0, c - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); exec(cur); }
    else if (e.key === "Escape") { e.preventDefault(); s.setPalette(false); }
  };

  let lastGroup = null;
  return (
    <div className={"scrim" + (s.palette ? " show" : "")} onClick={() => s.setPalette(false)}>
      <div className="cmd" onClick={e => e.stopPropagation()}>
        <div className="cmd-in">
          <Icon name="search" size={18} style={{ color: "var(--muted)" }} />
          <input ref={inputRef} placeholder="Jump to a setting, switch model, run an action…" value={q}
            onChange={e => { setQ(e.target.value); setCur(0); }} onKeyDown={onKey} />
          <Kbd>esc</Kbd>
        </div>
        <div className="cmd-list">
          {items.length === 0 && <div className="cmd-grp" style={{ padding: "16px 12px" }}>No matches</div>}
          {items.map((it, i) => {
            const head = it.group !== lastGroup ? (lastGroup = it.group) : null;
            return <React.Fragment key={i}>
              {head && <div className="cmd-grp">{head}</div>}
              <button className={"cmd-item" + (i === cur ? " cur" : "")} onMouseEnter={() => setCur(i)} onClick={() => exec(i)}>
                {it.brand ? <Brand name={it.brand} /> : <Icon name={it.icon} size={17} />}
                <span>{it.label}</span>{it.meta && <span className="meta">{it.meta}</span>}
              </button>
            </React.Fragment>;
          })}
        </div>
      </div>
    </div>
  );
}

function Toasts() {
  const s = useStore();
  return <div className="toasts">{s.toasts.map(t => (
    <div className="toast" key={t.id}>
      <span className="ic" style={t.bad ? { color: "var(--danger)" } : null}>
        <Icon name={t.bad ? "x" : "check"} size={16} /></span>
      <span>{t.msg}</span>
      {t.undo && <button className="undo" onClick={() => { t.undo(); s.dismiss(t.id); }}>Undo</button>}
    </div>))}</div>;
}

Object.assign(window, { ListeningHUD, CommandPalette, Toasts });
