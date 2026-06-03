// installer-b.jsx — Direction B · "Console" — hero + footer, app-like.
// Built out as the chosen direction: verified-publisher trust row, a real
// done recap that reflects the chosen options, tweak-driven defaults & speed.
function InstallerB({ theme, onTheme, solo, publisher = "Arc Forge", showPublisher = true, defaults, speedMul = 1, modelPresent = false }) {
  const F = useInstaller({ defaults, speedMul, modelPresent });
  const { step, pct, advanced, setAdvanced, settings, setS, begin, launch, restart } = F;

  const meta = step === "launched" ? "" : step === "done" ? "Setup complete" : advanced ? "Advanced setup" : "Setup";

  let body;
  if (step === "launched") {
    body = <FirstRun />;
  } else if (step === "installing") {
    const phase = pct < 52 ? "Downloading" : "Installing";
    body =
    <div className="istep istep-fade">
        <div className="ihero">
          <Orb state="installing" />
          <div className="body">
            <div className="eyebrow"><span className="dot live" /><span className="t-label" style={{ color: "var(--live)" }}>{phase}</span></div>
            <h2 className="t-title ipct" style={{ fontSize: 36 }}>{Math.round(pct)}<span style={{ fontSize: 20, color: "var(--muted)" }}>%</span></h2>
            <div className="sub t-body">{phase === "Downloading" ? "Downloading models." : "Setting things up — almost there."}</div>
          </div>
        </div>
        <div className="ifoot">
          <div className="ifoot-bar" style={{ width: pct + "%" }} />
          <span className="t-meta">{phase} Dictate</span>
          <span className="spacer" />
          <span className="t-mono" style={{ color: "var(--subtle)" }}>{Math.round(pct)}%</span>
        </div>
      </div>;

  } else if (step === "done") {
    body =
    <div className="istep istep-fade">
        <div className="ihero">
          <Orb state="done" />
          <div className="body">
            <div className="eyebrow"><span className="dot live" /><span className="t-label" style={{ color: "var(--live)" }}>Installed</span></div>
            <h2 className="t-title">Dictate is ready</h2>
            <div className="sub t-body">Quiet in your tray until you summon it.</div>
          </div>
        </div>
        <div className="ifoot">
          <button className="ilink" onClick={launch}><Icon name="sliders" size={15} /> Settings</button>
          <span className="spacer" />
          <button className="btn primary" onClick={launch}><Icon name="mic" size={17} /> Open Dictate</button>
        </div>
      </div>;

  } else if (advanced) {
    body =
    <div className="istep istep-fade">
        <div style={{ flex: 1, minHeight: 0, padding: "20px 24px 4px", display: "flex", flexDirection: "column", gap: 13 }}>
          <div>
            <div className="t-heading">Advanced setup</div>
            <div className="t-meta">Everything below has a sensible default.</div>
          </div>
          <AdvancedPanel settings={settings} setS={setS} />
        </div>
        <div className="ifoot">
          <button className="btn ghost" onClick={() => setAdvanced(false)}><Icon name="back" size={16} /> Back</button>
          <span className="spacer" />
          <button className="btn primary" onClick={begin}><Icon name="download" size={17} /> Install</button>
        </div>
      </div>;

  } else {
    // welcome
    body =
    <div className="istep istep-fade">
        <div className="ihero ihero-welcome">
          <div className="ibrandmark"><ArcMark /></div>
          <div className="body">
            <div className="eyebrow eyebrow-top"><span className="t-label">Setup</span></div>
            <h2 className="t-title">Dictate</h2>
            <div className="sub t-body">Type as fast as you can speak.</div>
          </div>
        </div>
        {showPublisher &&
      <div className="itrust">
            <span className="sh"><Icon name="shield" size={16} /></span>
            <span className="pub">{publisher}</span>
            <span className="mid">·</span>
            <span>Verified publisher</span>
            <span className="spacer" />
            <span className="sz">local-first</span>
          </div>
      }
        <div className="ifoot">
          <button className="btn primary" onClick={begin}><Icon name="download" size={17} /> Install</button>
          <LegalLine />
          <span className="spacer" />
          <button className="ilink" onClick={() => setAdvanced(true)}><Icon name="sliders" size={14} /> Advanced</button>
        </div>
      </div>;

  }

  return (
    <div className={"istage" + (solo ? " solo" : "")} data-theme={theme === "dark" ? "dark" : undefined}>
      <div className="iwin">
        <WinChrome meta={meta} theme={theme} onTheme={onTheme} />
        {body}
      </div>
    </div>);

}

Object.assign(window, { InstallerB });