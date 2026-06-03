// window.jsx — the Dictate window rendered with per-OS chrome.
// One faithful interior (condensed Status surface); TitleBar swaps the control
// cluster, alignment, corner & elevation by `platform`. Exports DictateWindow.

const ICN = {
  mic: <><path d="M12 2.5a2.6 2.6 0 0 0-2.6 2.6v6a2.6 2.6 0 0 0 5.2 0v-6A2.6 2.6 0 0 0 12 2.5Z"/><path d="M18 11v.6a6 6 0 0 1-12 0V11"/><path d="M12 17.6V21M8.5 21h7"/></>,
  status: <path d="M3 12h4l2.5 6 5-13 2 7H21"/>,
  sliders: <><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2.2"/><circle cx="8" cy="17" r="2.2"/></>,
  keyboard: <><rect x="3" y="6" width="18" height="12" rx="2.5"/><path d="M7 10h.01M11 10h.01M15 10h.01M17 14H7"/></>,
  hash: <path d="M5 9h14M5 15h14M10 4 8 20M16 4l-2 16"/>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 8v4.5l3 1.7"/></>,
  power: <><path d="M12 4v7"/><path d="M7.4 7.4a7 7 0 1 0 9.2 0"/></>,
  gear: <><circle cx="12" cy="12" r="3"/><path d="M12 3.5v2.2M12 18.3v2.2M5.5 5.5l1.6 1.6M16.9 16.9l1.6 1.6M3.5 12h2.2M18.3 12h2.2M5.5 18.5l1.6-1.6M16.9 7.1l1.6-1.6"/></>,
  chev: <path d="M9 6l6 6-6 6"/>,
  chevd: <path d="M6 9l6 6 6-6"/>,
  device: <><rect x="4" y="4" width="16" height="11" rx="2"/><path d="M8 20h8M12 15v5"/></>,
  moon: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>,
  min: <path d="M5 12h14"/>,
  max: <rect x="5" y="5" width="14" height="14" rx="1.5"/>,
  x: <path d="M6 6l12 12M18 6 6 18"/>,
};
function Ic({ n, size = 18 }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" style={{ display: "block", flex: "0 0 auto" }}>{ICN[n]}</svg>;
}
const ArcMark = () => (
  <svg viewBox="228 231 551 582" fill="none" style={{ width: "100%", height: "100%" }}><g transform="translate(228,231) scale(0.921405,0.937198)" fill="currentColor"><path d="M 302.5 0 L 325 37.5 L 329 42.5 L 342 65.5 L 346 70.5 L 356 88.5 L 360 93.5 L 373 116.5 L 377 121.5 L 390 144.5 L 394 149.5 L 407 172.5 L 411 177.5 L 420 192.5 L 422 198 L 326.5 198 L 325 196.5 L 306.5 172 L 266 239.5 L 264 244.5 L 256 256.5 L 254 261.5 L 243 278.5 L 241 283.5 L 233 295.5 L 231 300.5 L 223 312.5 L 221 317.5 L 213 329.5 L 211 334.5 L 200 351.5 L 198 356.5 L 190 368.5 L 188 373.5 L 180 385.5 L 178 390.5 L 167 407.5 L 165 412.5 L 147 441.5 L 135 463.5 L 124 480.5 L 122 485.5 L 104 514.5 L 102 519.5 L 96.5 527 L 0 526.5 L 9 512.5 L 35 465.5 L 40 458.5 L 66 411.5 L 71 404.5 L 97 357.5 L 102 350.5 L 128 303.5 L 133 296.5 L 159 249.5 L 164 242.5 L 166 237.5 L 168 235.5 L 170 230.5 L 172 228.5 L 174 223.5 L 192 193.5 L 194 188.5 L 199 181.5 L 201 176.5 L 203 174.5 L 205 169.5 L 207 167.5 L 209 162.5 L 230 127.5 L 232 122.5 L 234 120.5 L 236 115.5 L 238 113.5 L 240 108.5 L 242 106.5 L 244 101.5 L 261 73.5 L 263 68.5 L 265 66.5 L 267 61.5 L 269 59.5 L 271 54.5 L 273 52.5 L 275 47.5 L 277 45.5 L 279 40.5 L 281 38.5 L 283 33.5 L 292 19.5 L 302.5 0 Z"></path><path d="M 321.5 247 L 596.5 247 Q 597.3 246.8 597 249.5 L 570 290.5 L 562 304.5 L 554 315.5 L 553 318.5 L 548.5 324 L 295.5 324 L 294.5 325 L 276 325 L 276 322.5 L 321.5 247 Z"></path><path d="M 246.5 375 L 492 375.5 L 436.5 448 L 400.5 448 L 399.5 447 L 375.5 447 L 374 448.5 L 374 522.5 L 373 525.5 L 300 618.5 L 300 620 L 298 619.5 L 298 477.5 Q 300 476.5 298 475.5 L 298 466.5 Q 296.3 465.8 297 462.5 L 290 446.5 L 267 410.5 L 252 384.5 L 248 379.5 L 246 375.5 L 246.5 375 Z"></path></g></svg>
);

function Combo({ keys, lg }) {
  return <span className="combo">{keys.map((k, i) => <React.Fragment key={i}>
    {i > 0 && <span className="plus">+</span>}<span className={"kbd" + (lg ? " lg" : "")}>{k}</span>
  </React.Fragment>)}</span>;
}

/* ----- the title bar: the part that changes per OS ----- */
function TitleBar({ platform }) {
  const Brand = (
    <div className="tb-l">
      <span className="tb-mark"><ArcMark /></span>
      <span className="tb-title">Dictate<span className="sub">Settings</span></span>
    </div>
  );
  const TitleCenter = <div className="tb-c"><span className="tb-title">Dictate<span className="sub">Settings</span></span></div>;

  if (platform === "mac") return (
    <div className="tbar">
      <div className="tb-l"><span className="lights"><i className="c" /><i className="m" /><i className="g" /></span></div>
      {TitleCenter}
    </div>
  );
  if (platform === "win11" || platform === "win10") return (
    <div className="tbar">
      {Brand}
      <div className="tb-r"><div className="wincaps">
        <button title="Minimize"><Ic n="min" /></button>
        <button title="Maximize"><Ic n="max" /></button>
        <button className="x" title="Close"><Ic n="x" /></button>
      </div></div>
    </div>
  );
  if (platform === "gnome") return (
    <div className="tbar">
      <div className="tb-l"><span className="tb-mark"><ArcMark /></span></div>
      {TitleCenter}
      <div className="tb-r"><div className="adw">
        <button title="Close"><Ic n="x" /></button>
      </div></div>
    </div>
  );
  // kde / breeze
  return (
    <div className="tbar">
      <div className="tb-l"><span className="tb-mark"><ArcMark /></span></div>
      {TitleCenter}
      <div className="tb-r"><div className="breeze">
        <button title="Minimize"><Ic n="min" /></button>
        <button title="Maximize"><Ic n="max" /></button>
        <button className="x" title="Close"><Ic n="x" /></button>
      </div></div>
    </div>
  );
}

/* ----- the constant interior: condensed-but-faithful Status surface ----- */
function Interior() {
  const NAV = [
    { v: "status", icon: "status", label: "Status", active: true },
    { sec: "Configure" },
    { v: "model", icon: "sliders", label: "Model" },
    { v: "ptt", icon: "keyboard", label: "Push-to-talk" },
    { v: "hotwords", icon: "hash", label: "Hotwords", badge: 3 },
    { sec: "Activity" },
    { v: "history", icon: "history", label: "Recent history", badge: 1 },
    { sec: "App" },
    { v: "startup", icon: "power", label: "Startup" },
    { v: "advanced", icon: "gear", label: "Advanced" },
  ];
  return (
    <div className="shell">
      <aside className="rail">
        <div className="rail-status">
          <span className="mic"><Ic n="mic" size={18} /></span>
          <span style={{ minWidth: 0 }}>
            <span className="nm">Dictate <span className="dot live" /></span>
            <span className="t-meta" style={{ display: "block" }}>faster-whisper · ready</span>
          </span>
        </div>
        <nav className="nav">
          {NAV.map((n, i) => n.sec
            ? <div className="nav-sec" key={i}>{n.sec}</div>
            : <div key={n.v} className={"nav-item" + (n.active ? " active" : "")}>
                <Ic n={n.icon} size={16} /><span>{n.label}</span>
                {n.badge ? <span className="badge tnum">{n.badge}</span> : null}
              </div>)}
        </nav>
        <div className="rail-foot">
          <span className="iconbtn"><Ic n="moon" size={16} /></span>
          <span className="ver">v2026.6.2</span>
        </div>
      </aside>

      <main className="content">
        <div className="view">
          <div className="crumb">Status</div>
          <div className="hero">
            <div className="orb"><Ic n="mic" size={24} /></div>
            <div className="body">
              <div className="statusline">
                <span className="dot live" />
                <span className="t-label" style={{ color: "var(--live)" }}>Ready</span>
                <span className="t-meta">·&nbsp; microphone connected</span>
              </div>
              <h2>Ready to dictate</h2>
              <div className="sub">Hold your shortcut, speak, and release — text types straight into the app you're using.</div>
            </div>
            <div className="keyhint">
              <span className="t-label">Hold</span>
              <Combo keys={["Right Ctrl"]} lg />
            </div>
          </div>

          <div className="grid2">
            <div className="minic">
              <div className="top"><Ic n="sliders" size={16} /><Ic n="chev" size={13} /></div>
              <div className="k">Model</div>
              <div className="v">faster-whisper<span className="chip live">LOCAL</span></div>
            </div>
            <div className="minic">
              <div className="top"><Ic n="keyboard" size={16} /><Ic n="chev" size={13} /></div>
              <div className="k">Push-to-talk</div>
              <div className="v"><Combo keys={["Right Ctrl"]} /><span className="chip">HOLD</span></div>
            </div>
          </div>

          <div className="card">
            <div className="row">
              <span className="ic"><Ic n="device" size={17} /></span>
              <span className="main"><div className="lbl">Microphone</div><div className="help">Audio input device</div></span>
              <button className="select">Default device<Ic n="chevd" size={13} /></button>
            </div>
            <div className="row">
              <span className="ic"><Ic n="power" size={17} /></span>
              <span className="main"><div className="lbl">Launch on sign-in</div><div className="help">Start Dictate automatically</div></span>
              <span className="toggle on"><span className="knob" /></span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function DictateWindow({ platform }) {
  return (
    <div className={"win " + platform}>
      <TitleBar platform={platform} />
      <Interior />
    </div>
  );
}

Object.assign(window, { DictateWindow, TitleBar });
