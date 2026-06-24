// views.jsx — the only non-home surface left: the Notes list.
// Everything else that used to live behind the gear (Model, Push-to-talk,
// Hotwords, App update, Startup, Advanced, Status) was removed: the GUI is
// do-it-for-them, and all advanced config now lives in the `dictate config` CLI.
import { useState, useEffect, useMemo } from "react";
import { Icon } from "./icons.jsx";
import { useStore, formatHistoryTime } from "./store.jsx";

/* ============================== NOTES LIST + SEARCH ============================== */

// Highlight the first case-insensitive match of q inside text with a .hl span.
function hilite(text, q) {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text;
  return <>{text.slice(0, i)}<mark className="hl">{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

function HistoryView() {
  const s = useStore();
  const [q, setQ] = useState("");
  const [, tick] = useState(0);

  // Refresh relative timestamps every 15 s without a full re-render.
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 15000);
    return () => clearInterval(id);
  }, []);

  const all = s.history || [];
  const filtered = useMemo(() => {
    if (!q) return all;
    const sq = q.toLowerCase();
    return all.filter((n) => n.text.toLowerCase().includes(sq));
  }, [q, all]);

  // Open a history note in the ExpandedNote read view; back will return here.
  const openNote = (note) => {
    s.setCurrentNote(note);
    s.setExpandedFrom("history");
    s.setView("home");
    s.setNoteView("expanded");
  };

  const copyNote = (note) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(note.text)
        .then(() => s.toast("Copied to clipboard"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };

  const empty = all.length === 0;

  return (
    <div className="notes">
      {/* Own header: back → capture home, title. */}
      <div className="notes-top">
        <button className="ibtn" title="Back" onClick={() => s.setView("home")}>
          <Icon name="back" size={17} />
        </button>
        <div className="notes-title">Notes</div>
      </div>

      {/* Search field — autofocused, with ×-clear when non-empty */}
      <div className="notes-search">
        <Icon name="search" size={15} />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search notes"
          aria-label="Search notes"
        />
        {q && (
          <button className="ibtn sm" onClick={() => setQ("")} title="Clear search">
            <Icon name="x" size={15} />
          </button>
        )}
      </div>

      {/* Notes list — three states: empty-ever / no-results / rows */}
      <div className="notes-list">
        {empty ? (
          <div className="notes-blank">
            <span className="nb-ico"><Icon name="history" size={22} /></span>
            <div className="nb-title">Your notes will appear here</div>
            <div className="nb-sub">Every dictation is saved as a note you can search and reuse.</div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="notes-blank">
            <div className="nb-title">No notes match &ldquo;{q}&rdquo;.</div>
            <div className="nb-sub">Try a different word.</div>
          </div>
        ) : (
          filtered.map((note) => (
            <div
              className="note-row"
              key={note.id}
              role="button"
              tabIndex={0}
              onClick={() => openNote(note)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNote(note); } }}
            >
              <div className="nr-body">
                <div className="nr-text">{hilite(note.text, q)}</div>
                <div className="nr-meta t-mono">
                  <span>{formatHistoryTime(note.createdAt)}</span>
                </div>
              </div>
              <button
                className="ibtn nr-copy"
                title="Copy note"
                onClick={(e) => { e.stopPropagation(); copyNote(note); }}
              >
                <Icon name="copy" size={16} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export const VIEWS = {
  history: HistoryView,
};
