// ds-foundations.jsx — Foundations: brand, color, type, spacing, radius, elevation, motion.

/* shared bits */
function SubHead({ icon, children, meta }) {
  return <div className="ds-subhead">
    {icon && <span className="ic"><Icon name={icon} size={17} /></span>}
    <h3>{children}</h3><span className="ln" />{meta && <span className="meta">{meta}</span>}
  </div>;
}
function SecHead({ n, title, children }) {
  return <div className="ds-sec-head"><span className="ds-num">{n}</span>
    <div className="tx"><h2>{title}</h2><p>{children}</p></div></div>;
}
function Demo({ children, col, center, foot, token, desc, dark }) {
  return <div className="ds-gitem"><div className="ds-card">
    <div className={"ds-demo" + (col ? " col" : "") + (center ? " center" : "") + (dark ? " dark-preview" : "")}>{children}</div>
    {(foot || token || desc) && <div className="ds-foot">
      {foot && <span className="nm">{foot}</span>}{desc && <span className="ds-desc">{desc}</span>}
      {token && <span className="ds-token">{token}</span>}</div>}
  </div></div>;
}

/* ---------------- COLOR DATA ---------------- */
const COLORS = {
  Surfaces: [
    ["Paper", "--bg", "#efece6", "#0a0a0b"],
    ["Sunk", "--bg-2", "#e9e5dd", "#050506"],
    ["Surface", "--surface", "#ffffff", "#19191c"],
    ["Raised", "--surface-2", "#f7f5f1", "#212126"],
    ["Inset", "--surface-3", "#f0ede7", "#2c2c33"],
  ],
  Ink: [
    ["Ink", "--fg", "#1b1a16", "#f3f1ec"],
    ["Muted", "--muted", "rgba(27,26,22,.56)", "rgba(243,241,236,.60)"],
    ["Subtle", "--subtle", "rgba(27,26,22,.40)", "rgba(243,241,236,.42)"],
    ["Faint", "--faint", "rgba(27,26,22,.22)", "rgba(243,241,236,.22)"],
  ],
  Lines: [
    ["Border", "--border", "rgba(27,26,22,.10)", "rgba(243,241,236,.14)"],
    ["Border strong", "--border-2", "rgba(27,26,22,.16)", "rgba(243,241,236,.24)"],
    ["Hairline", "--hairline", "rgba(27,26,22,.07)", "rgba(243,241,236,.09)"],
  ],
  Signal: [
    ["Primary", "--primary", "#1b1a16", "#f3f1ec"],
    ["Live", "--live", "#2f8f63", "#4fbd86"],
    ["Danger", "--danger", "#c5402c", "#ff6b5b"],
    ["Amber", "amber", "#c08a2d", "#c08a2d"],
  ],
};
function shortVal(v) { return v.length > 10 ? "α " + v.slice(v.lastIndexOf(",") + 1).replace(")", "") : v; }
function ColorCard({ c }) {
  const [name, vr, light, dark] = c;
  return <div className="ds-color">
    <span className="chip" style={{ background: vr === "amber" ? "#c08a2d" : `var(${vr})` }} />
    <div className="meta">
      <div className="nm">{name}</div>
      <div className="var">{vr === "amber" ? "(signal)" : vr}</div>
      <div className="vals">
        <span className="v" title={"light · " + light}><b style={{ background: light }} />{shortVal(light)}</span>
        <span className="v" title={"dark · " + dark}><b style={{ background: dark }} />{shortVal(dark)}</span>
      </div>
    </div>
  </div>;
}

/* ---------------- TYPE DATA ---------------- */
const TYPE = [
  ["Display", "Ready to dictate", { fontSize: 30, fontWeight: 800, letterSpacing: "-.03em" }, "30 / 800 / -3%", "Hanken Grotesk"],
  ["Title", "Transcription model", { fontSize: 23, fontWeight: 800, letterSpacing: "-.02em" }, "23 / 800 / -2%", "Hanken Grotesk"],
  ["Heading", "Local compute", { fontSize: 17, fontWeight: 700, letterSpacing: "-.01em" }, "17 / 700 / -1%", "Hanken Grotesk"],
  ["Body", "Hold your shortcut, speak, release.", { fontSize: 14.5, fontWeight: 400 }, "14.5 / 400", "Hanken Grotesk"],
  ["Meta", "microphone connected", { fontSize: 12.5, fontWeight: 400, color: "var(--muted)" }, "12.5 / 400 · muted", "Hanken Grotesk"],
  ["Label", "PUSH-TO-TALK", { fontSize: 10.5, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase", color: "var(--subtle)" }, "10.5 / 700 / +7% caps", "Hanken Grotesk"],
  ["Mono", "faster-whisper · int8", { fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 500, letterSpacing: ".02em" }, "JetBrains Mono 500", "JetBrains Mono"],
];

/* ---------------- SCALES ---------------- */
const SPACING = [["4", 4, "hairline gaps"], ["8", 8, "control gaps"], ["12", 12, "card padding"], ["16", 16, "grid gaps"], ["22", 22, "card inset"], ["24", 24, "section gaps"], ["40", 40, "view padding"], ["56", 56, "view bottom"]];
const RADIUS = [["--r-sm", 9, "inputs, buttons"], ["--r-md", 13, "cards, fields"], ["--r-lg", 18, "panels, options"], ["--r-xl", 24, "status hero"], ["--r-pill", 999, "chips, toggles"]];
const MOTION = [["--t-fast", "140ms", "hovers, taps"], ["--t", "240ms", "view & theme"], ["--t-slow", "420ms", "entrances"], ["breath", "3.8s", "live pulse loop"]];

function Foundations() {
  return (
    <React.Fragment>
      {/* 01 BRAND */}
      <section className="ds-section" id="brand">
        <SecHead n="01" title="Brand & voice">
          Dictate is a tool that disappears. It lives in the tray and surfaces only when summoned — so the system
          is built to recede: warm paper greys, one living green for “listening”, and a single breathing pulse as
          the only thing that ever loops.
        </SecHead>

        <div className="ds-grid c2">
          <Demo center foot="Arc mark" token="assets/arc-mark.svg" desc="Carried at 16–20px in the title bar & tray">
            <div style={{ width: 86, height: 86, color: "var(--fg)" }}><ArcMark /></div>
          </Demo>
          <Demo center foot="Mic motif" token="--surface · ring" desc="The one figurative glyph — recording orb & rail">
            <div style={{ display: "flex", gap: 22, alignItems: "center" }}>
              <span style={{ width: 64, height: 64, borderRadius: "50%", background: "var(--surface-2)", border: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fg)", boxShadow: "var(--shadow-sm)" }}><Icon name="mic" size={26} /></span>
              <span className="hero live" style={{ padding: 0, border: "none", boxShadow: "none", background: "none" }}>
                <span className="orb" style={{ width: 64, height: 64 }}><Icon name="mic" size={26} /></span></span>
            </div>
          </Demo>
        </div>

        <SubHead icon="wave">Voice — how Dictate speaks</SubHead>
        <div className="ds-grid c2">
          <div className="ds-rule do"><div className="h"><Icon name="check" size={15} />Plain, present-tense, calm</div>
            <p>“Hold your shortcut, speak, release.” · “Stored in your system keychain.” Short, literal, reassuring. Tell people where their audio goes.</p></div>
          <div className="ds-rule dont"><div className="h"><Icon name="x" size={15} />No hype, no jargon, no alarm</div>
            <p>Avoid “AI-powered”, “seamless”, exclamation marks, and red unless something is truly destructive. The product should feel quiet.</p></div>
        </div>
      </section>

      {/* 02 COLOR */}
      <section className="ds-section" id="color">
        <SecHead n="02" title="Color">
          A warm greyscale built from a single paper hue, with desaturated ink set as alpha so text sits naturally on
          any surface. Every token is defined for both light and dark; swatches below reflect the theme you’re viewing —
          toggle it top-right.
        </SecHead>
        {Object.entries(COLORS).map(([grp, list]) => (
          <React.Fragment key={grp}>
            <SubHead meta={grp === "Signal" ? "use sparingly" : null}>{grp}</SubHead>
            <div className="ds-grid c4">{list.map(c => <ColorCard key={c[1] + c[0]} c={c} />)}</div>
          </React.Fragment>
        ))}
      </section>

      {/* 03 TYPE */}
      <section className="ds-section" id="type">
        <SecHead n="03" title="Typography">
          Two families. <strong>Hanken Grotesk</strong> carries everything human — tight, confident headings and calm
          body. <strong>JetBrains Mono</strong> handles the machine: shortcuts, model ids, timers, versions.
        </SecHead>
        <div className="ds-grid c2">
          <div className="ds-font"><div className="big">Aa</div>
            <div className="glyphs">Hh Gg Rr 0123 — listen, type</div>
            <div className="nm"><span className="t">Hanken Grotesk</span><span className="r">400 · 500 · 600 · 700 · 800</span></div></div>
          <div className="ds-font"><div className="big" style={{ fontFamily: "var(--font-mono)" }}>Aa</div>
            <div className="glyphs" style={{ fontFamily: "var(--font-mono)" }}>Right Ctrl · int8 · 0:03</div>
            <div className="nm"><span className="t">JetBrains Mono</span><span className="r">400 · 500 · 600</span></div></div>
        </div>
        <SubHead meta="7 roles">Scale</SubHead>
        <div className="ds-card"><div className="ds-type">
          {TYPE.map(([role, sample, st, dt]) => (
            <div className="ds-type-row" key={role}>
              <div className="spec" style={st}>{sample}</div>
              <div className="info"><span className="rl">{role}</span><span className="dt">{dt}</span></div>
            </div>
          ))}
        </div></div>
      </section>

      {/* 04 SPACING + RADIUS */}
      <section className="ds-section" id="space">
        <SecHead n="04" title="Spacing, radius & elevation">
          Spacing steps are even and few. Radii climb with surface size — small for controls, generous for the status
          hero. Shadows are soft and warm; in dark mode they deepen rather than glow.
        </SecHead>
        <div className="ds-grid c2">
          <div><SubHead meta="px">Spacing</SubHead>
            <div className="ds-card"><div className="ds-scale">
              {SPACING.map(([l, px, d]) => (
                <div className="ds-scale-row" key={l}><span className="rl">{l}</span>
                  <span className="viz"><span className="ds-bar" style={{ width: px }} /></span>
                  <span className="desc">{d}</span></div>
              ))}
            </div></div>
          </div>
          <div><SubHead meta="border-radius">Radius</SubHead>
            <div className="ds-card"><div className="ds-scale">
              {RADIUS.map(([v, px, d]) => (
                <div className="ds-scale-row" key={v}><span className="rl" style={{ width: 92 }}>{v}</span>
                  <span className="viz"><span className="ds-radbox" style={{ borderRadius: px === 999 ? 99 : px }} /></span>
                  <span className="desc">{d}</span></div>
              ))}
            </div></div>
          </div>
        </div>
        <SubHead meta="warm, low">Elevation</SubHead>
        <div className="ds-grid c4">
          {[["--shadow-sm", "cards at rest"], ["--shadow-md", "hover lift"], ["--shadow-lg", "window, HUD"], ["--shadow-pop", "palette, menus"]].map(([v, d]) => (
            <Demo key={v} center foot={v.replace("--shadow-", "")} desc={d}>
              <div className="ds-elev" style={{ boxShadow: `var(${v})`, width: "100%" }}>{v.replace("--", "")}</div>
            </Demo>
          ))}
        </div>
      </section>

      {/* 05 MOTION */}
      <section className="ds-section" id="motion">
        <SecHead n="05" title="Motion">
          Motion is functional and brief. One easing for the everyday, a softer one for entrances. The only loop in the
          whole product is the 3.8s “breath” on a live agent — everything else settles and stops.
        </SecHead>
        <div className="ds-grid c2">
          <div className="ds-card"><div className="ds-scale">
            {MOTION.map(([v, t, d]) => (
              <div className="ds-scale-row" key={v}><span className="rl" style={{ width: 84 }}>{v}</span>
                <span className="px" style={{ width: 56 }}>{t}</span><span className="viz" /><span className="desc">{d}</span></div>
            ))}
          </div></div>
          <Demo center foot="“Breath” — the only loop" token="3.8s · ease" desc="Signals a live, listening agent">
            <span className="hero live" style={{ padding: 0, border: "none", boxShadow: "none", background: "none" }}>
              <span className="orb" style={{ width: 72, height: 72 }}><Icon name="mic" size={28} /></span></span>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}><Dot live /><span className="t-meta">Listening</span></span>
          </Demo>
        </div>
      </section>
    </React.Fragment>
  );
}

Object.assign(window, { Foundations, SubHead, SecHead, Demo });
