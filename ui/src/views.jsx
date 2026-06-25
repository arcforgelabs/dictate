// views.jsx — the only non-home surface left: the Notes list.
// Everything else that used to live behind the gear (Model, Push-to-talk,
// Hotwords, App update, Startup, Advanced, Status) was removed: the GUI is
// do-it-for-them, and all advanced config now lives in the `dictate config` CLI.
import { useState, useEffect, useMemo } from "react";
import { Icon } from "./icons.jsx";
import { useStore, formatHistoryTime } from "./store.jsx";
import { ipc } from "./ipc.js";

/* ============================== VIEW TOGGLE ============================== */

export function NotebookToggle() {
  const s = useStore();
  const active = s.view === "history";
  const inExpanded = s.noteView === "expanded";

  const closeExpanded = () => {
    s.setNoteView(null);
    s.setView(s.expandedFrom === "history" ? "history" : "home");
  };

  if (inExpanded) {
    return (
      <button
        type="button"
        className="view-toggle"
        aria-label="Close note"
        title="Close"
        onClick={closeExpanded}
      >
        <Icon name="x" size={17} />
      </button>
    );
  }

  return (
    <button
      type="button"
      className={"view-toggle" + (active ? " on" : "")}
      aria-label="Dictations"
      aria-pressed={active}
      title={active ? "Back to capture" : "Dictations"}
      onClick={() => {
        s.setNoteView(null);
        s.setView(active ? "home" : "history");
      }}
    >
      <Icon name="notebook" size={17} />
    </button>
  );
}

/** Shared top bar — same row geometry as `.notes-search` on the dictations view. */
export function HomeBar({ left, right }) {
  return (
    <div className="notes-search home-bar">
      {left}
      <span className="notes-search-grow" aria-hidden="true" />
      {right}
      <NotebookToggle />
    </div>
  );
}

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

  // Open a history note in the ExpandedNote read view.
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

  const exportNote = async (note) => {
    const ts = note.createdAt ? new Date(note.createdAt).toISOString().slice(0, 10) : "note";
    const name = `dictate-note-${ts}.md`;
    const md = `# Note — ${ts}\n\n${note.text}\n`;
    try {
      const saved = await ipc.saveTextFile(name, md);
      if (saved) s.toast("Saved as Markdown");
    } catch {
      s.toast("Could not save file", { bad: true });
    }
  };

  const empty = all.length === 0;

  return (
    <div className="notes">
      <div className="notes-search">
        <Icon name="search" size={15} />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search dictations"
          aria-label="Search dictations"
        />
        {q && (
          <button className="ibtn sm" onClick={() => setQ("")} title="Clear search">
            <Icon name="x" size={15} />
          </button>
        )}
        <NotebookToggle />
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
                className="ibtn nr-action"
                title="Copy note"
                onClick={(e) => { e.stopPropagation(); copyNote(note); }}
              >
                <Icon name="copy" size={16} />
              </button>
              <button
                className="ibtn nr-action"
                title="Export as Markdown"
                onClick={(e) => { e.stopPropagation(); exportNote(note); }}
              >
                <Icon name="download" size={16} />
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
