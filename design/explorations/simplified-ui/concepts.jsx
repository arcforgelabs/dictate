// concepts.jsx — three simplified Dictate Settings concepts, rendered as
// desktop utility windows. Each concept exposes light / dark / recording
// states. Pure markup over the Dictate token system (see <style> in host).
// Exports ConceptA, ConceptB, ConceptC to window for the canvas host.

const { useState: cState } = React;

/* ---- brand mark (currentColor, inherits --fg) ---- */
function Mark() {
  return (
    <svg viewBox="228 231 551 582" fill="none" aria-hidden="true" style={{ width: "100%", height: "100%" }}>
      <g transform="translate(228,231) scale(0.921405,0.937198)" fill="currentColor">
        <path d="M 302.5 0 L 325 37.5 L 329 42.5 L 342 65.5 L 346 70.5 L 356 88.5 L 360 93.5 L 373 116.5 L 377 121.5 L 390 144.5 L 394 149.5 L 407 172.5 L 411 177.5 L 420 192.5 L 422 198 L 326.5 198 L 325 196.5 L 306.5 172 L 266 239.5 L 264 244.5 L 256 256.5 L 254 261.5 L 243 278.5 L 241 283.5 L 233 295.5 L 231 300.5 L 223 312.5 L 221 317.5 L 213 329.5 L 211 334.5 L 200 351.5 L 198 356.5 L 190 368.5 L 188 373.5 L 180 385.5 L 178 390.5 L 167 407.5 L 165 412.5 L 147 441.5 L 135 463.5 L 124 480.5 L 122 485.5 L 104 514.5 L 102 519.5 L 96.5 527 L 0 526.5 L 9 512.5 L 35 465.5 L 40 458.5 L 66 411.5 L 71 404.5 L 97 357.5 L 102 350.5 L 128 303.5 L 133 296.5 L 159 249.5 L 164 242.5 L 166 237.5 L 168 235.5 L 170 230.5 L 172 228.5 L 174 223.5 L 192 193.5 L 194 188.5 L 199 181.5 L 201 176.5 L 203 174.5 L 205 169.5 L 207 167.5 L 209 162.5 L 230 127.5 L 232 122.5 L 234 120.5 L 236 115.5 L 238 113.5 L 240 108.5 L 242 106.5 L 244 101.5 L 261 73.5 L 263 68.5 L 265 66.5 L 267 61.5 L 269 59.5 L 271 54.5 L 273 52.5 L 275 47.5 L 277 45.5 L 279 40.5 L 281 38.5 L 283 33.5 L 292 19.5 L 302.5 0 Z" />
        <path d="M 321.5 247 L 596.5 247 Q 597.3 246.8 597 249.5 L 570 290.5 L 562 304.5 L 554 315.5 L 553 318.5 L 548.5 324 L 295.5 324 L 294.5 325 L 276 325 L 276 322.5 L 321.5 247 Z" />
        <path d="M 246.5 375 L 492 375.5 L 436.5 448 L 400.5 448 L 399.5 447 L 375.5 447 L 374 448.5 L 374 522.5 L 373 525.5 L 300 618.5 L 300 620 L 298 619.5 L 298 477.5 Q 300 476.5 298 475.5 L 298 466.5 Q 296.3 465.8 297 462.5 L 290 446.5 L 267 410.5 L 252 384.5 L 248 379.5 L 246 375.5 L 246.5 375 Z" />
      </g>
    </svg>
  );
}

/* ---- minimal inline icon set (Lucide-style, 1.75 stroke) ---- */
const P = {
  mic: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" /></>,
  rec: <circle cx="12" cy="12" r="5.5" fill="currentColor" stroke="none" />,
  ring: <circle cx="12" cy="12" r="8.2" />,
  gear: <><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v3M12 18.5v3M21.5 12h-3M5.5 12h-3M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1M18.7 18.7l-2.1-2.1M7.4 7.4 5.3 5.3" /></>,
  cmd: <path d="M9 6.5A2.5 2.5 0 1 0 6.5 9H9V6.5ZM15 6.5A2.5 2.5 0 1 1 17.5 9H15V6.5ZM9 17.5A2.5 2.5 0 1 1 6.5 15H9v2.5ZM15 17.5a2.5 2.5 0 1 0 2.5-2.5H15v2.5ZM9 9h6v6H9z" />,
  chev: <path d="M9 6l6 6-6 6" />,
  stop: <rect x="7.5" y="7.5" width="9" height="9" rx="2" fill="currentColor" stroke="none" />,
  sliders: <><path d="M4 8h10M18 8h2M4 16h2M10 16h10" /><circle cx="16" cy="8" r="2" /><circle cx="8" cy="16" r="2" /></>,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 8v4.2l2.8 1.8" /></>,
  history: <><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1M3.5 4.5V9H8" /><path d="M12 8v4.3l3 1.7" /></>,
  hash: <path d="M5 9h14M5 15h14M10 4 8 20M16 4l-2 16" />,
};
function I({ n, s = 18 }) {
  return <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{P[n]}</svg>;
}

/* ---- shared bits ---- */
function Keys({ combo }) {
  const parts = combo.split("+");
  return (
    <span className="keys">
      {parts.map((k, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="plus">+</span>}
          <kbd className="kbd">{k}</kbd>
        </React.Fragment>
      ))}
    </span>
  );
}
function Wave({ n = 22, live }) {
  // deterministic pseudo-random heights so SSR/screenshot is stable
  const hs = Array.from({ length: n }, (_, i) => 5 + Math.round(13 * Math.abs(Math.sin(i * 1.7 + 0.6)) * (0.45 + 0.55 * Math.abs(Math.sin(i * 0.5)))));
  return (
    <div className={"wave" + (live ? " live" : "")} aria-hidden="true">
      {hs.map((h, i) => <i key={i} style={{ height: h + "px" }} />)}
    </div>
  );
}
function Chrome({ theme, right }) {
  return (
    <div className="dwin-tb">
      <div className="dwin-brand"><span className="mark"><Mark /></span><span>Dictate</span></div>
      <div className="tb-right">{right}</div>
    </div>
  );
}
function Gear() { return <button className="ibtn" title="Settings"><I n="gear" s={17} /></button>; }
function CmdHint() { return <span className="cmdhint"><I n="cmd" s={13} />K</span>; }

/* ======================================================================
   A · MINIMAL HOME — capture-first, settings collapsed behind the gear
   ====================================================================== */
function ConceptA({ theme, rec }) {
  return (
    <div className="themewrap" data-theme={theme}>
      <div className="dwin">
        <Chrome theme={theme} right={<><CmdHint /><Gear /></>} />
        {rec ? (
          <div className="a-listen">
            <div className="orb breath"><I n="mic" s={26} /></div>
            <Wave n={28} live />
            <div className="l-title">Listening…</div>
            <div className="l-sub t-mono">0:07 · release <Keys combo="⌃+⌥+D" /> to insert</div>
          </div>
        ) : (
          <div className="a-home">
            <div className="a-status"><span className="dot live" /><span className="t-mono">Ready · faster-whisper · MacBook Microphone</span></div>
            <div className="a-tiles">
              <button className="a-tile primary">
                <span className="t-ico"><I n="mic" s={22} /></span>
                <span className="t-name">Quick dictation</span>
                <span className="t-sub">Hold, speak, release — types where you’re focused.</span>
                <span className="t-foot"><Keys combo="⌃+⌥+D" /></span>
              </button>
              <button className="a-tile">
                <span className="t-ico"><I n="rec" s={20} /></span>
                <span className="t-name">Record conversation</span>
                <span className="t-sub">Long recording, saved to history as a transcript.</span>
                <span className="t-foot"><span className="xai">xAI speaker labels</span></span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ======================================================================
   B · MODE SWITCHER — Quick and Record are mutually exclusive modes;
   only the active mode's context controls appear.
   ====================================================================== */
function ConceptB({ theme, mode = "quick", rec }) {
  const m = rec ? "record" : mode;
  return (
    <div className="themewrap" data-theme={theme}>
      <div className="dwin">
        <Chrome theme={theme} right={<Gear />} />
        <div className="b-seg" role="tablist">
          <button className={"seg-btn" + (m === "quick" ? " on" : "")}>Quick dictation</button>
          <button className={"seg-btn" + (m === "record" ? " on" : "")}>Record conversation</button>
        </div>
        {m === "quick" && (
          <div className="b-stage">
            <button className="hold-target"><I n="mic" s={30} /></button>
            <div className="b-line">Types into the focused app.</div>
            <div className="b-ctl t-mono">Hold <Keys combo="⌃+⌥+D" /></div>
          </div>
        )}
        {m === "record" && !rec && (
          <div className="b-stage">
            <button className="rec-target"><I n="rec" s={26} /></button>
            <div className="b-line">Saved to history as a transcript.</div>
            <div className="b-row">
              <div className="b-row-l"><span className="t-name2">Speaker labels</span><span className="t-sub2">Names each voice in the transcript</span></div>
              <span className="xai">xAI</span>
              <span className="toggle on"><span className="knob" /></span>
            </div>
          </div>
        )}
        {rec && (
          <div className="b-stage rec">
            <button className="rec-target live"><I n="stop" s={22} /></button>
            <Wave n={26} live />
            <div className="b-rec-meta"><span className="reckdot" /><span className="t-mono">Recording · 1:24</span><span className="xai">xAI speaker labels</span></div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ======================================================================
   C · COMPACT CONSOLE — power-user; no left rail, top icon tabs,
   dense but calm. Settings inline as quiet rows.
   ====================================================================== */
function ConceptC({ theme, rec }) {
  const tabs = [["status", "mic"], ["model", "sliders"], ["mic", "mic"], ["hotkeys", "hash"], ["history", "history"]];
  return (
    <div className="themewrap" data-theme={theme}>
      <div className="dwin compact">
        <div className="dwin-tb">
          <div className="dwin-brand"><span className="mark"><Mark /></span></div>
          <div className="c-tabs">
            <button className="c-tab on"><I n="mic" s={16} /></button>
            <button className="c-tab"><I n="sliders" s={16} /></button>
            <button className="c-tab"><I n="hash" s={16} /></button>
            <button className="c-tab"><I n="history" s={16} /></button>
          </div>
          <div className="tb-right"><Gear /></div>
        </div>
        <div className="c-body">
          {rec ? (
            <div className="c-listenbar">
              <span className="reckdot" />
              <span className="t-mono">Listening · 0:07</span>
              <Wave n={20} live />
              <span className="c-release t-mono">release <Keys combo="⌃+⌥+D" /></span>
            </div>
          ) : (
            <div className="c-capture">
              <button className="c-btn primary"><I n="mic" s={17} />Quick<Keys combo="⌃+⌥+D" /></button>
              <button className="c-btn"><I n="rec" s={15} />Record<span className="xai sm">xAI</span></button>
            </div>
          )}
          <div className="c-meta t-mono">faster-whisper · turbo · MacBook Microphone</div>
          <div className={"c-rows" + (rec ? " dim" : "")}>
            <button className="c-row"><span className="c-k t-label">Model</span><span className="c-v">faster-whisper</span><I n="chev" s={15} /></button>
            <button className="c-row"><span className="c-k t-label">Microphone</span><span className="c-v">MacBook Microphone</span><I n="chev" s={15} /></button>
            <button className="c-row"><span className="c-k t-label">Shortcut</span><span className="c-v"><Keys combo="⌃+⌥+D" /></span><I n="chev" s={15} /></button>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ConceptA, ConceptB, ConceptC });
