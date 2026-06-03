// installer-flow.jsx — the install state machine + shared sub-components.
// Exports: useInstaller, AdvancedPanel, LegalLine, FirstRun  → window.
const { useState, useRef, useCallback, useEffect } = React;

function useInstaller(opts = {}) {
  const { defaults = {}, speedMul = 1, modelPresent = false } = opts;
  const launchDefault = defaults.launchOnLogin !== undefined ? defaults.launchOnLogin : true;
  const shortcutDefault = !!defaults.desktopShortcut;
  const [step, setStep] = useState("welcome"); // welcome | installing | done | launched
  const [pct, setPct] = useState(0);
  const [advanced, setAdvanced] = useState(false);
  const [settings, setSettings] = useState({
    location: "%LOCALAPPDATA%\\Dictate\\source",
    desktopShortcut: shortcutDefault,
    launchOnLogin: launchDefault
  });
  const timer = useRef(null);
  const speedRef = useRef(speedMul);speedRef.current = speedMul;
  const modelRef = useRef(modelPresent);modelRef.current = modelPresent;

  const setS = (k, v) => setSettings((s) => ({ ...s, [k]: v }));

  // re-seed the two toggles when their tweak-driven defaults change (pre-install)
  useEffect(() => {
    if (step === "welcome") setSettings((s) => ({ ...s, launchOnLogin: launchDefault, desktopShortcut: shortcutDefault }));
  }, [launchDefault, shortcutDefault]);

  const begin = useCallback(() => {
    // if the on-device model is already cached, skip the download phase entirely
    const cached = modelRef.current;
    const start = cached ? 55 : 0;
    setStep("installing");setPct(start);
    let p = start;
    // calm, slightly organic ramp with two micro-settles — reads as real work
    timer.current = setInterval(() => {
      const ease = p < 70 ? 0.9 : p < 92 ? 0.55 : 0.32; // slows near the end
      const settle = p > 33 && p < 38 || p > 74 && p < 79 ? 0.18 : 1;
      p = Math.min(100, p + (Math.random() * 0.8 + 0.4) * ease * settle * speedRef.current);
      setPct(p);
      if (p >= 100) {
        clearInterval(timer.current);
        setTimeout(() => setStep("done"), 560);
      }
    }, 90);
  }, []);

  useEffect(() => () => clearInterval(timer.current), []);

  const restart = () => {clearInterval(timer.current);setStep("welcome");setPct(0);};
  const launch = () => setStep("launched");

  return { step, pct, advanced, setAdvanced, settings, setS, begin, restart, launch };
}

// the almost-invisible advanced panel (install location + two options)
function AdvancedPanel({ settings, setS }) {
  return (
    <div className="iadv">
      <div className="iadv-row col">
        <div className="iadv-line">
          <span style={{ color: "var(--muted)", display: "flex" }}><Icon name="device" size={17} /></span>
          <div className="m">
            <div className="lbl">Install location</div>
            <div className="hlp">Where Dictate's files live on this PC.</div>
          </div>
        </div>
        <div className="iadv-pathrow">
          <span className="ipath" title={settings.location}>{settings.location}</span>
          <button className="btn sm" type="button">Browse…</button>
        </div>
      </div>
      <div className="iadv-row">
        <span style={{ color: "var(--muted)", display: "flex" }}><Icon name="shortcut" size={17} /></span>
        <div className="m">
          <div className="lbl">Desktop shortcut</div>
          <div className="hlp">Add a Dictate icon to your desktop.</div>
        </div>
        <Toggle on={settings.desktopShortcut} onChange={(v) => setS("desktopShortcut", v)} />
      </div>
      <div className="iadv-row">
        <span style={{ color: "var(--muted)", display: "flex" }}><Icon name="power" size={17} /></span>
        <div className="m">
          <div className="lbl">Launch on sign-in</div>
          <div className="hlp">Start Dictate quietly in the tray when you log in.</div>
        </div>
        <Toggle on={settings.launchOnLogin} onChange={(v) => setS("launchOnLogin", v)} />
      </div>
    </div>);

}

// honest, near-invisible legal line — agreement is assumed, license linked
function LegalLine() {
  return (
    <div className="ilegal">
      By installing you agree to the <a href="https://github.com/dictate-app/dictate/blob/main/LICENSE"
      target="_blank" rel="noopener">terms and license</a>.
    </div>);

}

// first-run welcome shown after "Open Dictate"
function FirstRun({ centered }) {
  const [tour, setTour] = useState(0);
  const TOUR = [
    { icon: "keyboard", title: "Hold to talk", body: "Hold Right Ctrl, speak, then release." },
    { icon: "mic", title: "It types for you", body: "Your words land at the cursor — in any app." },
    { icon: "sliders", title: "Make it yours", body: "Change the model or shortcut anytime in Settings." }];

  const body =
  <>
      <div className="ihint">
        <span style={{ color: "var(--live)", display: "flex" }}><Icon name="keyboard" size={19} /></span>
        <div style={{ flex: 1, textAlign: "left" }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Hold to talk</div>
          <div className="t-meta" style={{ marginTop: 1 }}>Hold, speak, release — text appears at your cursor.</div>
        </div>
        <span className="k"><Combo keys={["Right Ctrl"]} /></span>
      </div>
    </>;


  if (centered) {
    return (
      <div className="istep istep-fade">
        <div className="icenter">
          <div className="iorb live" style={{ width: 78, height: 78 }}><Icon name="mic" size={30} /></div>
          <div className="t-label" style={{ marginTop: 22, color: "var(--live)" }}>Listening agent ready</div>
          <h2 className="t-title" style={{ marginTop: 7 }}>Ready to dictate</h2>
          <div className="t-body muted" style={{ marginTop: 8, maxWidth: 280 }}>
            Dictate is live in your tray. Press your shortcut in any app and start talking.
          </div>
          <div style={{ width: "100%", marginTop: 22 }}>{body}</div>
        </div>
      </div>);

  }
  // hero variant (direction B)
  if (tour > 0) {
    const s = TOUR[tour - 1];
    return (
      <div className="istep istep-fade">
        <div className="ihero">
          <div className="iorb live" style={{ width: 70, height: 70, flex: "0 0 auto" }}><Icon name={s.icon} size={28} /></div>
          <div className="body">
            <div className="eyebrow"><span className="t-label" style={{ color: "var(--live)" }}>Step {tour} of {TOUR.length}</span></div>
            <h2 className="t-title">{s.title}</h2>
            <div className="sub t-body">{s.body}</div>
          </div>
        </div>
        <div className="ifoot">
          <div className="tour-dots">{TOUR.map((_, i) => <span key={i} className={"tour-dot" + (i + 1 === tour ? " on" : "")} />)}</div>
          <span className="spacer" />
          {tour > 1 && <button className="ilink" onClick={() => setTour(tour - 1)}>Back</button>}
          {tour < TOUR.length ?
          <button className="btn primary" onClick={() => setTour(tour + 1)}>Next</button> :
          <button className="btn primary" onClick={() => setTour(0)}><Icon name="check" size={16} /> Done</button>}
        </div>
      </div>);

  }
  return (
    <div className="istep istep-fade">
      <div className="ihero">
        <div className="iorb live" style={{ width: 70, height: 70, flex: "0 0 auto" }}><Icon name="mic" size={28} /></div>
        <div className="body">
          <div className="eyebrow"><span className="dot live" /><span className="t-label" style={{ color: "var(--live)" }}>In your tray</span></div>
          <h2 className="t-title">Ready to dictate</h2>
          <div className="sub t-body">Talk anywhere you can type.</div>
        </div>
      </div>
      <div className="ifoot">
        <span className="t-meta" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          Hold <Combo keys={["Right Ctrl"]} /> to talk
        </span>
        <span className="spacer" />
        <button className="ilink" onClick={() => setTour(1)}>Take a quick tour</button>
      </div>
    </div>);

}

Object.assign(window, { useInstaller, AdvancedPanel, LegalLine, FirstRun });
