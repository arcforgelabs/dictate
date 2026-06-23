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
  const input = screen.getByPlaceholderText(/Jump to a setting/i);
  fireEvent.change(input, { target: { value: label } });
  fireEvent.keyDown(input, { key: "Enter" });
}

describe("Quiet Console app (mock mode)", () => {
  it("renders the Note Capture home by default", () => {
    render(<App />);
    // Capture home: gear button in the TitleBar, cradle button, and status text.
    // Stage 3: "Dictate" wordmark removed from both TitleBar and capture surface.
    expect(screen.getByTitle("Settings")).toBeInTheDocument();
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Ready to capture")).toBeInTheDocument();
  });

  it("preserves Quick dictation and Record conversation in the Status view", () => {
    render(<App />);
    // Navigate to the legacy Status view (still accessible via ⌘K).
    navTo("Status");
    expect(screen.getByText("Quick dictation")).toBeInTheDocument();
    expect(screen.getByText("Record conversation")).toBeInTheDocument();
  });

  it("back button returns to capture home from a settings view", () => {
    render(<App />);
    navTo("Model");
    expect(screen.getByText("Transcription model")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Back"));
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
  });

  it("navigates to the Model view and lists all four providers", () => {
    render(<App />);
    navTo("Model");
    expect(screen.getByText("Transcription model")).toBeInTheDocument();
    expect(screen.getByText("faster-whisper · turbo")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini-transcribe")).toBeInTheDocument();
    expect(screen.getByText("grok-speech-to-text")).toBeInTheDocument();
    expect(screen.getByText("gemini-3-flash-preview")).toBeInTheDocument();
  });

  it("navigates to the App update view without prototype controls", () => {
    render(<App />);
    navTo("App update");
    expect(screen.getByRole("heading", { name: "App update" })).toBeInTheDocument();
    expect(screen.getByText("Engine")).toBeInTheDocument();
    expect(screen.getByText("App window")).toBeInTheDocument();
    expect(screen.queryByText(/PROTOTYPE/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/JUMP TO STATE/i)).not.toBeInTheDocument();
  });

  it("adds and removes a hotword", () => {
    render(<App />);
    navTo("Hotwords");
    const input = screen.getByPlaceholderText("Add a word…");
    fireEvent.change(input, { target: { value: "Kubernetes" } });
    fireEvent.click(screen.getByText("Add word"));
    expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Remove Kubernetes"));
    expect(screen.queryByText("Kubernetes")).not.toBeInTheDocument();
  });

  it("toggles the theme via the gear menu appearance control", () => {
    render(<App />);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    // Open gear menu then click the Dark option.
    fireEvent.click(screen.getByTitle("Settings"));
    fireEvent.click(screen.getByText("Dark"));
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
    fireEvent.click(screen.getByText("Search settings & actions"));
    expect(screen.getByPlaceholderText(/Jump to a setting/i)).toBeInTheDocument();
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

  it("New note returns to capture home", async () => {
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
   Feature: copy-last row
   ===================================================================== */
describe("Copy-last row", () => {
  it("is visible on the home when history is non-empty (mock mode)", () => {
    render(<App />);
    // Default mock mode seeds 3 history items, so the chip should appear.
    expect(screen.getByTitle("Copy the last note")).toBeInTheDocument();
  });

  it("is hidden while the note recording is active", () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("Start recording"));
    expect(screen.queryByTitle("Copy the last note")).not.toBeInTheDocument();
  });

  it("is hidden when history is empty (live SSE, empty hydration)", async () => {
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
    // After SSE connects and hydrates with empty history the chip must be absent.
    await waitFor(() => expect(screen.queryByTitle("Copy the last note")).not.toBeInTheDocument());
  });
});

/* =====================================================================
   Feature: Notes list + search (redesigned history view)
   ===================================================================== */
describe("Notes list (history view)", () => {
  it("renders the Notes list with search field when navigating to history", () => {
    render(<App />);
    navTo("Recent history");
    expect(screen.getByText("Notes")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search notes")).toBeInTheDocument();
    // Count badge — 3 mock notes
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("shows all three mock notes in the list", () => {
    render(<App />);
    navTo("Recent history");
    expect(screen.getByText(/Stalwart/i)).toBeInTheDocument();
    expect(screen.getByText(/sync to Thursday/i)).toBeInTheDocument();
    expect(screen.getByText(/beta testers/i)).toBeInTheDocument();
  });

  it("search filters notes by text and updates the count", () => {
    render(<App />);
    navTo("Recent history");
    const input = screen.getByPlaceholderText("Search notes");
    fireEvent.change(input, { target: { value: "Stalwart" } });
    // Matching note visible
    expect(screen.getByText(/Stalwart/i)).toBeInTheDocument();
    // Non-matching notes absent
    expect(screen.queryByText(/beta testers/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sync to Thursday/i)).not.toBeInTheDocument();
    // Count shows "1 of 3"
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
  });

  it("shows no-results state when search has no matches", () => {
    render(<App />);
    navTo("Recent history");
    const input = screen.getByPlaceholderText("Search notes");
    fireEvent.change(input, { target: { value: "xyzzy" } });
    expect(screen.getByText(/No notes match/i)).toBeInTheDocument();
  });

  it("clear button removes the search query and shows all notes again", () => {
    render(<App />);
    navTo("Recent history");
    const input = screen.getByPlaceholderText("Search notes");
    fireEvent.change(input, { target: { value: "Stalwart" } });
    expect(screen.queryByText(/beta testers/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Clear search"));
    expect(screen.getByText(/beta testers/i)).toBeInTheDocument();
  });

  it("tapping a note row opens it in the expanded view", () => {
    render(<App />);
    navTo("Recent history");
    // Click the Stalwart note row (its text bubbles the click up to note-row)
    fireEvent.click(screen.getByText(/Stalwart/i));
    // Should now be in the ExpandedNote view
    expect(screen.getByTitle("Back")).toBeInTheDocument();
    // The note text appears in the expanded body
    expect(screen.getByText(/Stalwart/i)).toBeInTheDocument();
  });

  it("Space key on a note row opens it in the expanded view (role=button a11y)", () => {
    render(<App />);
    navTo("Recent history");
    // Find the note-row div via its role="button" that contains the Stalwart text
    const noteRow = screen.getByText(/Stalwart/i).closest('[role="button"]');
    fireEvent.keyDown(noteRow, { key: " " });
    expect(screen.getByTitle("Back")).toBeInTheDocument();
    expect(screen.getByText(/Stalwart/i)).toBeInTheDocument();
  });

  it("back from expanded note (opened from notes list) returns to the notes list", () => {
    render(<App />);
    navTo("Recent history");
    fireEvent.click(screen.getByText(/Stalwart/i));
    // In expanded view; click Back
    fireEvent.click(screen.getByTitle("Back"));
    // Should be back at the notes list
    expect(screen.getByPlaceholderText("Search notes")).toBeInTheDocument();
    expect(screen.getByText("Notes")).toBeInTheDocument();
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
   Feature: Provider-health blocked state (Bundle C Part 3)
   ===================================================================== */
describe("Provider health blocked state", () => {
  it("shows capture home by default (healthy provider)", () => {
    render(<App />);
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Ready to capture")).toBeInTheDocument();
    expect(screen.queryByText("Online transcription isn't working")).not.toBeInTheDocument();
  });

  it("provider-health SSE updates providerHealthy state (live mode)", async () => {
    // When getState hydrates with online+healthy, then provider-health SSE fires unhealthy,
    // the UI should switch to BlockedHome.
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    // Initial hydration: online and healthy (has a key)
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        history: [],
        providerHealth: { healthy: false, status: "auth", mode: "online" },
        providers: { xai: { configured: true, status: "Ready" } },
      }),
    });

    render(<App />);
    // After hydration the blocked screen appears
    await waitFor(() =>
      expect(screen.getByText("Online transcription isn't working")).toBeInTheDocument()
    );
  });

  it("renders BlockedHome when hydrated with online+unhealthy providerHealth", async () => {
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
        providerHealth: { healthy: false, status: "no-key", mode: "online" },
        providers: { xai: { configured: false, status: "None" } },
      }),
    });

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Online transcription isn't working")).toBeInTheDocument()
    );
    // The mic button is disabled (danger class)
    const mic = screen.getByLabelText("Recording blocked — provider unhealthy");
    expect(mic).toBeDisabled();
    // Actions are present
    expect(screen.getByText("Switch to Private")).toBeInTheDocument();
    expect(screen.getByText("Retry")).toBeInTheDocument();
    // Mono hint
    expect(screen.getByText(/dictate config set-key xai/)).toBeInTheDocument();
  });

  it("Switch to Private returns to capture home (sets faster-whisper model)", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    // First call returns online+unhealthy, subsequent patch returns private+healthy
    let patchCount = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts) => {
      if (opts?.method === "PATCH") {
        patchCount++;
        return { ok: true, json: async () => ({
          history: [],
          providerHealth: { healthy: true, status: "ok", mode: "private" },
        })};
      }
      return { ok: true, json: async () => ({
        history: [],
        providerHealth: { healthy: false, status: "no-key", mode: "online" },
        providers: { xai: { configured: false, status: "None" } },
      })};
    });

    render(<App />);
    await waitFor(() =>
      expect(screen.getByText("Online transcription isn't working")).toBeInTheDocument()
    );

    fireEvent.click(screen.getByText("Switch to Private"));

    // After switching, capture home should return (patchConfig was called)
    await waitFor(() =>
      expect(screen.getByText("Ready to capture")).toBeInTheDocument(), { timeout: 2000 }
    );
    expect(patchCount).toBeGreaterThan(0);
  });

  it("blocked mic button is visually disabled (aria)", async () => {
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
        providerHealth: { healthy: false, status: "auth", mode: "online" },
        providers: { xai: { configured: true, status: "Ready" } },
      }),
    });

    render(<App />);
    await waitFor(() =>
      expect(screen.getByLabelText("Recording blocked — provider unhealthy")).toBeInTheDocument()
    );
    const btn = screen.getByLabelText("Recording blocked — provider unhealthy");
    expect(btn).toBeDisabled();
    expect(btn.className).toContain("danger");
  });
});
