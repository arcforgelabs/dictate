// icons.jsx — Lucide-style line glyphs (currentColor, 1.75). Ported to ES modules.
import React from "react";

const ICONS = {
  mic: <><path d="M12 2.5a2.6 2.6 0 0 0-2.6 2.6v6a2.6 2.6 0 0 0 5.2 0v-6A2.6 2.6 0 0 0 12 2.5Z"/><path d="M18 11v.6a6 6 0 0 1-12 0V11"/><path d="M12 17.6V21M8.5 21h7"/></>,
  status: <path d="M3 12h4l2.5 6 5-13 2 7H21"/>,
  sliders: <><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2.2"/><circle cx="8" cy="17" r="2.2"/></>,
  keyboard: <><rect x="3" y="6" width="18" height="12" rx="2.5"/><path d="M7 10h.01M11 10h.01M15 10h.01M17 14H7"/></>,
  hash: <path d="M5 9h14M5 15h14M10 4 8 20M16 4l-2 16"/>,
  clock: <><circle cx="12" cy="12" r="8.5"/><path d="M12 8v4.2l2.8 1.8"/></>,
  power: <><path d="M12 4v7"/><path d="M7.4 7.4a7 7 0 1 0 9.2 0"/></>,
  gear: <><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></>,
  chev: <path d="M9 6l6 6-6 6"/>,
  chevd: <path d="M6 9l6 6 6-6"/>,
  back: <path d="M15 6l-6 6 6 6"/>,
  check: <path d="M5 12.5l4.5 4.5L19 7"/>,
  copy: <><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/></>,
  device: <><rect x="4" y="4" width="16" height="11" rx="2"/><path d="M8 20h8M12 15v5"/></>,
  laptop: <path d="M20 16V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9m16 0H4m16 0 1.28 2.55a1 1 0 0 1-.9 1.45H3.62a1 1 0 0 1-.9-1.45L4 16"/>,
  key: <><circle cx="8" cy="12" r="3.2"/><path d="M11.2 12H20l-2 2.4M16 12v3"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  x: <path d="M6 6l12 12M18 6 6 18"/>,
  minus: <path d="M5 12h14"/>,
  square: <rect x="5" y="5" width="14" height="14" rx="1.5"/>,
  record: <circle cx="12" cy="12" r="7" fill="currentColor"/>,
  pause: <><rect x="7" y="5" width="4" height="14" rx="1"/><rect x="13" y="5" width="4" height="14" rx="1"/></>,
  play: <path d="M8 5.8v12.4c0 .9 1 1.4 1.7.9l10.2-6.2c.7-.4.7-1.4 0-1.8L9.7 4.9A1 1 0 0 0 8 5.8z"/>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/></>,
  cpu: <><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 9.5h5v5h-5z"/><path d="M9 3v2M15 3v2M9 19v2M15 19v2M3 9h2M3 15h2M19 9h2M19 15h2"/></>,
  bolt: <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"/>,
  refresh: <><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></>,
  trash: <><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13"/></>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M18.4 5.6l1.4-1.4M4.2 19.8l1.4-1.4"/></>,
  moon: <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>,
  wave: <path d="M3 12h2l2-7 4 16 3-12 2 5h5"/>,
  shield: <><path d="M12 3 5 6v5c0 4.5 3 7.7 7 9 4-1.3 7-4.5 7-9V6l-7-3z"/><path d="M9.5 12l1.8 1.8 3.5-3.6"/></>,
  pin: <><path d="M12 21s7-5.5 7-11a7 7 0 0 0-14 0c0 5.5 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/></>,
  history: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 8v4.5l3 1.7"/></>,
  notebook: <><path d="M2 6h4"/><path d="M2 10h4"/><path d="M2 14h4"/><path d="M2 18h4"/><rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9.5 8h5"/><path d="M9.5 12H16"/><path d="M9.5 16H14"/></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></>,
  download: <><path d="M12 3v12M7 11l5 4 5-4"/><path d="M5 20h14"/></>,
  archive: <><rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/></>,
  more: <><circle cx="5" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="19" cy="12" r="1.2" fill="currentColor"/></>,
  lock: <><rect x="5" y="11" width="14" height="11" rx="2.5"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></>,
  external: <><path d="M18 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></>,
  cloud: <path d="M17.5 19H8a5.5 5.5 0 1 1 .5-10.9A5 5 0 0 1 17.5 19z"/>,
  cloudoff: <><path d="m2 2 20 20"/><path d="M5.6 5.6A7 7 0 0 0 9 19h8.5a4.5 4.5 0 0 0 1.3-8.8M15.6 3.1A5 5 0 0 1 20.5 8c0 .25-.02.5-.05.75"/></>,
};

export function Icon({ name, size = 18, style, cls }) {
  const p = ICONS[name];
  return (
    <svg className={cls} width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
      style={{ flex: "0 0 auto", display: "block", ...style }}>{p}</svg>
  );
}

export const ArcMark = () => (
  <svg viewBox="18 8 84 84" fill="none" style={{ width: "100%", height: "100%" }}>
    <rect x="47" y="16" width="26" height="48" rx="13" fill="currentColor" />
    <path d="M28 48 A32 32 0 0 0 92 48" fill="none" stroke="currentColor" strokeWidth="8" strokeLinecap="round" />
  </svg>
);

/* Canonical cradle-mic mark — identical geometry to assets/dictate.svg.
   Two shapes only: capsule (mic body) + open cradle arc. No stem, no base.
   Used in the capture button (BreathCradle) and the header brand. */
export function Mark({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="18 8 84 84" fill="none" aria-label="Dictate">
      <rect x="47" y="16" width="26" height="48" rx="13" fill="currentColor" />
      <path d="M28 48A32 32 0 0 0 92 48" fill="none" stroke="currentColor" strokeWidth="8" strokeLinecap="round" />
    </svg>
  );
}
