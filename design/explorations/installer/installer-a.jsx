// installer-a.jsx — Direction A · "Centered" — symmetric, ceremonial, all air.
const { useState: useStateA } = React;

function InstallerA({ theme, onTheme }) {
  const F = useInstaller();
  const { step, pct, advanced, setAdvanced, settings, setS, begin, launch } = F;

  const meta = step === "launched" ? "" : step === "done" ? "Setup complete" : advanced ? "Advanced setup" : "Setup";

  let body;
  if (step === "launched") {
    body = <FirstRun centered />;
  } else if (step === "installing") {
    body = (
      <div className="istep istep-fade">
        <div className="icenter">
          <Orb state="installing" pct={pct} />
          <div className="ipct" style={{ fontSize: 30, marginTop: 24 }}>{Math.round(pct)}<span style={{ fontSize: 17, color: "var(--muted)" }}>%</span></div>
          <div style={{ width: 220, marginTop: 18 }}><div className="ibar"><i style={{ width: pct + "%" }} /></div></div>
          <div className="t-meta" style={{ marginTop: 16, color: "var(--subtle)" }}>Installing Dictate</div>
        </div>
      </div>
    );
  } else if (step === "done") {
    body = (
      <div className="istep istep-fade">
        <div className="icenter">
          <Orb state="done" />
          <div className="t-label" style={{ marginTop: 22, color: "var(--live)" }}>Installed</div>
          <h2 className="t-title" style={{ marginTop: 7 }}>Dictate is ready</h2>
          <div className="t-body muted" style={{ marginTop: 8, maxWidth: 270 }}>
            It lives in your tray now — quiet until you summon it.
          </div>
          <button className="btn primary" style={{ marginTop: 24, minWidth: 188 }} onClick={launch}>
            <Icon name="mic" size={17} /> Open Dictate
          </button>
          <div className="t-meta" style={{ marginTop: 13, color: "var(--subtle)" }}>
            Launch on sign-in is on · change in Settings
          </div>
        </div>
      </div>
    );
  } else if (advanced) {
    // quiet advanced setup view
    body = (
      <div className="istep istep-fade" style={{ padding: "22px 26px 18px", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button className="btn ghost" style={{ width: 32, height: 32, padding: 0, borderRadius: 8 }}
            onClick={() => setAdvanced(false)}><Icon name="back" size={17} /></button>
          <div>
            <div className="t-heading">Advanced setup</div>
            <div className="t-meta">Everything below has a sensible default.</div>
          </div>
        </div>
        <AdvancedPanel settings={settings} setS={setS} />
        <div style={{ flex: 1 }} />
        <button className="btn primary block" onClick={begin}><Icon name="download" size={17} /> Install Dictate</button>
        <div style={{ display: "flex", justifyContent: "center" }}><LegalLine /></div>
      </div>
    );
  } else {
    // welcome
    body = (
      <div className="istep istep-fade">
        <div className="icenter">
          <div className="iglyph"><ArcMark /></div>
          <h2 className="t-title" style={{ marginTop: 16 }}>Install Dictate</h2>
          <div className="t-body muted" style={{ marginTop: 6, maxWidth: 320 }}>
            Type with your voice in any app on this PC.
          </div>
          <div className="t-mono" style={{ marginTop: 11, color: "var(--subtle)" }}>v2026.2.25 · 48 MB · local-first</div>
          <button className="btn primary" style={{ marginTop: 20, minWidth: 200 }} onClick={begin}>
            <Icon name="download" size={17} /> Install
          </button>
          <button className="ilink" style={{ marginTop: 10 }} onClick={() => setAdvanced(true)}>
            <Icon name="sliders" size={14} /> Advanced
          </button>
        </div>
        <div style={{ flex: "0 0 auto", padding: "13px 30px", borderTop: "1px solid var(--hairline)", display: "flex", justifyContent: "center" }}>
          <LegalLine />
        </div>
      </div>
    );
  }

  return (
    <div className="istage" data-theme={theme === "dark" ? "dark" : undefined}>
      <div className="iwin">
        <WinChrome meta={meta} theme={theme} onTheme={onTheme} />
        {body}
      </div>
    </div>
  );
}

Object.assign(window, { InstallerA });
