import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within, cleanup, waitFor } from "@testing-library/react";
import App from "../App.jsx";

afterEach(() => {
  cleanup();
  delete window.__DICTATE__;
  delete window.EventSource;
  vi.restoreAllMocks();
});

// Click a sidebar nav entry by its label, scoped to the rail so it never
// collides with same-named mini-cards or badges elsewhere on the page.
function navTo(container, label) {
  const nav = container.querySelector(".nav");
  fireEvent.click(within(nav).getByText(label));
}

describe("Quiet Console app (mock mode)", () => {
  it("renders the Status view by default", () => {
    render(<App />);
    expect(screen.getByText("Ready to dictate")).toBeInTheDocument();
    expect(screen.getByText("Hold to try dictation")).toBeInTheDocument();
  });

  it("navigates to the Model view and lists all four providers", () => {
    const { container } = render(<App />);
    navTo(container, "Model");
    expect(screen.getByText("Transcription model")).toBeInTheDocument();
    expect(screen.getByText("faster-whisper · turbo")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini-transcribe")).toBeInTheDocument();
    expect(screen.getByText("grok-speech-to-text")).toBeInTheDocument();
    expect(screen.getByText("gemini-3-flash-preview")).toBeInTheDocument();
  });

  it("adds and removes a hotword", () => {
    const { container } = render(<App />);
    navTo(container, "Hotwords");
    const input = screen.getByPlaceholderText("Add a word…");
    fireEvent.change(input, { target: { value: "Kubernetes" } });
    fireEvent.click(screen.getByText("Add word"));
    expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Remove Kubernetes"));
    expect(screen.queryByText("Kubernetes")).not.toBeInTheDocument();
  });

  it("toggles the theme via the rail button", () => {
    render(<App />);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    fireEvent.click(screen.getByTitle("Toggle theme"));
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
});
