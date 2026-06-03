// ds-components.jsx — Components & Patterns. Live instances of the real controls.
const { useState: cS } = React;

/* small stateful wrappers so demos actually work */
function ToggleDemo({ init }) { const [on, setOn] = cS(init); return <Toggle on={on} onChange={setOn} />; }
function SegDemo({ options, init }) { const [v, setV] = cS(init); return <Seg options={options} value={v} onChange={setV} />; }
function OptDemo() {
  const [sel, setSel] = cS("a");
  const rows = [["a", "cpu", "faster-whisper · turbo", "Runs locally — no key", true], ["b", null, "gpt-4o-mini-transcribe", "OpenAI · hosted", false]];
  return <div className="opts" style={{ width: "100%" }}>
    {rows.map(([id, ic, t, d, local]) => (
      <button key={id} className={"opt" + (sel === id ? " sel" : "")} onClick={() => setSel(id)}>
        <span className="radio" />
        <span className="brand">{ic ? <Icon name="cpu" size={17} /> : <Brand name="openai" />}</span>
        <span className="main"><span className="ot">{t}{local && <Chip live>LOCAL</Chip>}</span><span className="od">{d}</span></span>
        {!local && (sel === id ? <Chip live>CONNECTED</Chip> : <Chip>NEEDS KEY</Chip>)}
      </button>
    ))}
  </div>;
}
function HotwordsDemo() {
  const [words, setWords] = cS(["AcmeWidget", "Stalwart"]);
  return <div className="words" style={{ width: "100%" }}>
    {words.map(w => <span key={w} className="word">{w}<button onClick={() => setWords(words.filter(x => x !== w))}><Icon name="x" size={13} /></button></span>)}
    <span className="word-input"><Icon name="plus" size={14} style={{ color: "var(--subtle)" }} /><input placeholder="Add a word…" readOnly style={{ width: 96 }} /></span>
  </div>;
}

function Components() {
  return (
    <React.Fragment>
      {/* 06 CONTROLS */}
      <section className="ds-section" id="controls">
        <SecHead n="06" title="Controls">
          The interactive vocabulary. One primary action per view; everything else is quiet until hovered. Each control
          here is the live component from the app — click them.
        </SecHead>

        <SubHead icon="bolt">Buttons</SubHead>
        <Demo foot="Buttons" desc="Primary · default · ghost · danger" token=".btn">
          <span className="ds-clbl">Sizes & intents</span>
          <button className="btn primary"><Icon name="mic" size={16} />Hold to dictate</button>
          <button className="btn">Rebind</button>
          <button className="btn ghost"><Icon name="copy" size={15} />Copy</button>
          <button className="btn danger"><Icon name="trash" size={15} />Clear</button>
          <button className="btn sm">Small</button>
          <button className="btn primary sm">Save &amp; select</button>
        </Demo>

        <div className="ds-grid c3" style={{ marginTop: 16 }}>
          <Demo center foot="Toggle" token=".toggle" desc="Binary settings">
            <ToggleDemo init={true} /><ToggleDemo init={false} />
          </Demo>
          <Demo center foot="Segmented" token=".seg" desc="2–3 exclusive options">
            <SegDemo options={[{ v: "hold", l: "Hold" }, { v: "toggle", l: "Toggle" }]} init="hold" />
          </Demo>
          <Demo center foot="Select" token=".select" desc="Longer option sets">
            <button className="select">Default device<Icon name="chevd" size={14} style={{ color: "var(--muted)" }} /></button>
          </Demo>
        </div>

        <SubHead icon="keyboard">Keys & inputs</SubHead>
        <div className="ds-grid c3">
          <Demo center foot="Keycaps" token=".kbd · Combo" desc="Shortcuts in mono">
            <Combo keys={["Right Ctrl"]} lg /><Kbd>⌘K</Kbd>
          </Demo>
          <Demo center foot="Text field" token=".input" desc="Keys, hotwords, search">
            <div className="input" style={{ width: "100%" }}><Icon name="key" size={16} style={{ color: "var(--muted)" }} />
              <input className="mono" placeholder="sk-································" readOnly /></div>
          </Demo>
          <Demo center foot="Key capture" token=".capture" desc="Live rebinding target">
            <div className="capture armed" style={{ width: "100%", padding: 18 }}>
              <div className="keys"><Combo keys={["Right Ctrl"]} lg /></div>
              <div className="t-meta">Listening for keys…</div></div>
          </Demo>
        </div>

        <SubHead icon="hash">Status & tags</SubHead>
        <Demo foot="Chips, badges & dots" token=".chip · .dot" desc="State at a glance — colour only when it means something">
          <Chip live>LOCAL</Chip><Chip>NEEDS KEY</Chip><Chip live>CONNECTED</Chip><Chip danger>OFFLINE</Chip>
          <span style={{ width: 1, height: 22, background: "var(--border)" }} />
          <span style={{ display: "flex", alignItems: "center", gap: 7 }}><Dot live /><span className="t-meta">Ready</span></span>
          <span style={{ display: "flex", alignItems: "center", gap: 7 }}><Dot amber /><span className="t-meta">Connecting</span></span>
          <span style={{ display: "flex", alignItems: "center", gap: 7 }}><Dot /><span className="t-meta">Idle</span></span>
        </Demo>
      </section>

      {/* 07 CONTAINERS */}
      <section className="ds-section" id="containers">
        <SecHead n="07" title="Containers">
          How content is grouped. Settings live as <em>rows</em> inside padded cards; choices live as <em>option lists</em>;
          glanceable values live as <em>mini cards</em>. Consistent left-label / right-control rhythm throughout.
        </SecHead>

        <SubHead icon="sliders">Setting rows</SubHead>
        <Demo col foot="Row group" token=".card.pad > .row" desc="Icon · label · helper · control">
          <div className="card pad" style={{ width: "100%" }}>
            <Row icon="device" label="Microphone" help="Audio input device">
              <button className="select">Default device<Icon name="chevd" size={14} style={{ color: "var(--muted)" }} /></button></Row>
            <Row icon="power" label="Launch on sign-in" help="Start Dictate automatically"><ToggleDemo init={true} /></Row>
            <Row icon="bolt" label="Activation" help="Hold the key, or tap to toggle">
              <SegDemo options={[{ v: "hold", l: "Hold" }, { v: "toggle", l: "Toggle" }]} init="hold" /></Row>
          </div>
        </Demo>

        <div className="ds-grid c2">
          <Demo col foot="Mini stat card" token=".minic" desc="Glanceable value · click to drill in">
            <button className="minic" style={{ width: "100%" }}>
              <div className="top"><Icon name="sliders" size={18} /><Icon name="chev" size={15} style={{ color: "var(--faint)" }} /></div>
              <div className="k">Model</div><div className="v">faster-whisper<Chip live>LOCAL</Chip></div></button>
          </Demo>
          <Demo col foot="Hotword chips" token=".word" desc="Removable tokens + inline add">
            <HotwordsDemo />
          </Demo>
        </div>

        <SubHead icon="cpu">Option list</SubHead>
        <Demo col foot="Radio option list" token=".opt" desc="Single-select with provider mark & state">
          <OptDemo />
        </Demo>

        <SubHead icon="status">Navigation rail</SubHead>
        <Demo foot="Sidebar nav items" token=".nav-item" desc="Rest · hover · active · with badge">
          <div style={{ width: 230, background: "var(--surface-2)", border: "1px solid var(--hairline)", borderRadius: "var(--r-md)", padding: 10, display: "flex", flexDirection: "column", gap: 2 }}>
            <button className="nav-item active"><Icon name="status" size={18} /><span>Status</span></button>
            <button className="nav-item"><Icon name="sliders" size={18} /><span>Model</span></button>
            <button className="nav-item"><Icon name="hash" size={18} /><span>Hotwords</span><span className="badge tnum">3</span></button>
          </div>
        </Demo>
      </section>

      {/* 08 PATTERNS */}
      <section className="ds-section" id="patterns">
        <SecHead n="08" title="Patterns">
          Where components combine into the moments that define Dictate — the status it shows at rest, the overlay while
          you speak, and the keyboard-first surfaces that keep your hands off the mouse.
        </SecHead>

        <SubHead icon="mic">Status hero</SubHead>
        <Demo col foot="Status hero" token=".hero" desc="The first thing you see — calm at rest, breathing when live">
          <div className="hero" style={{ width: "100%" }}>
            <div className="orb"><Icon name="mic" size={26} /></div>
            <div className="body">
              <div className="statusline"><Dot live /><span className="t-label" style={{ color: "var(--live)" }}>Ready</span>
                <span className="t-meta">·&nbsp; microphone connected</span></div>
              <h2 className="t-title" style={{ marginTop: 3 }}>Ready to dictate</h2>
              <div className="sub">Hold your shortcut, speak, and release — text types into the app you’re using.</div>
            </div>
            <div className="keyhint"><span className="t-label">Hold</span><Combo keys={["Right Ctrl"]} lg /></div>
          </div>
        </Demo>

        <SubHead icon="wave">Listening overlay</SubHead>
        <div className="ds-grid c2">
          <Demo center dark foot="Listening HUD" token=".hud-pill" desc="Floats above every app while recording">
            <div className="hud-pill">
              <span className="reckdot" /><Wave active bars={16} h={22} />
              <span className="txt">Listening</span><span className="timer">0:03</span>
              <span className="rel">release to insert</span></div>
          </Demo>
          <Demo center foot="Toast" token=".toast" desc="Quiet confirmation, auto-dismiss, undo where it counts">
            <div className="toast" style={{ position: "static" }}>
              <span className="ic"><Icon name="check" size={16} /></span><span>Inserted into Notes</span>
              <button className="undo">Undo</button></div>
          </Demo>
        </div>

        <SubHead icon="search">Command palette</SubHead>
        <Demo col foot="Command palette" token=".cmd" desc="⌘K — jump to any setting, switch model, run an action">
          <div className="cmd" style={{ width: "100%", boxShadow: "var(--shadow-md)" }}>
            <div className="cmd-in"><Icon name="search" size={18} style={{ color: "var(--muted)" }} />
              <input placeholder="Jump to a setting, switch model, run an action…" readOnly /><Kbd>esc</Kbd></div>
            <div className="cmd-list">
              <div className="cmd-grp">Actions</div>
              <button className="cmd-item cur"><Icon name="mic" size={17} /><span>Try dictation</span></button>
              <button className="cmd-item"><Icon name="moon" size={17} /><span>Switch to dark</span></button>
              <div className="cmd-grp">Models</div>
              <button className="cmd-item"><Brand name="openai" /><span>Use gpt-4o-mini-transcribe</span><span className="meta">OpenAI</span></button>
            </div>
          </div>
        </Demo>

        <SubHead icon="shield">Diagnostics & empty states</SubHead>
        <div className="ds-grid c2">
          <Demo col foot="Doctor checks" token=".check" desc="Animated, honest self-test">
            <div className="card tight" style={{ width: "100%" }}><div className="checks">
              {[["Microphone access", "Default device responding"], ["Model loads", "faster-whisper · turbo"], ["Shortcut registered", "Right Ctrl"]].map(([l, s]) => (
                <div className="check" key={l}><span className="st ok"><Icon name="check" size={13} /></span>
                  <div className="main"><div>{l}</div><div className="sub">{s}</div></div></div>
              ))}
            </div></div>
          </Demo>
          <Demo col foot="Empty state" token="—" desc="Plain, never apologetic">
            <div className="card tight" style={{ width: "100%", textAlign: "center", padding: "36px 20px", color: "var(--muted)" }}>
              <Icon name="history" size={26} style={{ color: "var(--faint)", margin: "0 auto 10px" }} />
              <div className="t-heading" style={{ color: "var(--fg)" }}>Nothing here yet</div>
              <div className="t-meta" style={{ marginTop: 4 }}>Recent dictations show up here for quick recovery.</div>
            </div>
          </Demo>
        </div>
      </section>
    </React.Fragment>
  );
}

Object.assign(window, { Components });
