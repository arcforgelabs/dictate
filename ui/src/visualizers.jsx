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
    : showResumeHint
      ? <Icon name="play" size={38} />
      : paused
        ? <Icon name="pause" size={38} />
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

/* ── WaveTimeline: scrolling level meter shown while recording before any
   transcript text arrives. New samples enter at the RIGHT and flow LEFT over
   time — a timeline of the last few seconds of input. Bars bloom green when the
   mic picks up speech and recede to a faint baseline in silence, so the strip
   literally shows whether audio is being heard.

   Source of truth: the real microphone (Web Audio AnalyserNode) when the
   browser grants access — so it reacts to your actual voice in the dev loop.
   If the mic is unavailable or denied, it falls back to the same synthetic
   speech `envelope` the cradle breathes on, so it's never dead. ──────────── */
const WAVE_BAR_W = 3;            // bar width (css px)
const WAVE_GAP = 3;             // gap between bars (css px)
const WAVE_SLOT = WAVE_BAR_W + WAVE_GAP;
const WAVE_STEP_MS = 60;        // time between new samples → scroll speed

export function WaveTimeline({ active = true, reduced = false, label = "Listening for speech" }) {
  const canvasRef = useRef(null);
  const stateRef = useRef({ samples: [], raf: 0, lastStep: 0, level: 0 });
  const audioRef = useRef({ ctx: null, analyser: null, stream: null, data: null, ready: false });

  // Open the real microphone while active; tear it down on stop/unmount.
  useEffect(() => {
    if (!active || reduced) return;
    let cancelled = false;
    const a = audioRef.current;
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) return;
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        const Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) { stream.getTracks().forEach((t) => t.stop()); return; }
        const ctx = new Ctx();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        ctx.createMediaStreamSource(stream).connect(analyser);
        a.ctx = ctx; a.analyser = analyser; a.stream = stream;
        a.data = new Uint8Array(analyser.fftSize); a.ready = true;
      } catch {
        a.ready = false; // denied / no device → synthetic fallback keeps it alive
      }
    })();
    return () => {
      cancelled = true;
      a.ready = false;
      if (a.stream) a.stream.getTracks().forEach((t) => t.stop());
      if (a.ctx) a.ctx.close().catch(() => {});
      a.ctx = a.analyser = a.stream = a.data = null;
    };
  }, [active, reduced]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let ctx = null;
    try { ctx = canvas.getContext && canvas.getContext("2d"); } catch { ctx = null; }
    if (!ctx) return; // jsdom / no 2d context → render nothing, never crash
    const st = stateRef.current;
    st.samples = []; st.lastStep = 0; st.level = 0;

    const cs = getComputedStyle(canvas);
    const liveColor = cs.getPropertyValue("--live").trim() || "#2f8f63";
    const subtleColor = cs.getPropertyValue("--subtle").trim() || "rgba(27,26,22,.4)";
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    let W = 0, H = 0, capacity = 0;

    const resize = () => {
      W = canvas.clientWidth || 320;
      H = canvas.clientHeight || 40;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      capacity = Math.ceil(W / WAVE_SLOT) + 3;
    };
    resize();
    let ro = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(resize);
      ro.observe(canvas);
    }

    const sampleLevel = (t) => {
      const a = audioRef.current;
      if (a.ready && a.analyser && a.data) {
        a.analyser.getByteTimeDomainData(a.data);
        let sum = 0;
        for (let i = 0; i < a.data.length; i++) { const v = (a.data[i] - 128) / 128; sum += v * v; }
        const rms = Math.sqrt(sum / a.data.length);
        return Math.min(1, rms * 3.4); // typical speech RMS is small → boost into 0..1
      }
      return envelope(t); // synthetic speech fallback
    };

    // Static reduced-motion view: a calm, fixed baseline of faint ticks.
    if (reduced) {
      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, W, H);
      const mid = H / 2;
      ctx.fillStyle = subtleColor;
      ctx.globalAlpha = 0.5;
      for (let x = W % WAVE_SLOT; x < W; x += WAVE_SLOT) {
        roundRect(ctx, x, mid - 1.5, WAVE_BAR_W, 3, 1.5);
        ctx.fill();
      }
      ctx.restore();
      return () => { ro && ro.disconnect(); };
    }

    const draw = (frac) => {
      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, W, H);
      const mid = H / 2;
      const n = st.samples.length;
      const offset = frac * WAVE_SLOT; // sub-step shift → smooth continuous scroll
      for (let i = 0; i < n; i++) {
        const s = st.samples[i];
        const x = W - (n - 1 - i) * WAVE_SLOT - WAVE_BAR_W - offset;
        if (x < -WAVE_SLOT || x > W) continue;
        const heard = s > 0.06;
        const h = heard ? Math.max(3, s * (H - 4)) : 3;
        ctx.fillStyle = heard ? liveColor : subtleColor;
        ctx.globalAlpha = heard ? 0.3 + s * 0.7 : 0.35;
        roundRect(ctx, x, mid - h / 2, WAVE_BAR_W, h, WAVE_BAR_W / 2);
        ctx.fill();
      }
      ctx.restore();
    };

    let mounted = true;
    const frame = (now) => {
      if (!mounted) return;
      if (!st.lastStep) st.lastStep = now;
      while (now - st.lastStep >= WAVE_STEP_MS) {
        st.lastStep += WAVE_STEP_MS;
        const tgt = active ? sampleLevel(st.lastStep / 1000) : 0;
        st.level += (tgt - st.level) * 0.55; // light smoothing → fluid, not jittery
        if (st.level < 0.002) st.level = 0;
        st.samples.push(st.level);
        if (st.samples.length > capacity) st.samples.shift();
      }
      draw(Math.min(1, (now - st.lastStep) / WAVE_STEP_MS));
      st.raf = requestAnimationFrame(frame);
    };
    st.raf = requestAnimationFrame(frame);

    return () => {
      mounted = false;
      cancelAnimationFrame(st.raf);
      ro && ro.disconnect();
    };
  }, [active, reduced]);

  return (
    <div className="wave-timeline" role="img" aria-label={label}>
      <canvas ref={canvasRef} aria-hidden="true" />
      <span className="sr-only">{label}…</span>
    </div>
  );
}

// Rounded-rect path helper (roundRect isn't in every canvas impl yet).
function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}
