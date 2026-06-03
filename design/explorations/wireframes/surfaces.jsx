// surfaces.jsx — supporting Dictate surfaces shared across all directions.
// Listening HUD variants · first-run onboarding · recent history · tray menu.

/* ============================ LISTENING HUD ============================ */
// Shown on a faint desktop backdrop so they read as floating overlays.
function HudStage({ children, label, k }) {
  return (
    <div className="hud-stage">
      <div className="hud-bg" />
      {children}
      <div className="hud-cap"><span className="wf-k">{k}</span>{label}</div>
    </div>
  );
}

function HudPill() {
  return (
    <HudStage k="1" label="Anchored pill — waveform + release hint">
      <div className="hud-pill">
        <span className="hud-dot" />
        <Wave n={20} color="var(--live)" />
        <span className="hud-txt">Listening…</span>
        <span className="hud-rel">release <Kbd dark>Ctrl</Kbd></span>
      </div>
    </HudStage>
  );
}

function HudChip() {
  return (
    <HudStage k="2" label="Corner chip — minimal, with elapsed time">
      <div className="hud-chip">
        <span className="hud-dot" /><span className="hud-txt">Rec</span>
        <span className="hud-time t-mono">0:03</span>
      </div>
    </HudStage>
  );
}

function HudOrb() {
  return (
    <HudStage k="3" label="Centered orb — breathing mic, ambient">
      <div className="hud-orb-wrap">
        <div className="hud-orb"><Icon name="mic" size={26} /></div>
        <div className="hud-orb-txt">Listening</div>
      </div>
    </HudStage>
  );
}

/* ============================ ONBOARDING (3 steps) ============================ */
function OnbStep({ step, total, eyebrow, title, children, primary, back }) {
  return (
    <Win title="Dictate" sub="Setup" width={440} height={560}>
      <div className="onb">
        <div className="onb-dots">
          {Array.from({ length: total }, (_, i) =>
            <span key={i} className={"onb-d" + (i < step ? " done" : "") + (i === step - 1 ? " now" : "")} />)}
        </div>
        <div className="onb-mark" dangerouslySetInnerHTML={{ __html: ARC_MARK }} />
        <Eyebrow>{eyebrow}</Eyebrow>
        <h2 style={{ marginTop: 6 }}>{title}</h2>
        <div className="onb-body">{children}</div>
        <div className="onb-actions">
          {back ? <Btn ghost>Back</Btn> : <Btn ghost>Skip for now</Btn>}
          <Btn primary>{primary}</Btn>
        </div>
      </div>
    </Win>
  );
}

function OnbModel() {
  const m = [["faster-whisper · turbo", "Runs locally — no key", true],
    ["gpt-4o-mini-transcribe", "OpenAI · hosted", false],
    ["grok-speech-to-text", "xAI · hosted", false]];
  return (
    <OnbStep step={1} total={3} eyebrow="Step 1 of 3" title="Choose how Dictate hears you" primary="Continue">
      <p className="onb-lede">Pick a transcription model. You can change it any time.</p>
      <div className="opt-list">
        {m.map(([t, d, sel]) => (
          <div key={t} className={"opt" + (sel ? " sel" : "")}>
            <span className={"radio" + (sel ? " on" : "")} />
            <div style={{ flex: 1 }}><div className="opt-t">{t}</div><div className="opt-d">{d}</div></div>
          </div>
        ))}
      </div>
    </OnbStep>
  );
}

function OnbKey() {
  return (
    <OnbStep step={2} total={3} eyebrow="Step 2 of 3" title="Add your API key" primary="Continue" back>
      <p className="onb-lede">For hosted models. Stored in your system keychain — never written to config.</p>
      <div className="field">
        <label className="t-label">OpenAI API key</label>
        <div className="input"><span className="t-mono" style={{ color: "var(--subtle)" }}>sk-····································</span>
          <Icon name="key" size={16} style={{ color: "var(--muted)" }} /></div>
      </div>
      <div className="onb-help"><Icon name="check" size={14} style={{ color: "var(--live)" }} />Held in OS secret store</div>
    </OnbStep>
  );
}

function OnbPtt() {
  return (
    <OnbStep step={3} total={3} eyebrow="Step 3 of 3" title="Set your push-to-talk key" primary="Finish setup" back>
      <p className="onb-lede">Press the keys you want to hold while speaking.</p>
      <div className="capture">
        <div className="capture-keys"><Kbd>Right Ctrl</Kbd></div>
        <div className="t-meta">Listening for keys… press a combination</div>
      </div>
      <Row label="Activation" help="Hold or toggle"
        control={<div className="seg"><span className="seg-i on">Hold</span><span className="seg-i">Toggle</span></div>} last />
    </OnbStep>
  );
}

/* ============================ RECENT HISTORY ============================ */
function HistoryPanel() {
  const items = [
    ["1", "2:04 PM · just now", "Can you push the release branch and tag it v2026.6.2 before the standup at ten."],
    ["2", "1:51 PM · 13m ago", "Reminder to follow up with the Stalwart team about the OAuth scopes."],
    ["3", "11:32 AM · 2h ago", "Draft a short note thanking the beta testers and ask for crash reports."],
  ];
  return (
    <Win title="Dictate" sub="Recent history" width={460} height={500}>
      <div className="hist">
        <div className="hist-head">
          <div><h3>Recent history</h3><div className="t-meta">Last 3 dictations · stored locally</div></div>
        </div>
        <div className="hist-list">
          {items.map(([i, time, text]) => (
            <div key={i} className="hist-item">
              <span className="hist-i t-mono">{i}</span>
              <div className="hist-main">
                <div className="hist-time">{time}</div>
                <div className="hist-text">{text}</div>
              </div>
              <Btn ghost sm icon="copy">Copy</Btn>
            </div>
          ))}
        </div>
        <div className="hist-foot">
          <span className="t-meta">Cleared automatically after 3 entries</span>
          <Btn ghost sm danger>Clear history</Btn>
        </div>
      </div>
    </Win>
  );
}

/* ============================ TRAY MENU ============================ */
function TrayMenu() {
  return (
    <div className="tray-stage">
      <div className="tray-bar">
        <span className="tray-ic" dangerouslySetInnerHTML={{ __html: ARC_MARK }} />
      </div>
      <div className="tray-menu">
        <div className="tray-head"><Dot live /><span>Dictate · Ready</span><span className="t-mono" style={{ marginLeft: "auto", color: "var(--subtle)" }}>turbo</span></div>
        <div className="tray-row"><Icon name="mic" size={16} /><span>Dictate once</span><span className="tray-k"><Kbd>Right Ctrl</Kbd></span></div>
        <div className="tray-row"><Icon name="clock" size={16} /><span>Recent history…</span></div>
        <div className="tray-div" />
        <div className="tray-row"><Icon name="sliders" size={16} /><span>Model</span><Icon name="chev" size={14} style={{ marginLeft: "auto", color: "var(--subtle)" }} /></div>
        <div className="tray-row"><Icon name="gear" size={16} /><span>Settings…</span></div>
        <div className="tray-div" />
        <div className="tray-row"><span className="tray-check"><Icon name="check" size={14} /></span><span>Launch on startup</span></div>
        <div className="tray-row danger"><Icon name="power" size={16} /><span>Quit Dictate</span></div>
      </div>
      <div className="hud-cap"><span className="wf-k">4</span>Tray menu — the always-present entry point</div>
    </div>
  );
}

Object.assign(window, { HudPill, HudChip, HudOrb, OnbModel, OnbKey, OnbPtt, HistoryPanel, TrayMenu });
