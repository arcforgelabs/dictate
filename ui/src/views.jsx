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
    s.setView("home");
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
      aria-label={active ? "Back to capture" : "Dictations"}
      aria-pressed={active}
      title={active ? "Back to capture" : "Dictations"}
      onClick={() => {
        s.setNoteView(null);
        s.setView(active ? "home" : "history");
      }}
    >
      <Icon name={active ? "x" : "notebook"} size={17} />
    </button>
  );
}

/** Shared top bar — same row geometry as `.notes-search` on the dictations view. */
export function HomeBar({ left, right, meeting }) {
  return (
    <div className="notes-search home-bar">
      {left}
      <span className="notes-search-grow" aria-hidden="true" />
      {right}
      {meeting}
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

function fmtSecs(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`;
}

function normalizeSegments(segments) {
  if (!Array.isArray(segments)) return [];
  return segments
    .map((segment, index) => {
      const text = typeof segment?.text === "string" ? segment.text.trim() : "";
      if (!text) return null;
      const tStart = Number.isFinite(Number(segment.tStart))
        ? Number(segment.tStart)
        : Number.isFinite(Number(segment.t_start))
          ? Number(segment.t_start)
          : null;
      const tEnd = Number.isFinite(Number(segment.tEnd))
        ? Number(segment.tEnd)
        : Number.isFinite(Number(segment.t_end))
          ? Number(segment.t_end)
          : null;
      return {
        seq: Number.isFinite(Number(segment.seq)) ? Number(segment.seq) : index,
        tStart,
        tEnd,
        text,
        speakerId: segment.speakerId || segment.speaker_id || null,
        speakerLabel: segment.speakerLabel || segment.speaker_label || null,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.seq - b.seq);
}

function notePlainText(note) {
  const segments = normalizeSegments(note?.segments);
  if (!segments.length) return typeof note?.text === "string" ? note.text : "";
  return segments
    .map((segment) => {
      const label = segment.speakerLabel || segment.speakerId;
      return label ? `${label}: ${segment.text}` : segment.text;
    })
    .join("\n");
}

function noteSearchText(note) {
  const pieces = [typeof note?.text === "string" ? note.text : ""];
  for (const segment of normalizeSegments(note?.segments)) {
    pieces.push(segment.text);
    if (segment.speakerLabel) pieces.push(segment.speakerLabel);
    if (segment.speakerId) pieces.push(segment.speakerId);
    if (Number.isFinite(segment.tStart)) pieces.push(fmtSecs(segment.tStart));
    if (Number.isFinite(segment.tEnd)) pieces.push(fmtSecs(segment.tEnd));
  }
  return pieces.join(" ").toLowerCase();
}

function noteMarkdown(note, titleDate) {
  const segments = normalizeSegments(note?.segments);
  if (!segments.length) return `# Note - ${titleDate}\n\n${notePlainText(note)}\n`;
  const lines = [`# Note - ${titleDate}`, ""];
  for (const segment of segments) {
    const label = segment.speakerLabel || segment.speakerId || "Transcript";
    const hasStart = Number.isFinite(segment.tStart);
    const hasEnd = Number.isFinite(segment.tEnd);
    const time = hasStart && hasEnd
      ? ` [${fmtSecs(segment.tStart)}-${fmtSecs(segment.tEnd)}]`
      : hasStart
        ? ` [${fmtSecs(segment.tStart)}]`
        : "";
    lines.push(`**${label}${time}:** ${segment.text}`);
  }
  return `${lines.join("\n\n")}\n`;
}

function HistoryView() {
  const s = useStore();
  const [q, setQ] = useState("");
  // Category filter (Phase 1): all | meetings | quick. View-only; capture is unchanged.
  const [cat, setCat] = useState("all");
  const [, tick] = useState(0);

  // Refresh relative timestamps every 15 s without a full re-render.
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 15000);
    return () => clearInterval(id);
  }, []);

  const all = s.history || [];
  // Prefer the persisted mode; segments remain a compatibility fallback for older records.
  const isMeeting = (n) => n?.mode === "meeting"
    || (n?.mode == null && Array.isArray(n?.segments) && n.segments.length > 0);
  const byCat = useMemo(() => {
    if (cat === "meetings") return all.filter(isMeeting);
    if (cat === "quick") return all.filter((n) => !isMeeting(n));
    return all;
  }, [all, cat]);
  const filtered = useMemo(() => {
    if (!q) return byCat;
    const sq = q.toLowerCase();
    return byCat.filter((n) => noteSearchText(n).includes(sq));
  }, [q, byCat]);

  // Open a history note in the ExpandedNote read view.
  const openNote = (note) => {
    s.setCurrentNote(note);
    s.setExpandedFrom("history");
    s.setView("home");
    s.setNoteView("expanded");
  };

  const copyNote = (note) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(notePlainText(note))
        .then(() => s.toast("Copied to clipboard"))
        .catch(() => s.toast("Could not copy", { bad: true }));
    }
  };

  const exportNote = async (note) => {
    const ts = note.createdAt ? new Date(note.createdAt).toISOString().slice(0, 10) : "note";
    const name = `dictate-note-${ts}.md`;
    const md = noteMarkdown(note, ts);
    try {
      const saved = await ipc.saveTextFile(name, md);
      if (saved) s.toast("Saved as Markdown");
    } catch {
      s.toast("Could not save file", { bad: true });
    }
  };

  const archiveNote = (note) => {
    if (!note?.id) return;
    s.archiveNote(note);
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
        <div className="engine-seg cat-seg" role="group" aria-label="Filter dictations">
          {[["all", "All"], ["meetings", "Meetings"], ["quick", "Quick"]].map(([c, label]) => (
            <button
              key={c}
              type="button"
              className={"engine-opt" + (cat === c ? " on" : "")}
              aria-pressed={cat === c}
              onClick={() => setCat(c)}
            >
              {label}
            </button>
          ))}
        </div>
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
            {q ? (
              <>
                <div className="nb-title">No notes match &ldquo;{q}&rdquo;.</div>
                <div className="nb-sub">Try a different word.</div>
              </>
            ) : (
              <>
                <div className="nb-title">{cat === "meetings" ? "No meetings yet." : "No quick records yet."}</div>
                <div className="nb-sub">
                  {cat === "meetings"
                    ? "Meetings you record will appear here."
                    : "Quick dictations will appear here."}
                </div>
              </>
            )}
          </div>
        ) : (
          filtered.map((note) => (
            <div
              className={"note-row" + (s.leavingNoteIds?.includes(note.id) ? " note-row-leave" : "")}
              key={note.id}
              role="button"
              tabIndex={0}
              onClick={() => openNote(note)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openNote(note); } }}
            >
              <div className="nr-body">
                <div className="nr-text">{hilite(notePlainText(note), q)}</div>
                <div className="nr-meta t-mono">
                  <span>{formatHistoryTime(note.createdAt)}</span>
                </div>
              </div>
              <div className="nr-actions">
                <button
                  className="ibtn nr-action"
                  title="Archive note"
                  onClick={(e) => { e.stopPropagation(); archiveNote(note); }}
                >
                  <Icon name="archive" size={16} />
                </button>
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
