// installer-shared.jsx — atoms shared by both installer directions.
// Exports: Icon, ArcMark, WinChrome, Orb, ProgressRing, Toggle, Combo  → window.
const { useState, useEffect, useRef } = React;

const IICONS = {
  mic: <><path d="M12 2.5a2.6 2.6 0 0 0-2.6 2.6v6a2.6 2.6 0 0 0 5.2 0v-6A2.6 2.6 0 0 0 12 2.5Z" /><path d="M18 11v.6a6 6 0 0 1-12 0V11" /><path d="M12 17.6V21M8.5 21h7" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  minus: <path d="M5 12h14" />,
  square: <rect x="5" y="5" width="14" height="14" rx="1.5" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M18.4 5.6l1.4-1.4M4.2 19.8l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />,
  sliders: <><path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2.2" /><circle cx="8" cy="17" r="2.2" /></>,
  device: <><rect x="4" y="4" width="16" height="11" rx="2" /><path d="M8 20h8M12 15v5" /></>,
  power: <><path d="M12 4v7" /><path d="M7.4 7.4a7 7 0 1 0 9.2 0" /></>,
  pin: <><path d="M12 21s7-5.5 7-11a7 7 0 0 0-14 0c0 5.5 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" /></>,
  shortcut: <><path d="M14 4h6v6" /><path d="M20 4 11 13" /><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" /></>,
  keyboard: <><rect x="3" y="6" width="18" height="12" rx="2.5" /><path d="M7 10h.01M11 10h.01M15 10h.01M17 14H7" /></>,
  shield: <><path d="M12 3 5 6v5c0 4.5 3 7.7 7 9 4-1.3 7-4.5 7-9V6l-7-3z" /><path d="M9.5 12l1.8 1.8 3.5-3.6" /></>,
  download: <><path d="M12 3v12M7 11l5 4 5-4" /><path d="M5 20h14" /></>,
  back: <path d="M15 6l-6 6 6 6" />,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M12 3.5v2.2M12 18.3v2.2M5.5 5.5l1.6 1.6M16.9 16.9l1.6 1.6M3.5 12h2.2M18.3 12h2.2M5.5 18.5l1.6-1.6M16.9 7.1l1.6-1.6" /></>,
  chev: <path d="M9 6l6 6-6 6" />
};

function Icon({ name, size = 18, style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
    style={{ flex: "0 0 auto", display: "block", ...style }}>{IICONS[name]}</svg>);

}

const ArcMark = () =>
<svg viewBox="228 231 551 582" fill="none" style={{ width: "100%", height: "100%" }}>
    <g transform="translate(228,231) scale(0.921405,0.937198)" fill="currentColor">
      <path d="M 302.5 0 L 325 37.5 L 329 42.5 L 342 65.5 L 346 70.5 L 356 88.5 L 360 93.5 L 373 116.5 L 377 121.5 L 390 144.5 L 394 149.5 L 407 172.5 L 411 177.5 L 420 192.5 L 422 198 L 326.5 198 L 325 196.5 L 306.5 172 L 266 239.5 L 264 244.5 L 256 256.5 L 254 261.5 L 243 278.5 L 241 283.5 L 233 295.5 L 231 300.5 L 223 312.5 L 221 317.5 L 213 329.5 L 211 334.5 L 200 351.5 L 198 356.5 L 190 368.5 L 188 373.5 L 180 385.5 L 178 390.5 L 167 407.5 L 165 412.5 L 147 441.5 L 135 463.5 L 124 480.5 L 122 485.5 L 104 514.5 L 102 519.5 L 96.5 527 L 0 526.5 L 9 512.5 L 35 465.5 L 40 458.5 L 66 411.5 L 71 404.5 L 97 357.5 L 102 350.5 L 128 303.5 L 133 296.5 L 159 249.5 L 164 242.5 L 166 237.5 L 168 235.5 L 170 230.5 L 172 228.5 L 174 223.5 L 192 193.5 L 194 188.5 L 199 181.5 L 201 176.5 L 203 174.5 L 205 169.5 L 207 167.5 L 209 162.5 L 230 127.5 L 232 122.5 L 234 120.5 L 236 115.5 L 238 113.5 L 240 108.5 L 242 106.5 L 244 101.5 L 261 73.5 L 263 68.5 L 265 66.5 L 267 61.5 L 269 59.5 L 271 54.5 L 273 52.5 L 275 47.5 L 277 45.5 L 279 40.5 L 281 38.5 L 283 33.5 L 292 19.5 L 302.5 0 Z"></path>
      <path d="M 321.5 247 L 596.5 247 Q 597.3 246.8 597 249.5 L 570 290.5 L 562 304.5 L 554 315.5 L 553 318.5 L 548.5 324 L 295.5 324 L 294.5 325 L 276 325 L 276 322.5 L 321.5 247 Z"></path>
      <path d="M 246.5 375 L 492 375.5 L 436.5 448 L 400.5 448 L 399.5 447 L 375.5 447 L 374 448.5 L 374 522.5 L 373 525.5 L 300 618.5 L 300 620 L 298 619.5 L 298 477.5 Q 300 476.5 298 475.5 L 298 466.5 Q 296.3 465.8 297 462.5 L 290 446.5 L 267 410.5 L 252 384.5 L 248 379.5 L 246 375.5 L 246.5 375 Z"></path>
    </g>
  </svg>;


// Title bar with arc mark, meta label, theme toggle + window controls.
function WinChrome({ meta = "Setup", theme, onTheme, onClose }) {
  return (
    <div className="itb">
      <div className="itb-left">
        <span className="itb-mark"><ArcMark /></span>
        Dictate<span className="itb-meta">by Arc Forge</span>
      </div>
      <div className="itb-ctrls">
        <button className="itb-btn"><Icon name="minus" size={14} /></button>
        <button className="itb-btn"><Icon name="square" size={12} /></button>
        <button className="itb-btn close" onClick={onClose}><Icon name="x" size={14} /></button>
      </div>
    </div>);

}

// Orb — the one living element. It simply breathes while installing
// (Dictate's signature pulse); the percentage + footer bar carry progress.
function Orb({ state }) {
  // state: "idle" | "installing" | "done"
  const live = state === "installing";
  return (
    <div className={"iorb" + (live ? " live" : "") + (state === "done" ? " done" : "")}>
      <Icon name={state === "done" ? "check" : "mic"} size={34} />
    </div>);

}

function Toggle({ on, onChange }) {
  return (
    <button role="switch" aria-checked={!!on} className={"toggle" + (on ? " on" : "")}
    onClick={() => onChange && onChange(!on)}><span className="knob" /></button>);

}

function Combo({ keys }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center" }}>
      {keys.map((k, i) =>
      <React.Fragment key={i}>{i > 0 && <span className="plus">+</span>}<span className="kbd">{k}</span></React.Fragment>
      )}
    </span>);

}

Object.assign(window, { Icon, ArcMark, WinChrome, Orb, Toggle, Combo });