// icons.jsx — Dictate mark candidate, line-icon set, keycaps, and the sample
// transcript data shared across the note-capture prototype.
// Exports to window: Mark, Icon, Keys, SPEAKERS, MEETING, SHORT, fmt, tokens, getPartial.

/* ---- Dictate mark — the SHIPPED cradle-mic (1:1 with assets/dictate.svg).
   Exactly two shapes: capsule (mic body) resting in an open cradle arc. NO stem,
   NO base. This same mark IS the capture button (the Breath Cradle); the breath
   rings emanate from the arc. currentColor; carry at 16–20px. */
function Mark({ s = 18 }) {
  return (
    <svg width={s} height={s} viewBox="18 8 84 84" fill="none" aria-label="Dictate">
      <rect x="47" y="16" width="26" height="48" rx="13" fill="currentColor" />
      <path d="M28 48A32 32 0 0 0 92 48" fill="none" stroke="currentColor" strokeWidth="8" strokeLinecap="round" />
    </svg>
  );
}

/* ---- line icons (Lucide-style, 1.75 stroke, used sparingly) ---- */
const P = {
  mic: <><rect x="9" y="2.5" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" /></>,
  stop: <rect x="6.5" y="6.5" width="11" height="11" rx="3" fill="currentColor" stroke="none" />,
  gear: <><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></>,
  cmd: <path d="M9 6.5A2.5 2.5 0 1 0 6.5 9H9V6.5ZM15 6.5A2.5 2.5 0 1 1 17.5 9H15V6.5ZM9 17.5A2.5 2.5 0 1 1 6.5 15H9v2.5ZM15 17.5a2.5 2.5 0 1 0 2.5-2.5H15v2.5ZM9 9h6v6H9z" />,
  chev: <path d="M9 6l6 6-6 6" />,
  more: <><circle cx="5" cy="12" r="1.7" fill="currentColor" stroke="none" /><circle cx="12" cy="12" r="1.7" fill="currentColor" stroke="none" /><circle cx="19" cy="12" r="1.7" fill="currentColor" stroke="none" /></>,
  chevd: <path d="M6 9l6 6 6-6" />,
  back: <path d="M15 5l-7 7 7 7" />,
  check: <path d="M5 12.5l4.2 4.2L19 7" />,
  copy: <><rect x="9" y="9" width="11" height="11" rx="2.5" /><path d="M5 15H4.5A1.5 1.5 0 0 1 3 13.5V4.5A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5" /></>,
  insert: <><path d="M13 4h6v16h-6" /><path d="M3 12h11M9.5 7.5 14 12l-4.5 4.5" /></>,
  share: <><path d="M12 15V3.5M8 7l4-4 4 4" /><path d="M5 12v7.5h14V12" /></>,
  edit: <><path d="M4 20h4L19.5 8.5l-4-4L4 16v4Z" /><path d="M14 6l4 4" /></>,
  expand: <path d="M4 9.5V4h5.5M20 9.5V4h-5.5M4 14.5V20h5.5M20 14.5V20h-5.5" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></>,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  lock: <><rect x="4.5" y="10.5" width="15" height="10" rx="2.5" /><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" /></>,
  cloud: <path d="M7 18.5a4.2 4.2 0 0 1-.2-8.4 5.2 5.2 0 0 1 10-1.1A3.8 3.8 0 0 1 16.8 18.5H7Z" />,
  clock: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5v5l3 1.8" /></>,
  users: <><circle cx="9" cy="8.5" r="3.2" /><path d="M3.5 19a5.5 5.5 0 0 1 11 0M15.5 6.2a3.2 3.2 0 0 1 0 6M16.5 13.4a5.5 5.5 0 0 1 4 5.6" /></>,
  layers: <path d="M12 3 2.5 8 12 13l9.5-5L12 3ZM3 13l9 5 9-5M3 17.5l9 5 9-5" />,
  alert: <><path d="M12 4 2.6 20h18.8L12 4Z" /><path d="M12 10v4.4M12 17.4h.01" /></>,
  refresh: <><path d="M3.5 12a8.5 8.5 0 0 1 14.4-6.1M20.5 12a8.5 8.5 0 0 1-14.4 6.1" /><path d="M18 3.5V8h-4.5M6 20.5V16h4.5" /></>,
  micoff: <><rect x="9" y="2.5" width="6" height="8.2" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 10.9 4.8M18.5 11a6.4 6.4 0 0 1-.2 1.7" /><path d="M12 17.5V21M8.5 21h7" /><path d="M3.5 3.5l17 17" /></>,
  device: <><rect x="3" y="4.5" width="18" height="12" rx="2" /><path d="M8 20.5h8M12 16.5v4" /></>,
  cloudoff: <><path d="M7 18.5a4.2 4.2 0 0 1-.3-8.4 5.2 5.2 0 0 1 7.8-2.5" /><path d="M16.4 9.3A3.8 3.8 0 0 1 17 18.5h-7" /><path d="M3.5 3.5l17 17" /></>,
  trash: <><path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13" /></>,
};
function Icon({ n, s = 18 }) {
  return <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{P[n]}</svg>;
}

function Keys({ combo }) {
  return (
    <span className="keys">
      {combo.split("+").map((k, i) => (
        <React.Fragment key={i}>{i > 0 && <span className="plus">+</span>}<kbd className="kbd">{k}</kbd></React.Fragment>
      ))}
    </span>
  );
}

/* ---- speakers + sample transcripts ---- */
// Colors are AA-safe, per-theme speaker tokens (defined in colors_and_type.css):
// names + avatar initials must clear 4.5:1 at 11–12px on both paper and dark.
const SPEAKERS = {
  you:   { name: "You",   color: "var(--speaker-you)" },
  maya:  { name: "Maya",  color: "var(--speaker-maya)" },
  devin: { name: "Devin", color: "var(--speaker-devin)" },
};

// A long meeting (multi-speaker) and a short single-speaker note.
const MEETING = [
  { sp: "you",   t: 0,   text: "Okay, let's get started — quick recap of where we landed last week." },
  { sp: "maya",  t: 9,   text: "We're shipping the capture rewrite. Quick dictation and recording are one flow now." },
  { sp: "devin", t: 18,  text: "Right. Every capture is a note — short or long, the same object." },
  { sp: "you",   t: 27,  text: "Exactly. The microphone is the record button: press to start, press again to stop." },
  { sp: "maya",  t: 36,  text: "And it stays out of the way while we talk — the note just appears when we stop." },
  { sp: "devin", t: 46,  text: "It even keeps track of who said what, which saves me a lot of cleanup later." },
  { sp: "you",   t: 55,  text: "Let's keep the surface calm. No rail, no dashboard. The note is the product." },
  { sp: "maya",  t: 64,  text: "I'll wire the streaming progress and the expand-to-read view next." },
];
const SHORT = [
  { sp: "you", t: 0, text: "Remember to send the updated capture spec to Maya before Thursday, and book the review room for the afternoon." },
];

/* ---- helpers ---- */
function fmt(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`;
}
function tokens(script) {
  const out = [];
  script.forEach((ln, li) => ln.text.split(" ").forEach((w) => out.push({ sp: ln.sp, w, li })));
  return out;
}
// Build grouped {sp,text} lines from the first `ti` streamed word-tokens.
function getPartial(script, ti) {
  const tk = tokens(script).slice(0, ti);
  const groups = [];
  tk.forEach((x) => {
    const last = groups[groups.length - 1];
    if (last && last.li === x.li) last.text += " " + x.w;
    else groups.push({ sp: x.sp, li: x.li, text: x.w });
  });
  return groups;
}

Object.assign(window, { Mark, Icon, Keys, SPEAKERS, MEETING, SHORT, fmt, tokens, getPartial });
