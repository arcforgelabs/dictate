// primitives.jsx — small controlled UI atoms shared across views.
import React, { useEffect, useRef, useState } from "react";
import { Icon } from "./icons.jsx";

export function Kbd({ children, lg }) {
  return <span className={"kbd" + (lg ? " lg" : "")}>{children}</span>;
}

export function Combo({ keys, lg }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center" }}>
      {keys.map((k, i) => (
        <React.Fragment key={i}>{i > 0 && <span className="plus">+</span>}<Kbd lg={lg}>{k}</Kbd></React.Fragment>
      ))}
    </span>
  );
}

export function Chip({ children, live, danger }) {
  return <span className={"chip" + (live ? " live" : "") + (danger ? " danger" : "")}>{children}</span>;
}

export function Dot({ live, amber }) {
  return <span className={"dot" + (live ? " live" : "") + (amber ? " amber" : "")} />;
}

export function Toggle({ on, onChange }) {
  return (
    <button role="switch" aria-checked={!!on} className={"toggle" + (on ? " on" : "")}
      onClick={() => onChange && onChange(!on)}><span className="knob" /></button>
  );
}

export function Tooltip({ label, children }) {
  const [active, setActive] = useState(false);

  useEffect(() => {
    setActive(false);
  }, [label]);

  const onBlur = (e) => {
    if (!e.currentTarget.contains(e.relatedTarget)) setActive(false);
  };

  return (
    <span
      className={"tip-wrap" + (active ? " show" : "")}
      onMouseEnter={() => setActive(true)}
      onMouseLeave={() => setActive(false)}
      onFocus={() => setActive(true)}
      onBlur={onBlur}
      onPointerDown={() => setActive(false)}
    >
      {children}
      <span className="tip" role="tooltip">{label}</span>
    </span>
  );
}

export function Seg({ options, value, onChange }) {
  return (
    <div className="seg">{options.map((o) => {
      const v = typeof o === "string" ? o : o.v;
      const l = typeof o === "string" ? o : o.l;
      return <button key={v} className={value === v ? "on" : ""} onClick={() => onChange(v)}>{l}</button>;
    })}</div>
  );
}

export function Row({ icon, label, help, children }) {
  return (
    <div className="row">
      {icon && <span className="ic"><Icon name={icon} size={18} /></span>}
      <div className="main"><div className="lbl">{label}</div>{help && <div className="help">{help}</div>}</div>
      {children && <div className="ctrl">{children}</div>}
    </div>
  );
}

// live waveform — drives bar heights via rAF while `active`
export function Wave({ active, bars = 18, color = "#4fbd86", h = 24 }) {
  const refs = useRef([]);
  useEffect(() => {
    if (!active) { refs.current.forEach((el) => el && (el.style.height = "3px")); return; }
    let raf, t = 0;
    const tick = () => {
      t += 0.18;
      refs.current.forEach((el, i) => {
        if (!el) return;
        const v = Math.abs(Math.sin(t + i * 0.55) * 0.6 + Math.sin(t * 1.7 + i) * 0.4);
        el.style.height = (4 + v * (h - 5)) + "px";
      });
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [active]);
  return (
    <div className="wave" style={{ height: h }}>
      {Array.from({ length: bars }, (_, i) => (
        <i key={i} ref={(el) => (refs.current[i] = el)} style={{ background: color, height: 3 }} />
      ))}
    </div>
  );
}
