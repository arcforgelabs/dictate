import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within, cleanup, waitFor } from "@testing-library/react";
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
    // Capture home: gear button, the record cradle button, and status text.
    // "Dictate" appears in both TitleBar and the capture header so use getAllBy.
    expect(screen.getAllByText("Dictate").length).toBeGreaterThanOrEqual(1);
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
