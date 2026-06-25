// visualizers.jsx — Breath Cradle: the one recording gesture for Note Capture.
// The capture mic (the brand Mark) IS the button; while recording it fills with
// the living green and BREATHES on the 3.8 s loop. At conversational volume it
// stays calm; a ring blooms outward from the cradle ONLY on real emphasis; in
// silence the breath recedes until summoned. Reduced motion → a static
// state-colour cradle (steady ring, no loop).
import { useRef, useEffect, useState } from "react";
import { Icon, Mark } from "./icons.jsx";

// Synthetic speech envelope → 0..1 with ~2 s pauses between phrases (recede),
// a calm conversational floor, and an emphasis peak ~every 5 s that summons a ring.
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

export function BreathCradle({ active, paused, session, reduced, onStart, onPause, onResume }) {
  const wrapRef = useRef(null), btnRef = useRef(null), haloRef = useRef(null);
  const S = useRef({ amp: 0, armed: true, last: 0, raf: 0 });
  const [near, setNear] = useState(false);

  useEffect(() => {
    const wrap = wrapRef.current, btn = btnRef.current, halo = haloRef.current;
    const st = S.current;

    // idle: capsule nested in its cradle, dead still; reset amp so next recording starts clean
    if (!active) {
      st.amp = 0;
      if (halo) { halo.style.opacity = "0"; halo.style.transform = "translate(-50%,-50%) scale(1)"; }
      if (btn) btn.style.transform = "scale(1)";
      return;
    }
    // reduced motion: static state-colour cradle — steady ring, no loop, no blooms
    if (reduced) {
      if (halo) { halo.style.opacity = "0.5"; halo.style.transform = "translate(-50%,-50%) scale(1.16)"; }
      if (btn) btn.style.transform = "scale(1)";
      return;
    }

    let mounted = true;
    const frame = (now) => {
      if (!mounted) return;
      const t = now / 1000, tgt = envelope(t);
      const rate = tgt > st.amp ? 0.30 : 0.05; // fast attack, slow release → natural recede
      st.amp += (tgt - st.amp) * rate;
      if (st.amp < 0.002) st.amp = 0;

      const breath = 1 + 0.04 * Math.sin(t * 2 * Math.PI / 3.8); // THE 3.8 s loop
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

  const handleClick = () => {
    if (!session) onStart && onStart();
    else if (paused) onResume && onResume();
    else onPause && onPause();
  };

  const showStopHint = active && near;
  const showResumeHint = paused && near;
  const wrapClass = "recwrap"
    + (session ? " session" : "")
    + (active ? " live" : "")
    + (paused ? " paused" : "")
    + (showStopHint ? " stop-hint" : "")
    + (showResumeHint ? " resume-hint" : "");

  const btnClass = "recbtn"
    + (active ? " rec" : "")
    + (paused ? " paused" : "")
    + (showStopHint ? " stop-hint" : "")
    + (showResumeHint ? " resume-hint" : "");

  const label = !session
    ? "Start recording"
    : paused
      ? "Resume recording"
      : "Pause recording";

  const icon = showStopHint
    ? <Icon name="square" size={34} />
    : showResumeHint || paused
      ? <Icon name="mic" size={38} />
      : <Mark size={42} />;

  return (
    <div
      className={wrapClass}
      ref={wrapRef}
      onMouseEnter={() => setNear(true)}
      onMouseLeave={() => setNear(false)}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      aria-label={label}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleClick(); }
      }}
    >
      <div className="cradle-halo" ref={haloRef} aria-hidden="true" />
      <div
        className={btnClass}
        ref={btnRef}
        aria-hidden="true"
        style={active && !showStopHint ? { background: "var(--live-bg)", borderColor: "var(--live)", color: "var(--live)" } : undefined}
      >
        <span className="rb-ico">{icon}</span>
      </div>
    </div>
  );
}
