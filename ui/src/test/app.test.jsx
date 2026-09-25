import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within, cleanup, waitFor, act } from "@testing-library/react";
import App from "../App.jsx";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
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

// Meeting capture and the All / Meetings / Quick filter are beta-channel chrome.
function enableBeta() {
  fireEvent.click(screen.getByLabelText("About Dictate"));
  const dialog = screen.getByRole("dialog", { name: "Dictate" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Beta" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
}

function mockPackagePolling(statuses) {
  const sources = [];
  let checks = 0;
  let resolvedChecks = 0;
  window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
  window.__TAURI__ = { core: { invoke: vi.fn() } };
  window.EventSource = class {
    constructor() { sources.push(this); }
    close() {}
  };
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const path = String(url).replace("http://127.0.0.1:1", "");
    if (path === "/api/state") {
      return {
        ok: true,
        json: async () => ({
          version: "2026.7.4",
          updateChannel: "stable",
          model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
          history: [],
        }),
      };
    }
    if (path === "/api/update-status") {
      const status = statuses[Math.min(checks, statuses.length - 1)];
      checks += 1;
      if (status instanceof Error) throw status;
      return {
        ok: true,
        json: async () => {
          resolvedChecks += 1;
          return status;
        },
      };
    }
    return { ok: true, json: async () => ({}) };
  });
  return {
    sources,
    fetchSpy,
    getChecks: () => checks,
    getResolvedChecks: () => resolvedChecks,
  };
}

describe("Quiet Console app (mock mode)", () => {
  it("renders the capture (mic) home by default", () => {
    render(<App />);
    // Home is the capture surface: the cradle mic, ready status, and a Notes button.
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
    expect(screen.getByText("Click to dictate")).toBeInTheDocument();
    expect(screen.getByLabelText("Dictations")).toHaveAttribute("aria-pressed", "false");
  });

  it("teaches the key on a fresh launch, then swaps to copy-last after capturing", async () => {
    const { container } = render(<App />);
    // Fresh session (even with saved notes): the keyboard teaching graphic shows,
    // and there is no copy-last affordance yet.
    expect(container.querySelector(".gs-kbd")).toBeInTheDocument();
    expect(screen.queryByText("Copy last dictation")).not.toBeInTheDocument();

    // Capture a quick note — this begins the session — then return to the home.
    fireEvent.click(screen.getByLabelText("Start recording"));
    finishCapture();
    await waitFor(() => expect(screen.getByTitle("Copy")).toBeInTheDocument(), { timeout: 2000 });
    fireEvent.click(screen.getByLabelText("Close note"));

    // Teaching graphic is gone; copy-last is now offered for the recent dictation.
    expect(container.querySelector(".gs-kbd")).not.toBeInTheDocument();
    expect(screen.getByText("Copy last dictation")).toBeInTheDocument();
    expect(screen.getByText(/capture this as a project note/i)).toBeInTheDocument();
  });

  it("copies the most recent quick dictation from the home", async () => {
    const writeText = vi.fn().mockResolvedValue();
    Object.assign(navigator, { clipboard: { writeText } });
    render(<App />);
    // Begin the session and return to the home so the copy-last affordance appears.
    fireEvent.click(screen.getByLabelText("Start recording"));
    finishCapture();
    await waitFor(() => expect(screen.getByTitle("Copy")).toBeInTheDocument(), { timeout: 2000 });
    fireEvent.click(screen.getByLabelText("Close note"));
    fireEvent.click(screen.getByText("Copy last dictation"));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText.mock.calls[0][0]).toBeTruthy();
  });

  it("previews the exact whitespace-preserving text copied by copy-last", async () => {
    const sources = [];
    const exactText = "First line\n  second line";
    const writeText = vi.fn().mockResolvedValue();
    Object.assign(navigator, { clipboard: { writeText } });
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        history: [{ id: "quick_exact", text: exactText, createdAt: "2026-07-13T00:00:00+00:00" }],
      }),
    });

    const { container } = render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    act(() => {
      sources[0].onmessage({ data: JSON.stringify({ type: "recording", active: true }) });
      sources[0].onmessage({ data: JSON.stringify({ type: "recording", active: false }) });
    });

    await waitFor(() => expect(container.querySelector(".note-copylast-preview")).not.toBeNull());
    const preview = container.querySelector(".note-copylast-preview");
    expect(preview).not.toBeNull();
    expect(preview.textContent).toBe(exactText);
    fireEvent.click(screen.getByText("Copy last dictation"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(exactText));
  });

  it("trusts explicit note mode while retaining legacy segment meeting fallback", async () => {
    const sources = [];
    const writeText = vi.fn().mockResolvedValue();
    Object.assign(navigator, { clipboard: { writeText } });
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        updateChannel: "unstable",
        history: [
          {
            id: "segmented_note",
            text: "Explicit segmented conversation note",
            createdAt: "2026-07-14T00:00:00+00:00",
            mode: "note",
            segments: [{ seq: 0, text: "Explicit segmented conversation note" }],
          },
          {
            id: "legacy_segmented_meeting",
            text: "Legacy segmented meeting",
            createdAt: "2026-07-13T00:00:00+00:00",
            segments: [{ seq: 0, speaker_label: "Speaker 1", text: "Legacy segmented meeting" }],
          },
        ],
      }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    act(() => {
      sources[0].onmessage({ data: JSON.stringify({ type: "recording", active: true }) });
      sources[0].onmessage({ data: JSON.stringify({ type: "recording", active: false }) });
    });

    await screen.findByText("Copy last dictation");
    fireEvent.click(screen.getByText("Copy last dictation"));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Explicit segmented conversation note"));

    navTo("Notes");
    fireEvent.click(screen.getByRole("button", { name: "Meetings" }));
    expect(screen.getByText(/Legacy segmented meeting/)).toBeInTheDocument();
    expect(screen.queryByText("Explicit segmented conversation note")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Quick" }));
    expect(screen.getByText("Explicit segmented conversation note")).toBeInTheDocument();
    expect(screen.queryByText(/Legacy segmented meeting/)).not.toBeInTheDocument();
  });

  it("uses native Windows chrome without the inner mock titlebar", () => {
    window.__DICTATE__ = { platform: "win11" };
    const { container } = render(<App />);

    expect(container.querySelector(".win.native-chrome.win11")).toBeTruthy();
    expect(container.querySelector(".titlebar")).toBeNull();
  });

  it("has no settings gear — config lives in the dictate config CLI", () => {
    render(<App />);
    expect(screen.queryByTitle("Settings")).not.toBeInTheDocument();
    // Transcription is local-only: no provider switch to offer on the home.
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });

  it("shows update controls and lets local users choose Beta", async () => {
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
            updateChannel: "stable",
            installedPackageVersion: "2026.7.4",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/update-status") {
        return {
          ok: true,
          json: async () => ({
            currentVersion: "2026.7.4",
            latestVersion: "2026.7.4",
            updateAvailable: false,
            checked: true,
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("About Dictate"));

    expect(screen.getByRole("button", { name: "Normal" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Beta" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Check for update" }));
    await waitFor(() => expect(screen.getByText("You're on the latest version")).toBeInTheDocument());
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:1/api/update-status",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("clears a skipped version when account starts a command-style update", async () => {
    const sources = [];
    const invoke = vi.fn().mockResolvedValue(null);
    const stored = new Map();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key) => stored.get(key) ?? null),
      setItem: vi.fn((key, value) => stored.set(key, value)),
      removeItem: vi.fn((key) => stored.delete(key)),
    });
    let updateStarted = false;
    let commandPolls = 0;
    let releaseStart;
    const startResponse = new Promise((resolve) => { releaseStart = resolve; });
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.__TAURI__ = { core: { invoke } };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts = {}) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "unstable",
            installedPackageVersion: "2026.7.4",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/update-status") {
        if (updateStarted) {
          commandPolls += 1;
          if (commandPolls === 1) {
            return {
              ok: true,
              json: async () => ({
                checked: false,
                updateAvailable: false,
                phase: "failed",
                errorCode: "check_failed",
                errorDetail: "temporary registry failure",
              }),
            };
          }
        }
        return {
          ok: true,
          json: async () => ({
            currentVersion: updateStarted ? "2026.7.4-unstable.53.1" : "2026.7.4",
            latestVersion: "2026.7.4-unstable.53.1",
            updateAvailable: !updateStarted,
            checked: true,
          }),
        };
      }
      if (path === "/api/update" && opts.method === "POST") {
        updateStarted = true;
        await startResponse;
        return {
          ok: true,
          json: async () => ({
            mode: "command",
            started: true,
            message: "Started the Linux user updater.",
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    await screen.findByRole("button", { name: /Update available/i });
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(localStorage.getItem("dictate.skippedVersion")).toBe("2026.7.4-unstable.53.1");
    expect(screen.queryByRole("button", { name: /Update available/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "About Dictate" }));
    const accountUpdate = await screen.findByRole("button", { name: "Update" });
    fireEvent.click(accountUpdate);
    expect(localStorage.getItem("dictate.skippedVersion")).toBeNull();
    const preparingButton = await screen.findByRole("button", { name: /Preparing update/i });
    expect(accountUpdate).toBeDisabled();
    await act(async () => { releaseStart(); });

    expect(await screen.findByRole("button", { name: /Updating/i })).toBe(preparingButton);
    expect(screen.queryByRole("button", { name: /Restart Dictate/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Later" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip" })).not.toBeInTheDocument();

    const restartButton = await screen.findByRole("button", { name: /Restart Dictate/i }, { timeout: 4000 });
    expect(restartButton).toBe(preparingButton);
    expect(screen.queryByRole("button", { name: "Later" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip" })).not.toBeInTheDocument();
    fireEvent.click(restartButton);

    expect(await screen.findByRole("button", { name: /Restarting/i })).toBe(preparingButton);
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("restart_app"));
  });

  it("leaves preparing when package reservation resolves current", async () => {
    const sources = [];
    let checks = 0;
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "stable",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/update-status") {
        checks += 1;
        return {
          ok: true,
          json: async () => checks === 1
            ? {
                checked: true,
                updateAvailable: true,
                installKind: "linux-package",
                phase: "preparing",
              }
            : {
                checked: true,
                updateAvailable: false,
                installKind: "linux-package",
                phase: "current",
              },
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    expect(await screen.findByRole("button", { name: /Preparing update/i })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Check for updates" }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Preparing update/i })).not.toBeInTheDocument();
    expect(checks).toBe(2);
  });

  it.each(["Skip", "Later"])("explicit check shows available while %s remains suppressed", async (action) => {
    const stored = new Map();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key) => stored.get(key) ?? null),
      setItem: vi.fn((key, value) => stored.set(key, value)),
      removeItem: vi.fn((key) => stored.delete(key)),
    });
    const polling = mockPackagePolling([
      {
        checked: true,
        updateAvailable: false,
        installKind: "linux-package",
        phase: "current",
      },
      {
        checked: true,
        updateAvailable: true,
        latestVersion: "2026.7.5",
        installKind: "linux-package",
        phase: "available",
      },
    ]);

    render(<App />);
    await waitFor(() => expect(polling.getResolvedChecks()).toBe(1));
    await act(async () => {});
    fireEvent.click(await screen.findByRole("button", { name: "Check for updates" }));
    expect(await screen.findByRole("button", { name: /Update available/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: action }));
    expect(screen.queryByRole("button", { name: /Update available/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "About Dictate" }));
    fireEvent.click(await screen.findByRole("button", { name: "Check for update" }));
    await waitFor(() => expect(polling.getChecks()).toBe(3));
    expect(screen.queryByRole("button", { name: /Update available/i })).not.toBeInTheDocument();
  });

  it("restarts directly from the account update action", async () => {
    const invoke = vi.fn().mockResolvedValue(true);
    const polling = mockPackagePolling([
      {
        checked: true,
        updateAvailable: true,
        installKind: "linux-package",
        phase: "installed",
        actions: ["restart"],
      },
    ]);
    window.__TAURI__ = { core: { invoke } };

    render(<App />);
    expect(await screen.findByRole("button", { name: /Restart Dictate/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "About Dictate" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Dictate" })).getByRole("button", { name: "Restart" }));

    expect(await screen.findByRole("button", { name: /Restarting/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Preparing update/i })).not.toBeInTheDocument();
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("restart_app"));
    expect(polling.fetchSpy.mock.calls.some(([url, options]) => (
      String(url).endsWith("/api/update") && options?.method === "POST"
    ))).toBe(false);
  });

  it("re-adopts active package progress from an explicit check", async () => {
    const polling = mockPackagePolling([
      {
        checked: false,
        updateAvailable: false,
        phase: "failed",
        errorCode: "check_failed",
      },
      {
        checked: true,
        updateAvailable: true,
        installKind: "linux-package",
        phase: "downloading",
        progress: 42,
      },
    ]);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Check for updates" }));

    expect(await screen.findByRole("button", { name: /Downloading… 42%/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(polling.getChecks()).toBe(2);
  });

  it("restarts from an installed package found by explicit check", async () => {
    const invoke = vi.fn().mockResolvedValue(true);
    const polling = mockPackagePolling([
      {
        checked: false,
        updateAvailable: false,
        phase: "failed",
        errorCode: "check_failed",
      },
      {
        checked: true,
        updateAvailable: true,
        installKind: "linux-package",
        phase: "installed",
        actions: ["restart"],
      },
    ]);
    window.__TAURI__ = { core: { invoke } };

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Check for updates" }));

    const restart = await screen.findByRole("button", { name: /Restart Dictate/i });
    expect(invoke).not.toHaveBeenCalled();
    fireEvent.click(restart);
    expect(await screen.findByRole("button", { name: /Restarting/i })).toBeInTheDocument();
    await waitFor(() => expect(invoke).toHaveBeenCalledTimes(1));
    expect(invoke).toHaveBeenCalledWith("restart_app");
    expect(polling.getChecks()).toBe(2);
  });

  it("recovers package polling after a transient status failure", async () => {
    vi.useFakeTimers();
    const polling = mockPackagePolling([
      {
        checked: true,
        updateAvailable: true,
        installKind: "linux-package",
        phase: "preparing",
      },
      {
        checked: false,
        updateAvailable: true,
        installKind: "linux-package",
        phase: "failed",
        errorCode: "check_failed",
      },
      {
        checked: true,
        updateAvailable: true,
        installKind: "linux-package",
        phase: "downloading",
        progress: 42,
      },
    ]);

    render(<App />);
    await act(async () => {});
    expect(screen.getByRole("button", { name: /Preparing update/i })).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByRole("button", { name: /Preparing update/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByRole("button", { name: /Downloading… 42%/i })).toBeInTheDocument();
    expect(polling.getChecks()).toBe(3);
  });

  it("makes repeated package polling failures retryable", async () => {
    vi.useFakeTimers();
    const polling = mockPackagePolling([
      {
        checked: true,
        updateAvailable: true,
        installKind: "linux-package",
        phase: "preparing",
      },
      new Error("status transport unavailable"),
    ]);

    render(<App />);
    await act(async () => {});
    expect(screen.getByRole("button", { name: /Preparing update/i })).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText("Lost contact with updater. Retry the update.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(polling.getChecks()).toBe(4);

    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(polling.getChecks()).toBe(4);
  });

  it("clears a stale polling failure after a healthy explicit check", async () => {
    vi.useFakeTimers();
    const polling = mockPackagePolling([
      {
        checked: true,
        updateAvailable: true,
        installKind: "linux-package",
        phase: "preparing",
      },
      new Error("status transport unavailable"),
      new Error("status transport unavailable"),
      new Error("status transport unavailable"),
      {
        checked: true,
        updateAvailable: false,
        installKind: "linux-package",
        phase: "current",
      },
    ]);

    render(<App />);
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "About Dictate" }));
    fireEvent.click(screen.getByRole("button", { name: "Check for update" }));
    await act(async () => {});

    expect(polling.getChecks()).toBe(5);
    expect(screen.getByRole("button", { name: "Check for updates" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(screen.queryByText("Lost contact with updater. Retry the update.")).not.toBeInTheDocument();
  });

  it("turns an expired command update poll into a retryable failure", async () => {
    const sources = [];
    let started = false;
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts = {}) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "unstable",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/update" && opts.method === "POST") {
        started = true;
        return {
          ok: true,
          json: async () => ({ mode: "command", started: true, message: "Started updater." }),
        };
      }
      if (path === "/api/update-status") {
        if (!started) {
          return {
            ok: true,
            json: async () => ({
              checked: true,
              updateAvailable: true,
              latestVersion: "2026.7.5",
              phase: "available",
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            checked: false,
            updateAvailable: true,
            latestVersion: "2026.7.5",
            phase: "failed",
            errorCode: "check_failed",
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    const updateButton = await screen.findByRole("button", { name: /Update available/i });
    vi.useFakeTimers();
    fireEvent.click(updateButton);
    await act(async () => {});
    expect(screen.getByRole("button", { name: /Updating/i })).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(300_000); });

    expect(screen.getByText("Update status timed out. Retry the update.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  }, 15000);

  it("keeps launch discovery failures out of the active-update failure pill", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "stable",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/update-status") {
        return {
          ok: true,
          json: async () => ({
            checked: false,
            updateAvailable: false,
            phase: "failed",
            errorCode: "check_failed",
            errorDetail: "offline",
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    expect(await screen.findByRole("button", { name: "Check for updates" })).toBeInTheDocument();
    expect(screen.queryByText("Update failed")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("switches to Beta updates and adopts the new package version", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts = {}) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "stable",
            installedPackageVersion: "2026.7.4",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/config" && opts.method === "PATCH") {
        expect(opts.body).toBe(JSON.stringify({ updateChannel: "unstable" }));
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "unstable",
            installedPackageVersion: "2026.7.4-unstable.52.1",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/update-status") {
        return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("About Dictate"));
    fireEvent.click(screen.getByRole("button", { name: "Beta" }));

    await waitFor(() => expect(screen.getByText("Beta updates selected")).toBeInTheDocument());
    expect(screen.getByText("2026.7.4-unstable.52.1")).toBeInTheDocument();
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

  it("hides meeting capture and the dictation filter on the normal channel", () => {
    render(<App />);
    expect(screen.queryByRole("button", { name: "Meeting" })).not.toBeInTheDocument();
    navTo("Notes");
    expect(screen.queryByRole("group", { name: "Filter dictations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Meetings" })).not.toBeInTheDocument();
  });

  it("records a mock meeting with speaker-labelled output", async () => {
    render(<App />);
    enableBeta();
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

  it("keeps a completed local meeting accessible in Dictations", async () => {
    render(<App />);
    enableBeta();
    fireEvent.click(screen.getByText("Meeting"));
    fireEvent.click(screen.getByLabelText("Finish meeting"));
    await waitFor(() => expect(screen.getByLabelText("Close note")).toBeInTheDocument(), { timeout: 2000 });
    fireEvent.click(screen.getByLabelText("Close note"));
    fireEvent.click(screen.getByLabelText("Dictations"));
    fireEvent.click(screen.getByRole("button", { name: "Meetings" }));

    expect(screen.getByText(/launch blockers/i)).toBeInTheDocument();
    expect(screen.getByText(/test the Windows build/i)).toBeInTheDocument();
  });

  it("uses a compact listening indicator for push-to-talk without the old waveform", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ history: [], prefs: { overlay: true } }),
    });

    const { container } = render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    act(() => {
      sources[0].onmessage({ data: JSON.stringify({ type: "recording", active: true }) });
    });

    expect(screen.getByText("Listening")).toBeInTheDocument();
    expect(container.querySelector(".hud .wave")).not.toBeInTheDocument();
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
    enableBeta();
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

  it("category toggle filters meetings vs quick records", () => {
    render(<App />);
    enableBeta();
    navTo("Notes");
    // Default "All": both a meeting (diarized) and quick records are visible.
    expect(screen.getByText(/status round/i)).toBeInTheDocument();   // meeting (has segments)
    expect(screen.getByText(/reviewers/i)).toBeInTheDocument();      // quick (no segments)
    // "Meetings": only the meeting.
    fireEvent.click(screen.getByRole("button", { name: "Meetings" }));
    expect(screen.getByText(/status round/i)).toBeInTheDocument();
    expect(screen.queryByText(/reviewers/i)).not.toBeInTheDocument();
    // "Quick": only quick records.
    fireEvent.click(screen.getByRole("button", { name: "Quick" }));
    expect(screen.queryByText(/status round/i)).not.toBeInTheDocument();
    expect(screen.getByText(/reviewers/i)).toBeInTheDocument();
    // Back to "All": both again.
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText(/status round/i)).toBeInTheDocument();
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

  it("classifies a hydrated meeting by mode when it has no diarized segments", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        updateChannel: "unstable",
        history: [{
          id: "local_meeting_without_segments",
          text: "Durable local meeting without speaker labels",
          createdAt: "2026-07-13T00:00:00+00:00",
          mode: "meeting",
          segments: [],
        }],
      }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    navTo("Notes");
    fireEvent.click(screen.getByRole("button", { name: "Meetings" }));

    const meeting = await screen.findByText("Durable local meeting without speaker labels");
    expect(meeting).toBeInTheDocument();
    fireEvent.click(meeting);
    expect(screen.getByLabelText("Close note")).toBeInTheDocument();
    expect(screen.getByText("Durable local meeting without speaker labels")).toBeInTheDocument();
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
   Feature: honest update phases for the platform package updater.
   ===================================================================== */
describe("Update flow — package phases", () => {
  it("shows honest linux-package update phases without fake percentages", async () => {
    const sources = [];
    let launchChecked = false;
    let updatePolls = 0;
    const invoke = vi.fn().mockResolvedValue(null);
    const installStartedAt = new Date(Date.now() - 18_000).toISOString();
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.__TAURI__ = { core: { invoke } };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts = {}) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "stable",
            installedPackageVersion: "2026.7.4",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/update-status") {
        if (!launchChecked) {
          launchChecked = true;
          return {
            ok: true,
            json: async () => ({
              currentVersion: "2026.7.4",
              latestVersion: "2026.7.5",
              updateAvailable: true,
              checked: true,
              installKind: "linux-package",
              phase: "available",
            }),
          };
        }
        updatePolls += 1;
        if (updatePolls === 1) {
          return {
            ok: true,
            json: async () => ({
              currentVersion: "2026.7.4",
              latestVersion: "2026.7.5",
              updateAvailable: true,
              checked: true,
              installKind: "linux-package",
              phase: "downloading",
              progress: 42,
            }),
          };
        }
        if (updatePolls === 2) {
          return {
            ok: true,
            json: async () => ({
              currentVersion: "2026.7.4",
              latestVersion: "2026.7.5",
              updateAvailable: true,
              checked: true,
              installKind: "linux-package",
              phase: "verifying",
            }),
          };
        }
        if (updatePolls === 3) {
          return {
            ok: true,
            json: async () => ({
              currentVersion: "2026.7.4",
              latestVersion: "2026.7.5",
              updateAvailable: true,
              checked: true,
              installKind: "linux-package",
              phase: "installing",
              installStartedAt,
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            currentVersion: "2026.7.4",
            latestVersion: "2026.7.5",
            updateAvailable: true,
            checked: true,
            installKind: "linux-package",
            phase: "installed",
            step: "restart",
          }),
        };
      }
      if (path === "/api/update" && opts.method === "POST") {
        updatePolls = 0;
        return {
          ok: true,
          json: async () => ({
            mode: "working",
            started: true,
            installKind: "linux-package",
            phase: "downloading",
            progress: 0,
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    const updateButton = await screen.findByRole("button", { name: /Update available/i });
    fireEvent.click(updateButton);
    expect(await screen.findByRole("button", { name: /Downloading/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Later" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Skip" })).not.toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Downloading… 42%/i })).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.queryByRole("button", { name: /Updating \d+%/i })).not.toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Verifying download/i })).toBeInTheDocument();
    }, { timeout: 3000 });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Installing update… \d{2}:\d{2}/i })).toBeInTheDocument();
    }, { timeout: 5000 });
    const restart = await screen.findByRole("button", { name: /Restart Dictate/i }, { timeout: 3000 });
    expect(invoke).not.toHaveBeenCalled();
    fireEvent.click(restart);
    expect(await screen.findByRole("button", { name: /Restarting/i })).toBeInTheDocument();
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("restart_app"));
    expect(invoke).toHaveBeenCalledTimes(1);
  }, 15000);

  it("keeps update failure reason visible and retries from the pill", async () => {
    const sources = [];
    let attempts = 0;
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts = {}) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            version: "2026.7.4",
            updateChannel: "stable",
            installedPackageVersion: "2026.7.4",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
          }),
        };
      }
      if (path === "/api/update-status") {
        if (attempts === 0) {
          return {
            ok: true,
            json: async () => ({
              currentVersion: "2026.7.4",
              latestVersion: "2026.7.5",
              updateAvailable: true,
              checked: true,
              installKind: "linux-package",
              phase: "available",
            }),
          };
        }
        if (attempts === 1) {
          return {
            ok: true,
            json: async () => ({
              currentVersion: "2026.7.4",
              latestVersion: "2026.7.5",
              updateAvailable: true,
              checked: true,
              installKind: "linux-package",
              phase: "failed",
              errorDetail: "Download checksum mismatch",
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            currentVersion: "2026.7.4",
            latestVersion: "2026.7.5",
            updateAvailable: true,
            checked: true,
            installKind: "linux-package",
            phase: "downloading",
            progress: 0,
          }),
        };
      }
      if (path === "/api/update" && opts.method === "POST") {
        attempts += 1;
        if (attempts === 1) {
          return {
            ok: true,
            json: async () => ({
              mode: "error",
              started: false,
              installKind: "linux-package",
              phase: "failed",
              errorDetail: "Download checksum mismatch",
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            mode: "working",
            started: true,
            installKind: "linux-package",
            phase: "downloading",
            progress: 0,
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    const updateButton = await screen.findByRole("button", { name: /Update available/i });
    fireEvent.click(updateButton);

    expect(await screen.findByRole("status")).toHaveTextContent("Download checksum mismatch");
    const retry = await screen.findByRole("button", { name: "Retry" });
    fireEvent.click(retry);
    expect(await screen.findByRole("button", { name: /Downloading/i })).toBeInTheDocument();
    expect(attempts).toBe(2);
  });
});
