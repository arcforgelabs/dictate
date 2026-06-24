import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within, cleanup, waitFor, act } from "@testing-library/react";
import App from "../App.jsx";

afterEach(() => {
  cleanup();
  delete window.__DICTATE__;
  delete window.EventSource;
  vi.restoreAllMocks();
});

// Navigate to a settings view via the ⌘K command palette.
// The palette opens with Ctrl+K, we type the label to filter to one item,
// then press Enter to execute. The palette closes and the view renders.
function navTo(label) {
  fireEvent.keyDown(window, { ctrlKey: true, key: "k", bubbles: true });
  const input = screen.getByPlaceholderText(/Search notes/i);
  fireEvent.change(input, { target: { value: label } });
  fireEvent.keyDown(input, { key: "Enter" });
}

describe("Quiet Console app (mock mode)", () => {
  it("renders the capture (mic) home by default", () => {
    render(<App />);
    // Home is the capture surface: the cradle mic, ready status, and a Notes button.
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Ready to capture")).toBeInTheDocument();
    expect(screen.getByTitle("Notes")).toBeInTheDocument();
  });

  it("has no settings gear — config lives in the dictate config CLI", () => {
    render(<App />);
    expect(screen.queryByTitle("Settings")).not.toBeInTheDocument();
    // The one survivor on the home is the privacy pill.
    expect(screen.getByText("On-device · private")).toBeInTheDocument();
  });

  it("back button returns to the capture home from the Notes view", () => {
    render(<App />);
    navTo("Notes");
    expect(screen.getByPlaceholderText("Search notes")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Back"));
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Ready to capture")).toBeInTheDocument();
  });

  it("toggles the theme via the command palette", () => {
    render(<App />);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    navTo("Switch to dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("wears GNOME chrome by default (close-only control)", () => {
    const { container } = render(<App />);
    expect(container.querySelector(".win")).toHaveClass("gnome");
    expect(container.querySelector(".adw")).toBeInTheDocument();
    expect(container.querySelector(".wincaps")).toBeNull();
  });

  it("opens the command palette with the title-bar search", () => {
    render(<App />);
    fireEvent.click(screen.getByText("Search notes & actions"));
    expect(screen.getByPlaceholderText(/Search notes/i)).toBeInTheDocument();
  });

  it("shows Transcribing… then note-ready surface after a mock capture", async () => {
    render(<App />);
    // Start recording
    fireEvent.click(screen.getByLabelText("Start recording"));
    expect(screen.getByLabelText("Stop recording")).toBeInTheDocument();
    // Stop recording — transitions to "Transcribing…"
    fireEvent.click(screen.getByLabelText("Stop recording"));
    expect(screen.getByText("Transcribing…")).toBeInTheDocument();
    // After the 800 ms mock delay the note-ready surface appears
    await waitFor(() => expect(screen.getByText("Insert")).toBeInTheDocument(), { timeout: 2000 });
    // CTA hierarchy: Insert primary, Open note, New note
    expect(screen.getByText("Open note")).toBeInTheDocument();
    expect(screen.getByText("New note")).toBeInTheDocument();
    // The note text from the mock is visible
    expect(screen.getByText(/project note/i)).toBeInTheDocument();
  });

  it("opens the expanded note from note-ready and returns with back", async () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("Start recording"));
    fireEvent.click(screen.getByLabelText("Stop recording"));
    // Wait for note-ready
    await waitFor(() => expect(screen.getByText("Open note")).toBeInTheDocument(), { timeout: 2000 });
    fireEvent.click(screen.getByText("Open note"));
    // Expanded: back button present, note text present
    expect(screen.getByTitle("Back")).toBeInTheDocument();
    const backBtn = screen.getByTitle("Back");
    fireEvent.click(backBtn);
    // Returns to note-ready
    expect(screen.getByText("Insert")).toBeInTheDocument();
  });

  it("New note returns to the capture home", async () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("Start recording"));
    fireEvent.click(screen.getByLabelText("Stop recording"));
    await waitFor(() => expect(screen.getByText("New note")).toBeInTheDocument(), { timeout: 2000 });
    fireEvent.click(screen.getByText("New note"));
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Ready to capture")).toBeInTheDocument();
  });

  it("resolves Transcribing… back to home on note status=empty (live SSE)", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    // Engine fires note-recording(false) → UI shows Transcribing…
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "note-recording", active: false }),
      });
    });
    expect(screen.getByText("Transcribing…")).toBeInTheDocument();

    // Engine fires note event with status="empty" (no speech detected)
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "note", text: "", status: "empty" }),
      });
    });

    // Must leave Transcribing… and return to capture home
    await waitFor(() => expect(screen.queryByText("Transcribing…")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
  });

  it("resolves Transcribing… back to home on note status=failed (live SSE)", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    act(() => {
      sources[0].onmessage({ data: JSON.stringify({ type: "note-recording", active: false }) });
    });
    expect(screen.getByText("Transcribing…")).toBeInTheDocument();

    act(() => {
      sources[0].onmessage({ data: JSON.stringify({ type: "note", text: "", status: "failed" }) });
    });

    await waitFor(() => expect(screen.queryByText("Transcribing…")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
  });

  it("resolves Transcribing… back to home when stale transcript arrives while processing (live SSE)", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    act(() => {
      sources[0].onmessage({ data: JSON.stringify({ type: "note-recording", active: false }) });
    });
    expect(screen.getByText("Transcribing…")).toBeInTheDocument();

    // _fail_recording_session fires a stale transcript event (belt-and-suspenders)
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "transcript", phase: "final", text: "", stale: true }),
      });
    });

    await waitFor(() => expect(screen.queryByText("Transcribing…")).not.toBeInTheDocument());
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
  });

  it("fires exactly one toast when _fail_recording_session sends stale+note-failed (P3.1)", async () => {
    // Regression test: stale transcript AND note status="failed" both arrive (normal on fail path).
    // The stale branch must resolve silently; only the note "failed" branch toasts.
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    // Recording stops → processing
    act(() => {
      sources[0].onmessage({ data: JSON.stringify({ type: "note-recording", active: false }) });
    });
    expect(screen.getByText("Transcribing…")).toBeInTheDocument();

    // _fail_recording_session fires stale transcript THEN note{failed}
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "transcript", phase: "final", text: "", stale: true }),
      });
    });
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "note", text: "", status: "failed" }),
      });
    });

    // Exactly one "Couldn't transcribe" toast — no duplicate
    await waitFor(() =>
      expect(screen.getAllByText(/Couldn't transcribe/i)).toHaveLength(1)
    );
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
  });

  it("clears live transcript text when a stale transcript event arrives", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() {
        sources.push(this);
      }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    sources[0].onmessage({
      data: JSON.stringify({ type: "transcript", phase: "partial", text: "speculative words", stale: false }),
    });
    expect(await screen.findByText("speculative words")).toBeInTheDocument();

    sources[0].onmessage({
      data: JSON.stringify({ type: "transcript", phase: "final", text: "", stale: true }),
    });

    await waitFor(() => expect(screen.queryByText("speculative words")).not.toBeInTheDocument());
  });

  it("ignores delayed stale transcript events from older recording ids", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() {
        sources.push(this);
      }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    sources[0].onmessage({
      data: JSON.stringify({
        type: "transcript",
        phase: "partial",
        text: "new recording words",
        stale: false,
        recording_id: 2,
      }),
    });
    expect(await screen.findByText("new recording words")).toBeInTheDocument();

    sources[0].onmessage({
      data: JSON.stringify({ type: "transcript", phase: "final", text: "", stale: true, recording_id: 1 }),
    });

    expect(await screen.findByText("new recording words")).toBeInTheDocument();
  });

  it("newer stale transcript events suppress older delayed partials", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() {
        sources.push(this);
      }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    sources[0].onmessage({
      data: JSON.stringify({ type: "transcript", phase: "final", text: "", stale: true, recording_id: 3 }),
    });
    sources[0].onmessage({
      data: JSON.stringify({
        type: "transcript",
        phase: "partial",
        text: "older delayed words",
        stale: false,
        recording_id: 2,
      }),
    });

    await waitFor(() => expect(screen.queryByText("older delayed words")).not.toBeInTheDocument());
  });

  it("same recording delayed partial does not reappear after stale final", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() {
        sources.push(this);
      }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    sources[0].onmessage({
      data: JSON.stringify({
        type: "transcript",
        phase: "partial",
        text: "same recording speculative",
        stale: false,
        recording_id: 4,
      }),
    });
    expect(await screen.findByText("same recording speculative")).toBeInTheDocument();

    sources[0].onmessage({
      data: JSON.stringify({ type: "transcript", phase: "final", text: "", stale: true, recording_id: 4 }),
    });
    await waitFor(() => expect(screen.queryByText("same recording speculative")).not.toBeInTheDocument());

    sources[0].onmessage({
      data: JSON.stringify({
        type: "transcript",
        phase: "partial",
        text: "same recording delayed",
        stale: false,
        recording_id: 4,
      }),
    });

    await waitFor(() => expect(screen.queryByText("same recording delayed")).not.toBeInTheDocument());
  });

  it("accepts low transcript ids after a recording id reset window", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() {
        sources.push(this);
      }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    sources[0].onmessage({
      data: JSON.stringify({ type: "transcript", phase: "final", text: "", stale: true, recording_id: 80 }),
    });
    sources[0].onmessage({
      data: JSON.stringify({
        type: "transcript",
        phase: "partial",
        text: "fresh session words",
        stale: false,
        recording_id: 1,
      }),
    });

    expect(await screen.findByText("fresh session words")).toBeInTheDocument();
  });
});

/* =====================================================================
   Feature: Notes list + search (reachable from the capture home)
   ===================================================================== */
describe("Notes list (history view)", () => {
  it("renders the Notes list with search field", () => {
    render(<App />);
    navTo("Notes");
    expect(screen.getByText("Notes", { selector: ".notes-title" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search notes")).toBeInTheDocument();
  });

  it("shows all three mock notes in the list", () => {
    render(<App />);
    navTo("Notes");
    expect(screen.getByText(/Stalwart/i)).toBeInTheDocument();
    expect(screen.getByText(/sync to Thursday/i)).toBeInTheDocument();
    expect(screen.getByText(/beta testers/i)).toBeInTheDocument();
  });

  it("search filters notes by text", () => {
    render(<App />);
    navTo("Notes");
    const input = screen.getByPlaceholderText("Search notes");
    fireEvent.change(input, { target: { value: "Stalwart" } });
    // Matching note visible
    expect(screen.getByText(/Stalwart/i)).toBeInTheDocument();
    // Non-matching notes absent
    expect(screen.queryByText(/beta testers/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sync to Thursday/i)).not.toBeInTheDocument();
  });

  it("shows no-results state when search has no matches", () => {
    render(<App />);
    navTo("Notes");
    const input = screen.getByPlaceholderText("Search notes");
    fireEvent.change(input, { target: { value: "xyzzy" } });
    expect(screen.getByText(/No notes match/i)).toBeInTheDocument();
  });

  it("clear button removes the search query and shows all notes again", () => {
    render(<App />);
    navTo("Notes");
    const input = screen.getByPlaceholderText("Search notes");
    fireEvent.change(input, { target: { value: "Stalwart" } });
    expect(screen.queryByText(/beta testers/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Clear search"));
    expect(screen.getByText(/beta testers/i)).toBeInTheDocument();
  });

  it("tapping a note row opens it in the expanded view", () => {
    render(<App />);
    navTo("Notes");
    // Click the Stalwart note row (its text bubbles the click up to note-row)
    fireEvent.click(screen.getByText(/Stalwart/i));
    // Should now be in the ExpandedNote view
    expect(screen.getByTitle("Back")).toBeInTheDocument();
    // The note text appears in the expanded body
    expect(screen.getByText(/Stalwart/i)).toBeInTheDocument();
  });

  it("Space key on a note row opens it in the expanded view (role=button a11y)", () => {
    render(<App />);
    navTo("Notes");
    // Find the note-row div via its role="button" that contains the Stalwart text
    const noteRow = screen.getByText(/Stalwart/i).closest('[role="button"]');
    fireEvent.keyDown(noteRow, { key: " " });
    expect(screen.getByTitle("Back")).toBeInTheDocument();
    expect(screen.getByText(/Stalwart/i)).toBeInTheDocument();
  });

  it("back from expanded note (opened from notes list) returns to the notes list", () => {
    render(<App />);
    navTo("Notes");
    fireEvent.click(screen.getByText(/Stalwart/i));
    // In expanded view; click Back
    fireEvent.click(screen.getByTitle("Back"));
    // Should be back at the notes list
    expect(screen.getByPlaceholderText("Search notes")).toBeInTheDocument();
    expect(screen.getByText("Notes", { selector: ".notes-title" })).toBeInTheDocument();
  });

  it("back from expanded note (opened from note-ready) still returns to note-ready", async () => {
    render(<App />);
    // Do a mock capture to get to note-ready
    fireEvent.click(screen.getByLabelText("Start recording"));
    fireEvent.click(screen.getByLabelText("Stop recording"));
    await waitFor(() => expect(screen.getByText("Open note")).toBeInTheDocument(), { timeout: 2000 });
    // Open expanded from note-ready
    fireEvent.click(screen.getByText("Open note"));
    expect(screen.getByTitle("Back")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Back"));
    // Back at note-ready, not notes list
    expect(screen.getByText("Insert")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Search notes")).not.toBeInTheDocument();
  });
});

/* =====================================================================
   Feature: Provider resilience — graceful degradation (Bundle C Part 3)
   Recording is NEVER hard-blocked. On-device is the always-available floor.
   ===================================================================== */
describe("Provider resilience — graceful degradation", () => {
  it("shows the capture home by default with mic always enabled", () => {
    render(<App />);
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Ready to capture")).toBeInTheDocument();
    // BlockedHome is gone — these strings must never appear
    expect(screen.queryByText("Online transcription isn't working")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Recording blocked — provider unhealthy")).not.toBeInTheDocument();
  });

  it("mic is NOT disabled by provider state — online+unhealthy still shows Start recording", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        history: [],
        providerHealth: { healthy: false, status: "auth", mode: "online", degraded: true, reason: "auth", active: "faster-whisper" },
        providers: { xai: { configured: true, status: "Ready" } },
      }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    // After hydration with degraded state, the mic button must still be enabled
    await waitFor(() => expect(screen.getByLabelText("Start recording")).toBeInTheDocument());
    expect(screen.queryByText("Online transcription isn't working")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Recording blocked — provider unhealthy")).not.toBeInTheDocument();
  });

  it("provider-degraded SSE triggers amber toast and degraded strip during recording", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    // Start recording via SSE note-recording event
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "note-recording", active: true }),
      });
    });
    expect(screen.getByLabelText("Stop recording")).toBeInTheDocument();

    // Fire provider-degraded SSE
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "provider-degraded", preferred: "xai", active: "faster-whisper", reason: "unreachable" }),
      });
    });

    // Amber toast: "Switched to on-device"
    await waitFor(() =>
      expect(screen.getByText(/Switched to on-device/i)).toBeInTheDocument()
    );

    // Degraded strip shows during recording
    expect(screen.getByText(/On-device · reconnecting…/)).toBeInTheDocument();

    // Mic remains functional (recording still active)
    expect(screen.getByLabelText("Stop recording")).toBeInTheDocument();
  });

  it("provider-recovered SSE clears degraded state and shows recovery toast", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [] }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    // First degrade
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "provider-degraded", preferred: "xai", active: "faster-whisper", reason: "unreachable" }),
      });
    });
    await waitFor(() => expect(screen.getByText(/Switched to on-device/i)).toBeInTheDocument());

    // Then recover
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "provider-recovered", preferred: "xai", active: "xai" }),
      });
    });

    // Recovery toast appears
    await waitFor(() => expect(screen.getByText(/Back online/)).toBeInTheDocument());
    // Home screen is still reachable (mic not disabled)
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
  });

  it("degraded strip renders when hydrated with providerDegraded=true and recording starts", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        history: [],
        providerHealth: { healthy: false, status: "unreachable", mode: "online", degraded: true, reason: "unreachable", active: "faster-whisper" },
      }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    // Start recording via SSE (providerDegraded is already true from hydration)
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "note-recording", active: true }),
      });
    });

    await waitFor(() =>
      expect(screen.getByText(/On-device · reconnecting…/)).toBeInTheDocument()
    );
    expect(screen.getByLabelText("Stop recording")).toBeInTheDocument();
  });
});
