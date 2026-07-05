import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within, cleanup, waitFor, act } from "@testing-library/react";
import App from "../App.jsx";

afterEach(() => {
  cleanup();
  delete window.__DICTATE__;
  delete window.__TAURI__;
  delete window.EventSource;
  vi.restoreAllMocks();
});

// Navigate to a settings view via the ⌘K command palette.
// The palette opens with Ctrl+K, we type the label to filter to one item,
// then press Enter to execute. The palette closes and the view renders.
function navTo(label) {
  fireEvent.keyDown(window, { ctrlKey: true, key: "k", bubbles: true });
  const input = screen.getByPlaceholderText(/Search notes, run an action/i);
  fireEvent.change(input, { target: { value: label } });
  fireEvent.keyDown(input, { key: "Enter" });
}

function finishCapture() {
  fireEvent.click(screen.getByLabelText("Pause recording"));
  fireEvent.click(screen.getByText("Finish note"));
}

describe("Quiet Console app (mock mode)", () => {
  it("renders the capture (mic) home by default", () => {
    render(<App />);
    // Home is the capture surface: the cradle mic, ready status, and a Notes button.
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Click to dictate")).toBeInTheDocument();
    expect(screen.getByLabelText("Dictations")).toHaveAttribute("aria-pressed", "false");
  });

  it("has no settings gear — config lives in the dictate config CLI", () => {
    render(<App />);
    expect(screen.queryByTitle("Settings")).not.toBeInTheDocument();
    // The one survivor on the home is the privacy toggle.
    expect(screen.getByLabelText("Local")).toBeInTheDocument();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("opens account status behind the Dictate mark and enables encrypted sync", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts = {}) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "unstable",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            device: { device: "cuda", compute: "float16" },
            history: [],
            dictatePro: { signedIn: true, account: { email: "samuel@example.test" } },
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
          }),
        };
      }
      if (path === "/api/pro/sync/enable" && opts.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            sync: { enabled: true, accountId: "acct_1", deviceId: "dev_1", keyAvailable: true, lastSeq: 4 },
            recoveryKey: "dictate-rk-test",
          }),
        };
      }
      if (path === "/api/pro/devices") {
        return {
          ok: true,
          json: async () => ({
            devices: [
              { device_id: "dev_1", label: "This workstation", revoked_at: null },
              { device_id: "dev_2", label: "Windows lab", revoked_at: null },
            ],
          }),
        };
      }
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("Dictate account and status"));

    expect(screen.getByRole("dialog", { name: "Dictate" })).toBeInTheDocument();
    expect(screen.getByText("Version 2026.7.4 · unstable")).toBeInTheDocument();
    expect(screen.getByText("samuel@example.test")).toBeInTheDocument();
    expect(screen.getByText("Sync off")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Recovery key"), { target: { value: "dictate-rk-existing" } });
    expect(screen.getByText("Restore encrypted sync")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Recovery key"), { target: { value: "" } });

    fireEvent.click(screen.getByText("Enable encrypted sync"));
    await waitFor(() => expect(screen.getByText("Encrypted sync on")).toBeInTheDocument());
    expect(screen.getByText("Encrypted sync enabled")).toBeInTheDocument();
    expect(screen.getByText("dictate-rk-test")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Windows lab")).toBeInTheDocument());
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:1/api/pro/sync/enable",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows API key toast with copy instructions when enabling cloud without a key", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<App />);
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.getByText("Requires Dictate Pro or API key.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Copy"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("dictate config set-key xai")));
    expect(writeText.mock.calls[0][0]).toContain("dictate config set-provider online");
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("opens Dictate Pro when the missing-key toast is clicked", () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    render(<App />);
    fireEvent.click(screen.getByRole("switch"));
    const toast = screen.getByText("Requires Dictate Pro or API key.").closest(".toast");
    fireEvent.click(toast);
    expect(open).toHaveBeenCalledWith(
      "https://arcforge.au/download/dictate#dictate-pro",
      "_blank",
      "noopener,noreferrer",
    );
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("notebook toggle returns to the capture home from the dictations view", () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("Dictations"));
    expect(screen.getByPlaceholderText("Search dictations")).toBeInTheDocument();
    expect(screen.getByLabelText("Back to capture")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByLabelText("Back to capture"));
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Click to dictate")).toBeInTheDocument();
  });

  it("toggles the theme via the command palette", () => {
    render(<App />);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    navTo("Switch to dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("wears GNOME chrome by default", () => {
    const { container } = render(<App />);
    expect(container.querySelector(".win")).toHaveClass("gnome");
    expect(container.querySelector(".adw")).toBeInTheDocument();
    expect(container.querySelector(".wincaps")).toBeNull();
  });

  it("pauses and resumes a mock capture from the cradle", () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("Start recording"));
    fireEvent.click(screen.getByLabelText("Pause recording"));
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByText("Finish note")).toBeInTheDocument();
    expect(screen.getByLabelText("Discard recording")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Resume recording"));
    expect(screen.getByText("Recording")).toBeInTheDocument();
    expect(screen.getByLabelText("Pause recording")).toBeInTheDocument();
  });

  it("discards a paused mock capture after confirmation", async () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("Start recording"));
    fireEvent.click(screen.getByLabelText("Pause recording"));
    fireEvent.click(screen.getByLabelText("Discard recording"));
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("Discard note?")).toBeInTheDocument();
    const confirm = screen.getByRole("button", { name: "Confirm" });
    await waitFor(() => expect(confirm).toHaveFocus());
    fireEvent.click(confirm);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByText("Click to dictate")).toBeInTheDocument();
    expect(screen.queryByText("Transcribing…")).not.toBeInTheDocument();
  });

  it("shows Transcribing… then expanded note after a mock capture", async () => {
    render(<App />);
    // Start recording
    fireEvent.click(screen.getByLabelText("Start recording"));
    expect(screen.getByLabelText("Pause recording")).toBeInTheDocument();
    finishCapture();
    expect(screen.getByText("Transcribing…")).toBeInTheDocument();
    // After the 800 ms mock delay the expanded note view appears
    await waitFor(() => expect(screen.getByTitle("Copy")).toBeInTheDocument(), { timeout: 2000 });
    expect(screen.getByTitle("Copy")).toBeInTheDocument();
    expect(screen.getByLabelText("Close note")).toBeInTheDocument();
    // The note text from the mock is visible
    expect(screen.getByText(/project note/i)).toBeInTheDocument();
  });

  it("records a mock meeting with speaker-labelled output", async () => {
    render(<App />);
    fireEvent.click(screen.getByText("Meeting"));
    expect(screen.getByText("Meeting")).toBeInTheDocument();
    expect(screen.getByLabelText("Finish meeting")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Finish meeting"));
    expect(screen.getByText("Transcribing…")).toBeInTheDocument();
    expect(screen.getByText("Separating speakers and preparing the transcript.")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByTitle("Copy")).toBeInTheDocument(), { timeout: 2000 });
    expect(screen.getByText("Speaker 1")).toBeInTheDocument();
    expect(screen.getByText("Speaker 2")).toBeInTheDocument();
    expect(screen.getByText("0:00-0:02")).toBeInTheDocument();
    expect(screen.getByText(/launch blockers/i)).toBeInTheDocument();
  });

  it("does not return canned transcripts in a shell without an engine bridge", () => {
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    render(<App />);
    expect(screen.queryByText(/meeting summary/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Start recording"));

    expect(screen.getByText("Dictate engine is not connected")).toBeInTheDocument();
    expect(screen.queryByLabelText("Pause recording")).not.toBeInTheDocument();
    expect(screen.queryByText(/project note/i)).not.toBeInTheDocument();
  });

  it("close from expanded note (after capture) returns to capture home", async () => {
    render(<App />);
    fireEvent.click(screen.getByLabelText("Start recording"));
    finishCapture();
    await waitFor(() => expect(screen.getByTitle("Copy")).toBeInTheDocument(), { timeout: 2000 });
    fireEvent.click(screen.getByLabelText("Close note"));
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Click to dictate")).toBeInTheDocument();
  });

  it("exports expanded note as markdown through the native save bridge", async () => {
    const invoke = vi.fn().mockResolvedValue(true);
    render(<App />);
    fireEvent.click(screen.getByLabelText("Start recording"));
    finishCapture();
    await waitFor(() => expect(screen.getByTitle("Export as Markdown")).toBeInTheDocument(), { timeout: 2000 });
    window.__TAURI__ = { core: { invoke } };
    fireEvent.click(screen.getByTitle("Export as Markdown"));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("save_text_file", expect.objectContaining({
      defaultName: expect.stringMatching(/^dictate-note-\d{4}-\d{2}-\d{2}\.md$/),
      content: expect.stringContaining("# Note -"),
    })));
    expect(screen.getByText("Saved as Markdown")).toBeInTheDocument();
  });

  it("exports segmented meeting notes with speaker labels and timestamps", async () => {
    const invoke = vi.fn().mockResolvedValue(true);
    render(<App />);
    fireEvent.click(screen.getByText("Meeting"));
    fireEvent.click(screen.getByLabelText("Finish meeting"));

    await waitFor(() => expect(screen.getByTitle("Export as Markdown")).toBeInTheDocument(), { timeout: 2000 });
    window.__TAURI__ = { core: { invoke } };
    fireEvent.click(screen.getByTitle("Export as Markdown"));

    await waitFor(() => expect(invoke).toHaveBeenCalledWith("save_text_file", expect.objectContaining({
      content: expect.stringContaining("**Speaker 1 [0:00-0:02]:** Let's capture the launch blockers."),
    })));
    expect(invoke.mock.calls[0][1].content).toContain("**Speaker 2 [0:02-0:05]:** I will test the Windows build and report back tomorrow.");
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
  it("renders the dictations list with search field", () => {
    render(<App />);
    navTo("Notes");
    expect(screen.getByPlaceholderText("Search dictations")).toBeInTheDocument();
    expect(screen.getByLabelText("Back to capture")).toHaveAttribute("aria-pressed", "true");
  });

  it("shows all three mock notes in the list", () => {
    render(<App />);
    navTo("Notes");
    expect(screen.getByText(/meeting summary/i)).toBeInTheDocument();
    expect(screen.getByText(/planning session/i)).toBeInTheDocument();
    expect(screen.getByText(/reviewers/i)).toBeInTheDocument();
  });

  it("search filters notes by text", () => {
    render(<App />);
    navTo("Notes");
    const input = screen.getByPlaceholderText("Search dictations");
    fireEvent.change(input, { target: { value: "summary" } });
    // Matching note visible
    expect(screen.getByText(/Reminder to send/i)).toBeInTheDocument();
    // Non-matching notes absent
    expect(screen.queryByText(/reviewers/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/planning session/i)).not.toBeInTheDocument();
  });

  it("shows no-results state when search has no matches", () => {
    render(<App />);
    navTo("Notes");
    const input = screen.getByPlaceholderText("Search dictations");
    fireEvent.change(input, { target: { value: "xyzzy" } });
    expect(screen.getByText(/No notes match/i)).toBeInTheDocument();
  });

  it("clear button removes the search query and shows all notes again", () => {
    render(<App />);
    navTo("Notes");
    const input = screen.getByPlaceholderText("Search dictations");
    fireEvent.change(input, { target: { value: "summary" } });
    expect(screen.queryByText(/reviewers/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Clear search"));
    expect(screen.getByText(/reviewers/i)).toBeInTheDocument();
  });

  it("archive button removes a note from the visible list", async () => {
    render(<App />);
    navTo("Notes");
    expect(screen.getByText(/meeting summary/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByTitle("Archive note")[0]);
    expect(screen.getByText(/Note archived/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText(/meeting summary/i)).not.toBeInTheDocument();
    });
  });

  it("archive toast undo restores the note", async () => {
    render(<App />);
    navTo("Notes");
    fireEvent.click(screen.getAllByTitle("Archive note")[0]);
    fireEvent.click(screen.getByText("Undo"));
    expect(screen.getByText(/meeting summary/i)).toBeInTheDocument();
  });

  it("tapping a note row opens it in the expanded view", () => {
    render(<App />);
    navTo("Notes");
    // Click the summary note row (its text bubbles the click up to note-row)
    fireEvent.click(screen.getByText(/meeting summary/i));
    // Should now be in the ExpandedNote view
    expect(screen.getByTitle("Copy")).toBeInTheDocument();
    // The note text appears in the expanded body
    expect(screen.getByText(/meeting summary/i)).toBeInTheDocument();
  });

  it("Space key on a note row opens it in the expanded view (role=button a11y)", () => {
    render(<App />);
    navTo("Notes");
    // Find the note-row div via its role="button" that contains the summary text
    const noteRow = screen.getByText(/meeting summary/i).closest('[role="button"]');
    fireEvent.keyDown(noteRow, { key: " " });
    expect(screen.getByTitle("Copy")).toBeInTheDocument();
    expect(screen.getByText(/meeting summary/i)).toBeInTheDocument();
  });

  it("close from expanded note (opened from notes list) returns to capture home", () => {
    render(<App />);
    navTo("Notes");
    fireEvent.click(screen.getByText(/meeting summary/i));
    fireEvent.click(screen.getByLabelText("Close note"));
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Click to dictate")).toBeInTheDocument();
  });

  it("back column in expanded note returns to the notes list", () => {
    render(<App />);
    navTo("Notes");
    fireEvent.click(screen.getByText(/meeting summary/i));
    fireEvent.click(screen.getByLabelText("Back to dictations"));
    expect(screen.getByPlaceholderText("Search dictations")).toBeInTheDocument();
    expect(screen.getByLabelText("Back to capture")).toHaveAttribute("aria-pressed", "true");
  });

  it("rehydrates persisted meeting segments from live state", async () => {
    const sources = [];
    const invoke = vi.fn().mockResolvedValue(true);
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.__TAURI__ = { core: { invoke } };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        history: [{
          id: "note_meeting",
          text: "Meeting transcript saved",
          createdAt: "2026-07-05T00:00:00+00:00",
          mode: "meeting",
          speakerLabels: true,
          segments: [
            {
              seq: 0,
              t_start: 0.48,
              t_end: 3.36,
              text: "The birch canoe slid on the smooth planks.",
              speaker_id: "speaker_0",
              speaker_label: "Speaker 1",
            },
            {
              seq: 1,
              t_start: 3.36,
              t_end: 7.68,
              text: "Paint the sockets in the wall dull green.",
              speaker_id: "speaker_1",
              speaker_label: "Speaker 2",
            },
          ],
        }],
      }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    navTo("Notes");
    const input = screen.getByPlaceholderText("Search dictations");
    fireEvent.change(input, { target: { value: "paint the sockets" } });
    expect(screen.getByText(/The birch canoe slid/i)).toBeInTheDocument();
    expect(screen.getByText(/Paint the sockets/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Export as Markdown"));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("save_text_file", expect.objectContaining({
      content: expect.stringContaining("**Speaker 1 [0:00-0:03]:** The birch canoe slid on the smooth planks."),
    })));
    expect(invoke.mock.calls[0][1].content).toContain(
      "**Speaker 2 [0:03-0:07]:** Paint the sockets in the wall dull green.",
    );
    fireEvent.click(screen.getByText(/Paint the sockets/i));

    expect(screen.getByText("Speaker 1")).toBeInTheDocument();
    expect(screen.getByText("Speaker 2")).toBeInTheDocument();
    expect(screen.getByText("0:00-0:03")).toBeInTheDocument();
    expect(screen.getByText("0:03-0:07")).toBeInTheDocument();
    expect(screen.getByText("The birch canoe slid on the smooth planks.")).toBeInTheDocument();
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
    expect(screen.getByText("Click to dictate")).toBeInTheDocument();
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
    expect(screen.getByLabelText("Pause recording")).toBeInTheDocument();

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

    // Privacy toggle stays on (on-device fallback) and shows degraded styling
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(document.querySelector(".privpill.degraded")).toBeInTheDocument();

    // Mic remains functional (recording still active)
    expect(screen.getByLabelText("Pause recording")).toBeInTheDocument();
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
      expect(document.querySelector(".privpill.degraded")).toBeInTheDocument()
    );
    expect(screen.getByLabelText("Pause recording")).toBeInTheDocument();
  });
});
