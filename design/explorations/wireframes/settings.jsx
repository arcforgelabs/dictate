// settings.jsx — three directions for the Dictate desktop settings window.
// A · Sidebar console   B · Single calm scroll   C · Springboard cards

/* ============================ A · SIDEBAR CONSOLE ============================ */
function DirA() {
  const nav = [
    ["status", "Status", true], ["sliders", "Model", false],
    ["keyboard", "Push-to-talk", false], ["hash", "Hotwords", false],
    ["clock", "Recent history", false], ["power", "Startup", false],
    ["gear", "Advanced", false],
  ];
  return (
    <div className="frame">
    <Win title="Dictate" sub="Settings" width={920} height={660}>
      <div className="layA">
        <aside className="rail">
          <nav className="nav">
            {nav.map(([ic, label, active]) => (
              <div key={label} className={"nav-item" + (active ? " active" : "")}>
                <Icon name={ic} size={18} /><span>{label}</span>
              </div>
            ))}
          </nav>
          <div className="rail-foot">
            <div className="row" style={{ padding: "10px 0", border: "none" }}>
              <div className="row-main"><div className="row-label" style={{ fontSize: 13 }}>Appearance</div></div>
              <div className="seg"><span className="seg-i on">Light</span><span className="seg-i">Dark</span></div>
            </div>
            <div className="t-mono" style={{ color: "var(--subtle)" }}>v2026.2.25</div>
          </div>
        </aside>

        <section className="pane">
          <div className="pane-head">
            <div>
              <Eyebrow>Status</Eyebrow>
              <h2 style={{ marginTop: 6 }}>Ready to dictate</h2>
            </div>
            <Btn ghost sm icon="status">Run doctor</Btn>
          </div>

          <div className="hero-card">
            <div className="hero-mic"><Icon name="mic" size={26} /></div>
            <div style={{ flex: 1 }}>
              <div className="hero-line"><Dot live /><span className="t-label" style={{ color: "var(--live)" }}>Ready</span>
                <span className="t-meta">·&nbsp; microphone connected</span></div>
              <div className="hero-sub">Hold your shortcut, speak, release. Text types into the focused app.</div>
            </div>
            <div className="hero-kbd"><span className="t-meta" style={{ marginBottom: 6 }}>Hold</span>
              <div><Kbd>Ctrl</Kbd><span className="plus">+</span><Kbd>R</Kbd></div>
            </div>
          </div>

          <div className="two-up">
            <div className="card mini">
              <div className="mini-top"><Icon name="sliders" size={18} /><Btn ghost sm>Change</Btn></div>
              <div className="mini-label">Model</div>
              <div className="mini-val">faster-whisper · turbo</div>
              <Chip>LOCAL</Chip>
            </div>
            <div className="card mini">
              <div className="mini-top"><Icon name="keyboard" size={18} /><Btn ghost sm>Change</Btn></div>
              <div className="mini-label">Push-to-talk</div>
              <div className="mini-val"><Kbd>Ctrl</Kbd><span className="plus">+</span><Kbd>R</Kbd></div>
              <Chip>HOLD</Chip>
            </div>
          </div>

          <div className="card list">
            <Row icon="device" label="Microphone" help="Audio input device"
              control={<span className="select">Default device <Icon name="chev" size={14} style={{ transform: "rotate(90deg)" }} /></span>} />
            <Row icon="status" label="Transcription" help="Where audio is processed"
              control={<div className="seg"><span className="seg-i on">Local</span><span className="seg-i">API</span></div>} />
            <Row icon="power" label="Launch on sign-in" help="Start Dictate automatically"
              control={<Toggle on />} last />
          </div>
        </section>
      </div>
    </Win>
    <Note k="A">Sidebar console — persistent left nav, every area one click away. Power-user IA.</Note>
    </div>
  );
}

/* ========================== B · SINGLE CALM SCROLL ========================== */
function DirB() {
  const models = [
    ["faster-whisper · turbo", "Runs on this machine — no key needed", "LOCAL", true],
    ["gpt-4o-mini-transcribe", "OpenAI · hosted", "NEEDS KEY", false],
    ["grok-speech-to-text", "xAI · hosted", "NEEDS KEY", false],
    ["gemini-3-flash-preview", "Google · hosted", "NEEDS KEY", false],
  ];
  return (
    <div className="frame">
    <Win title="Dictate" width={620} height={660}>
      <div className="layB">
        <div className="b-status">
          <div className="hero-mic sm"><Icon name="mic" size={22} /></div>
          <div style={{ flex: 1 }}>
            <div className="hero-line"><Dot live /><strong>Ready to dictate</strong></div>
            <div className="t-meta">faster-whisper · turbo &nbsp;·&nbsp; hold <Kbd>Ctrl</Kbd><span className="plus">+</span><Kbd>R</Kbd></div>
          </div>
          <span className="icon-btn"><Icon name="gear" size={18} /></span>
        </div>

        <div className="b-scroll">
          <section className="b-sec">
            <Eyebrow>Model</Eyebrow>
            <div className="opt-list">
              {models.map(([t, d, tag, sel]) => (
                <div key={t} className={"opt" + (sel ? " sel" : "")}>
                  <span className={"radio" + (sel ? " on" : "")} />
                  <div style={{ flex: 1 }}>
                    <div className="opt-t">{t}</div><div className="opt-d">{d}</div>
                  </div>
                  <Chip live={sel} tone={sel ? "" : "warn"}>{tag}</Chip>
                </div>
              ))}
            </div>
          </section>

          <section className="b-sec">
            <Eyebrow>Push-to-talk</Eyebrow>
            <div className="row" style={{ borderTop: "none" }}>
              <div className="row-main"><div className="row-label">Shortcut</div>
                <div className="row-help">Hold to record, release to insert</div></div>
              <div className="row-ctrl" style={{ gap: 8, display: "flex", alignItems: "center" }}>
                <Kbd>Ctrl</Kbd><span className="plus">+</span><Kbd>R</Kbd><Btn ghost sm>Rebind</Btn></div>
            </div>
            <Row label="Activation" help="Hold the key, or tap to toggle"
              control={<div className="seg"><span className="seg-i on">Hold</span><span className="seg-i">Toggle</span></div>} last />
          </section>

          <section className="b-sec">
            <Eyebrow count={3}>Hotwords</Eyebrow>
            <div className="chips-wrap">
              {["AcmeWidget", "OpenClaw", "Stalwart"].map(w => (
                <span key={w} className="word-chip">{w}<Icon name="x" size={12} /></span>
              ))}
              <span className="word-chip add"><Icon name="plus" size={12} />Add word</span>
            </div>
            <div className="row-help" style={{ marginTop: 10 }}>Spell-corrected terms the model should always get right.</div>
          </section>

          <section className="b-sec">
            <Eyebrow>Startup</Eyebrow>
            <Row label="Launch on sign-in" help="Start Dictate automatically" control={<Toggle on />} last />
          </section>
        </div>
      </div>
    </Win>
    <Note k="B">Single calm scroll — status pinned on top, one column of sections. Linear & reassuring.</Note>
    </div>
  );
}

/* =========================== C · SPRINGBOARD CARDS =========================== */
function DirC() {
  const cards = [
    ["sliders", "Model", "faster-whisper · turbo", "LOCAL", true],
    ["keyboard", "Push-to-talk", "Ctrl + R · Hold", null, false],
    ["device", "Microphone", "Default device", null, false],
    ["hash", "Hotwords", "3 words saved", null, false],
    ["clock", "Recent history", "3 dictations", null, false],
    ["power", "Startup", "On at sign-in", "ON", false],
  ];
  return (
    <div className="frame">
    <Win title="Dictate" width={760} height={660}>
      <div className="layC">
        <div className="c-head">
          <div className="hero-mic"><Icon name="mic" size={24} /></div>
          <div style={{ flex: 1 }}>
            <h2>Good to go</h2>
            <div className="hero-line" style={{ marginTop: 4 }}><Dot live />
              <span className="t-meta">Ready · hold <Kbd>Ctrl</Kbd><span className="plus">+</span><Kbd>R</Kbd> to dictate</span></div>
          </div>
          <span className="icon-btn"><Icon name="gear" size={18} /></span>
        </div>

        <div className="c-grid">
          {cards.map(([ic, t, v, tag, sel]) => (
            <div key={t} className="c-card">
              <div className="c-card-top">
                <span className="c-ic"><Icon name={ic} size={18} /></span>
                {tag && <Chip live={sel}>{tag}</Chip>}
              </div>
              <div className="c-card-t">{t}</div>
              <div className="c-card-v">{v}</div>
              <span className="c-chev"><Icon name="chev" size={16} /></span>
            </div>
          ))}
        </div>

        <div className="c-foot">
          <span className="t-meta">Dictate v2026.2.25 · up to date</span>
          <Btn ghost sm icon="status">Run doctor</Btn>
        </div>
      </div>
    </Win>
    <Note k="C">Springboard — glanceable home of cards, each shows its current value; click to drill in. Focused.</Note>
    </div>
  );
}

Object.assign(window, { DirA, DirB, DirC });
