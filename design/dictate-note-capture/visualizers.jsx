// visualizers.jsx — Dictate's ONE recording gesture: the Breath Cradle.
// The capture mic (the brand mark) IS the button; while recording it fills with
// the living green and BREATHES on the 3.8s loop. At conversational volume it
// stays calm; a ring blooms outward from the cradle ONLY on real emphasis; in
// silence the breath recedes until summoned. Reduced motion → a static
// state-color cradle (steady ring, no loop). Amplitude here is synthetic (this
// is a frontend prototype) with built-in phrase pauses so the recede reads.
// Exports to window: BreathCradle.

const { useRef: vRef, useEffect: vEffect } = React;

// synthetic speech envelope → 0..1, with ~2s pauses between phrases (recede),
// a calm conversational floor, and an emphasis peak ~every 5s that summons a ring.
function envelope(t) {
  const inPhrase = (t % 6.2) < 4.2;
  if (!inPhrase) return 0;
  let base = 0.16 + 0.14 * Math.abs(Math.sin(t * 4.7)) + 0.06 * Math.abs(Math.sin(t * 9.1 + 1));
  const e = t % 5.0;
  if (e < 0.6) base += 0.55 * Math.max(0, Math.sin((e / 0.6) * Math.PI)); // stressed syllable
  return Math.min(1, base);
}

function spawnRing(wrap, born, mag0) {
  if (!wrap) return;
  const r = document.createElement("div");
  r.className = "cradle-ring";
  wrap.appendChild(r);
  const life = 1500, mag = 0.95 + mag0 * 0.95;
  const step = (now) => {
    const k = (now - born) / life;
    if (k >= 1) { r.remove(); return; }
    r.style.transform = `translate(-50%,-50%) scale(${(0.85 + k * mag).toFixed(3)})`;
    r.style.opacity = (0.38 * (1 - k)).toFixed(3);
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function BreathCradle({ active, reduced, onToggle }) {
  const wrapRef = vRef(null), btnRef = vRef(null), haloRef = vRef(null);
  const S = vRef({ amp: 0, armed: true, last: 0, raf: 0 });

  vEffect(() => {
    const wrap = wrapRef.current, btn = btnRef.current, halo = haloRef.current;
    const st = S.current;

    // idle: capsule nested in its cradle, dead still
    if (!active) {
      if (halo) { halo.style.opacity = "0"; halo.style.transform = "translate(-50%,-50%) scale(1)"; }
      if (btn) btn.style.transform = "scale(1)";
      return;
    }
    // reduced motion: static state-color cradle — steady ring, no loop, no blooms
    if (reduced) {
      if (halo) { halo.style.opacity = "0.5"; halo.style.transform = "translate(-50%,-50%) scale(1.16)"; }
      if (btn) btn.style.transform = "scale(1)";
      return;
    }

    let mounted = true;
    const frame = (now) => {
      if (!mounted) return;
      const t = now / 1000, tgt = envelope(t);
      const rate = tgt > st.amp ? 0.30 : 0.05;     // fast attack, slow release → natural recede
      st.amp += (tgt - st.amp) * rate;
      if (st.amp < 0.002) st.amp = 0;

      const breath = 1 + 0.04 * Math.sin(t * 2 * Math.PI / 3.8); // THE 3.8s loop
      if (halo) {
        halo.style.transform = `translate(-50%,-50%) scale(${(breath * (1 + st.amp * 0.25)).toFixed(3)})`;
        halo.style.opacity = (0.06 + st.amp * 0.5).toFixed(3); // calm floor, recede to ~.06 in pauses
      }
      if (btn) btn.style.transform = `scale(${breath.toFixed(3)})`;

      if (st.amp > 0.6 && st.armed && now - st.last > 360) { // bloom only on real emphasis
        st.armed = false; st.last = now; spawnRing(wrap, now, st.amp);
      }
      if (st.amp < 0.35) st.armed = true;

      st.raf = requestAnimationFrame(frame);
    };
    st.raf = requestAnimationFrame(frame);
    return () => { mounted = false; cancelAnimationFrame(st.raf); };
  }, [active, reduced]);

  return (
    <div className="recwrap" ref={wrapRef}>
      <div className="cradle-halo" ref={haloRef} aria-hidden="true" />
      <button className={"recbtn" + (active ? " rec" : "")} ref={btnRef}
        style={active ? { background: "var(--live-bg)", borderColor: "var(--live)", color: "var(--live)", WebkitTextFillColor: "var(--live)" } : undefined}
        onClick={onToggle} title={active ? "Stop" : "Record"}
        aria-label={active ? "Stop recording" : "Start recording"}>
        <span className="rb-ico"><Mark s={42} /></span>
      </button>
    </div>
  );
}

Object.assign(window, { BreathCradle });
