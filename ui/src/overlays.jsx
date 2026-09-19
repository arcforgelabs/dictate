// overlays.jsx — listening HUD, command palette (⌘K), toast stack.
import { useState, useEffect, useRef, useMemo } from "react";
import { Icon } from "./icons.jsx";
import { Kbd } from "./primitives.jsx";
import { useStore } from "./store.jsx";

export function ListeningHUD() {
  const s = useStore();
  const [t, setT] = useState(0);
  useEffect(() => {
    if (!s.recording) { setT(0); return; }
    const start = Date.now();
    const id = setInterval(() => setT((Date.now() - start) / 1000), 100);
    return () => clearInterval(id);
  }, [s.recording]);
  const mm = String(Math.floor(t / 60)).padStart(1, "0");
  const ss = String(Math.floor(t % 60)).padStart(2, "0");
  // Push-to-talk only — note capture already shows Recording + WaveTimeline in the cradle stack.
  const show = s.recording && s.overlay && !s.noteRecording;
  return (
    <div className={"hud" + (show ? " show" : "")}>
      <div className="hud-pill">
        <span className="reckdot" />
        <Icon name="mic" size={16} />
        <span className="txt">Listening</span>
        <span className="timer">{mm}:{ss}</span>
        {s.activation === "hold"
          ? <span className="rel">release to insert</span>
          : <span className="rel">tap to stop</span>}
      </div>
    </div>
  );
}

export function CommandPalette() {
  const s = useStore();
  const [q, setQ] = useState("");
  const [cur, setCur] = useState(0);
  const inputRef = useRef(null);
  useEffect(() => { if (s.palette) { setQ(""); setCur(0); setTimeout(() => inputRef.current && inputRef.current.focus(), 40); } }, [s.palette]);

  const items = useMemo(() => {
    // The GUI has no settings; the palette is just the daily verbs. Advanced
    // config lives in the `dictate config` CLI, not here.
    const all = [
      { icon: "history", label: "Notes", group: "Go to", run: () => { s.setNoteView(null); s.setView("history"); } },
      { icon: "mic", label: "Try dictation", group: "Actions", run: () => s.dictateOnce() },
      { icon: s.theme === "dark" ? "sun" : "moon", label: s.theme === "dark" ? "Switch to light" : "Switch to dark", group: "Actions", run: () => s.setTheme(s.theme === "dark" ? "light" : "dark") },
      { icon: "trash", label: "Clear notes", group: "Actions", run: () => s.clearHistory() },
    ];
    if (!q.trim()) return all;
    const lq = q.toLowerCase();
    return all.filter((i) => i.label.toLowerCase().includes(lq));
  }, [q, s.theme]);

  useEffect(() => { if (cur >= items.length) setCur(Math.max(0, items.length - 1)); }, [items.length]);

  const exec = (i) => { const it = items[i]; if (it) { it.run(); s.setPalette(false); } };
  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setCur((c) => Math.min(items.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCur((c) => Math.max(0, c - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); exec(cur); }
    else if (e.key === "Escape") { e.preventDefault(); s.setPalette(false); }
  };

  let lastGroup = null;
  return (
    <div className={"scrim" + (s.palette ? " show" : "")} onClick={() => s.setPalette(false)}>
      <div className="cmd" onClick={(e) => e.stopPropagation()}>
        <div className="cmd-in">
          <Icon name="search" size={18} style={{ color: "var(--muted)" }} />
          <input ref={inputRef} placeholder="Search notes, run an action…" value={q}
            onChange={(e) => { setQ(e.target.value); setCur(0); }} onKeyDown={onKey} />
          <Kbd>Esc</Kbd>
        </div>
        <div className="cmd-list">
          {items.length === 0 && <div className="cmd-grp" style={{ padding: "16px 12px" }}>No matches</div>}
          {items.map((it, i) => {
            const head = it.group !== lastGroup ? (lastGroup = it.group) : null;
            return (
              <div key={i}>
                {head && <div className="cmd-grp">{head}</div>}
                <button className={"cmd-item" + (i === cur ? " cur" : "")} onMouseEnter={() => setCur(i)} onClick={() => exec(i)}>
                  <Icon name={it.icon} size={17} />
                  <span>{it.label}</span>{it.meta && <span className="meta">{it.meta}</span>}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function Toasts() {
  const s = useStore();

  const copyToast = (t) => {
    if (typeof navigator === "undefined" || !navigator.clipboard) {
      s.toast("Clipboard not available", { bad: true });
      return;
    }
    navigator.clipboard.writeText(t.copy)
      .then(() => s.toast("Copied"))
      .catch(() => s.toast("Could not copy", { bad: true }));
  };

  const openToastLink = (href) => {
    if (typeof window !== "undefined" && href) {
      window.open(href, "_blank", "noopener,noreferrer");
    }
  };

  const onToastClick = (t, e) => {
    if (!t.href || e.target.closest(".toast-act")) return;
    openToastLink(t.href);
  };

  return (
    <div className="toasts">{s.toasts.map((t) => {
      const iconName = t.icon || (t.bad ? "x" : "check");
      const icColor = t.tone === "amber" ? "var(--amber)" : t.bad ? "var(--danger)" : undefined;
      return (
        <div
          className={"toast" + (t.tone ? " " + t.tone : "") + (t.href ? " toast-link" : "")}
          key={t.id}
          onClick={t.href ? (e) => onToastClick(t, e) : undefined}
        >
          <span className="ic" style={icColor ? { color: icColor } : null}>
            <Icon name={iconName} size={16} /></span>
          <span>{t.msg}</span>
          {t.copy && (
            <button className="toast-act" type="button" title="Copy" aria-label="Copy"
              onClick={(e) => { e.stopPropagation(); copyToast(t); }}>
              <Icon name="copy" size={15} />
            </button>
          )}
          {t.undo && (
            <button className="toast-act" type="button"
              onClick={(e) => { e.stopPropagation(); t.undo(); s.dismiss(t.id); }}>
              Undo
            </button>
          )}
        </div>
      );
    })}</div>
  );
}
