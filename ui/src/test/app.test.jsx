import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within, cleanup, waitFor, act } from "@testing-library/react";
import App from "../App.jsx";
import { PRODUCT_DESTINATIONS } from "../productDestinations.js";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
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

const ACTIVE_PRO = {
  signedIn: true,
  account: { email: "samuel@example.test" },
  entitlements: { active: true, display_name: "Dictate Pro", status: "active" },
};

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
            dictatePro: ACTIVE_PRO,
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
              { device_id: "dev_1", label: "This workstation", trusted_at: "2026-07-05T12:00:00Z", revoked_at: null },
              { device_id: "dev_2", label: "Windows lab", trusted_at: "2026-07-05T12:00:00Z", revoked_at: null },
              { device_id: "dev_3", label: "New laptop", trusted_at: null, revoked_at: null },
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
    expect(screen.getByText("Offline")).toBeInTheDocument();
    expect(screen.getByText("Sync my dictations across devices")).toBeInTheDocument();
    expect(screen.getByText("This encrypts your synced dictations before upload.")).toBeInTheDocument();
    expect(screen.getByText("Hosted Pro transcription is separate from sync and may send audio to hosted model providers when selected.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Recovery key"), { target: { value: "dictate-rk-existing" } });
    expect(screen.getByText("Restore sync")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Recovery key"), { target: { value: "" } });

    fireEvent.click(screen.getByText("Sync my dictations"));
    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
    expect(screen.getByText("Encrypted sync enabled")).toBeInTheDocument();
    expect(screen.getByText("Save this key. It restores synced dictations on a new device if your other devices are unavailable.")).toBeInTheDocument();
    expect(screen.getByText("dictate-rk-test")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Windows lab")).toBeInTheDocument());
    expect(screen.getByText("New laptop")).toBeInTheDocument();
    expect(screen.getByText("Action needed")).toBeInTheDocument();
    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:1/api/pro/sync/enable",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("offers Manage account only when signed in, and it opens the web portal", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
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
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
            dictatePro: ACTIVE_PRO,
            productDestinations: PRODUCT_DESTINATIONS,
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
          }),
        };
      }
      if (path === "/api/pro/devices") return { ok: true, json: async () => ({ devices: [] }) };
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("Dictate account and status"));

    expect(screen.getByText("samuel@example.test")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Manage account"));
    expect(open).toHaveBeenCalledWith(
      PRODUCT_DESTINATIONS.hub,
      "_blank",
      "noopener,noreferrer",
    );
    expect(screen.getByText("Opened account portal")).toBeInTheDocument();
  });

  it("does not offer Manage account when signed out", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
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
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
            dictatePro: { signedIn: false, account: null },
            browserSigninEnabled: true,
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
          }),
        };
      }
      if (path === "/api/pro/devices") return { ok: true, json: async () => ({ devices: [] }) };
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("Dictate account and status"));
    fireEvent.click(screen.getByRole("button", { name: "Account" }));

    expect(screen.getByText("Sign in")).toBeInTheDocument();
    expect(screen.queryByText("Manage account")).not.toBeInTheDocument();
  });

  // Shared harness for the signed-out account panel: mounts the app, opens the account
  // dialog and reveals the sign-in block, wiring `fetch` through a caller-supplied router
  // keyed on path (+ method for ambiguous paths). Returns the fetch spy for assertions.
  function renderSignedOutAccountPanel(routes) {
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
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
            dictatePro: { signedIn: false, account: null },
            // These tests exercise the browser sign-in flow itself; the one test that
            // covers the disabled state builds its own /api/state mock with this false.
            browserSigninEnabled: true,
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
          }),
        };
      }
      if (path === "/api/pro/devices") return { ok: true, json: async () => ({ devices: [] }) };
      const route = routes(path, opts);
      if (route) return route;
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });
    return { sources, fetchSpy };
  }

  async function openSignInBlock(sources) {
    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("Dictate account and status"));
    expect(screen.getByText("Not signed in")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
  }

  it("shows a working Sign in affordance instead of the old unavailable apology", async () => {
    const { sources } = renderSignedOutAccountPanel(() => null);
    await openSignInBlock(sources);

    expect(screen.queryByText("Browser sign-in unavailable")).not.toBeInTheDocument();
    expect(screen.getByText("Sign in")).toBeInTheDocument();
    expect(screen.getByText("Opens your browser to connect this device to your account.")).toBeInTheDocument();
    expect(screen.getByText("Email me a code instead")).toBeInTheDocument();
  });

  it("drives the loopback waiting state, reopens the link, and cancels back to idle", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    let cancelCalls = 0;
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/browser/start" && opts.method === "POST") {
        return { ok: true, json: async () => ({ flow: "loopback", authorize_url: "http://127.0.0.1:9/authorize?x=1", expires_in: 300 }) };
      }
      if (path === "/api/pro/auth/browser/status") {
        return { ok: true, json: async () => ({ status: "pending" }) };
      }
      if (path === "/api/pro/auth/browser/cancel" && opts.method === "POST") {
        cancelCalls += 1;
        return { ok: true, json: async () => ({ status: "cancelled" }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => expect(screen.getByText("Waiting for browser…")).toBeInTheDocument());
    expect(screen.getByText("Approve the sign-in in the browser tab we just opened.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Open sign-in page"));
    expect(open).toHaveBeenCalledWith("http://127.0.0.1:9/authorize?x=1", "_blank", "noopener,noreferrer");

    fireEvent.click(screen.getByText("Cancel"));
    await waitFor(() => expect(cancelCalls).toBe(1));
    expect(screen.getByText("Sign in")).toBeInTheDocument();
  }, 10_000);

  it("completes sign-in once the status poll reports complete", async () => {
    let statusCalls = 0;
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/browser/start" && opts.method === "POST") {
        return { ok: true, json: async () => ({ flow: "loopback", authorize_url: "http://127.0.0.1:9/authorize", expires_in: 300 }) };
      }
      if (path === "/api/pro/auth/browser/status") {
        statusCalls += 1;
        if (statusCalls < 2) return { ok: true, json: async () => ({ status: "pending" }) };
        return { ok: true, json: async () => ({ status: "complete", account_id: "acct_1", device_id: "dev_1", dictatePro: ACTIVE_PRO }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => expect(screen.getByText("Waiting for browser…")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("samuel@example.test")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText("Signed in")).toBeInTheDocument();
  }, 10_000);

  it("shows the device-code waiting state with a copyable code and portal link", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/browser/start" && opts.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            flow: "device_code",
            user_code: "ABCD-EFGH",
            verification_uri: "http://127.0.0.1:9/device",
            verification_uri_complete: "http://127.0.0.1:9/device?user_code=ABCD-EFGH",
            expires_in: 900,
            interval: 5,
          }),
        };
      }
      if (path === "/api/pro/auth/browser/status") {
        return { ok: true, json: async () => ({ status: "pending" }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument());
    expect(screen.getByText("Enter this code at your account portal")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Open portal"));
    expect(open).toHaveBeenCalledWith(
      "http://127.0.0.1:9/device?user_code=ABCD-EFGH",
      "_blank",
      "noopener,noreferrer",
    );
  }, 10_000);

  it("never opens a non-https/non-loopback verification_uri (belt-and-braces)", async () => {
    // The Python client already clamps this server-side (ProClient._clamp_verification_uri);
    // this is the last-line-of-defense guard in openVerificationPortal itself.
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/browser/start" && opts.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            flow: "device_code",
            user_code: "ABCD-EFGH",
            verification_uri: "javascript:alert(1)",
            verification_uri_complete: "javascript:alert(1)",
            expires_in: 900,
            interval: 5,
          }),
        };
      }
      if (path === "/api/pro/auth/browser/status") {
        return { ok: true, json: async () => ({ status: "pending" }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Open portal"));
    expect(open).not.toHaveBeenCalled();
  }, 10_000);

  it("cancels the pending attempt instead of leaking a poll if the dialog closes mid-request", async () => {
    let resolveStart;
    const startPromise = new Promise((resolve) => { resolveStart = resolve; });
    let cancelCalls = 0;
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/browser/start" && opts.method === "POST") {
        return startPromise.then(() => ({
          ok: true,
          json: async () => ({ flow: "loopback", authorize_url: "http://127.0.0.1:9/authorize", expires_in: 300 }),
        }));
      }
      if (path === "/api/pro/auth/browser/cancel" && opts.method === "POST") {
        cancelCalls += 1;
        return { ok: true, json: async () => ({ status: "cancelled" }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Sign in"));
    // Close the dialog (unmounts AccountDialog) while /browser/start is still in flight.
    fireEvent.click(screen.getByLabelText("Close"));
    resolveStart();

    await waitFor(() => expect(cancelCalls).toBe(1));
  }, 10_000);

  it("resets the email form on Cancel instead of resuming a stale code-entry step", async () => {
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/start" && opts.method === "POST") {
        return { ok: true, json: async () => ({ challenge_id: "ch_1", account_id: "acct_1" }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Email me a code instead"));
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "samuel@example.test" } });
    fireEvent.click(screen.getByText("Send code"));
    await waitFor(() => expect(screen.getByLabelText("Sign-in code")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByText("Sign in with an email code")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Email me a code instead"));
    expect(screen.getByLabelText("Email address")).toHaveValue("");
    expect(screen.queryByLabelText("Sign-in code")).not.toBeInTheDocument();
  });

  it("shows honest email-only copy when browser sign-in is disabled", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
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
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
            dictatePro: { signedIn: false, account: null },
            browserSigninEnabled: false,
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
          }),
        };
      }
      if (path === "/api/pro/devices") return { ok: true, json: async () => ({ devices: [] }) };
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });

    await openSignInBlock(sources);

    expect(screen.getByText("We'll email you a code to sign in this device.")).toBeInTheDocument();
    expect(screen.queryByText("Opens your browser to connect this device to your account.")).not.toBeInTheDocument();
    expect(screen.queryByText("Email me a code instead")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Sign in"));
    expect(screen.getByText("Sign in with an email code")).toBeInTheDocument();
  });

  it("shows an inline error with Try again / Email me a code after a failed poll", async () => {
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/browser/start" && opts.method === "POST") {
        return { ok: true, json: async () => ({ flow: "loopback", authorize_url: "http://127.0.0.1:9/authorize", expires_in: 300 }) };
      }
      if (path === "/api/pro/auth/browser/status") {
        return { ok: true, json: async () => ({ status: "error", reason: "expired_token" }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => expect(screen.getByText("Sign-in timed out.")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText("Try again")).toBeInTheDocument();
    expect(screen.getByText("Email me a code")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Email me a code"));
    expect(screen.getByText("Sign in with an email code")).toBeInTheDocument();
  }, 10_000);

  it("falls back straight to the email form with no apology when browser sign-in is unavailable", async () => {
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/browser/start" && opts.method === "POST") {
        return { ok: true, json: async () => ({ flow: "email" }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Sign in"));
    await waitFor(() => expect(screen.getByText("Sign in with an email code")).toBeInTheDocument());
    expect(screen.queryByText("Browser sign-in unavailable")).not.toBeInTheDocument();
    expect(screen.queryByText("Waiting for browser…")).not.toBeInTheDocument();
  });

  it("completes sign-in via the email code fallback form", async () => {
    const { sources } = renderSignedOutAccountPanel((path, opts) => {
      if (path === "/api/pro/auth/start" && opts.method === "POST") {
        return { ok: true, json: async () => ({ challenge_id: "ch_1", expires_at: "2026-07-06T00:00:00Z", account_id: "acct_1" }) };
      }
      if (path === "/api/pro/auth/complete" && opts.method === "POST") {
        return { ok: true, json: async () => ({ account_id: "acct_1", device_id: "dev_1", signedIn: true, dictatePro: ACTIVE_PRO }) };
      }
      return null;
    });
    await openSignInBlock(sources);

    fireEvent.click(screen.getByText("Email me a code instead"));
    expect(screen.getByText("Sign in with an email code")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "samuel@example.test" } });
    fireEvent.click(screen.getByText("Send code"));
    await waitFor(() => expect(screen.getByText("Code sent — check your email")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Sign-in code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Verify code"));
    await waitFor(() => expect(screen.getByText("samuel@example.test")).toBeInTheDocument());
    expect(screen.getByText("Signed in")).toBeInTheDocument();
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
            dictatePro: { signedIn: false, account: null },
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
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
    fireEvent.click(screen.getByLabelText("Dictate account and status"));

    expect(screen.getByRole("button", { name: "Normal" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Beta" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Check for update" }));
    await waitFor(() => expect(screen.getByText("You're on the latest version")).toBeInTheDocument());
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:1/api/update-status",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("turns command-style updates into a same-position restart action", async () => {
    const sources = [];
    const invoke = vi.fn().mockResolvedValue(null);
    let updateStarted = false;
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
            dictatePro: { signedIn: false, account: null },
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
          }),
        };
      }
      if (path === "/api/update-status") {
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
    const updateButton = await screen.findByRole("button", { name: /Update available/i });
    fireEvent.click(updateButton);
    expect(await screen.findByRole("button", { name: /Updating/i })).toBe(updateButton);
    expect(screen.queryByRole("button", { name: /Restart Dictate/i })).not.toBeInTheDocument();

    const restartButton = await screen.findByRole("button", { name: /Restart Dictate/i }, { timeout: 4000 });
    expect(restartButton).toBe(updateButton);
    fireEvent.click(restartButton);

    expect(await screen.findByRole("button", { name: /Restarting/i })).toBe(updateButton);
    await waitFor(() => expect(invoke).toHaveBeenCalledWith("restart_app"));
  });

  it("lets Dictate Pro users switch to Beta updates", async () => {
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
            dictatePro: ACTIVE_PRO,
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
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
            dictatePro: ACTIVE_PRO,
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
          }),
        };
      }
      if (path === "/api/update-status") {
        return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
      }
      if (path === "/api/pro/devices") return { ok: true, json: async () => ({ devices: [] }) };
      return { ok: true, json: async () => ({}) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("Dictate account and status"));
    fireEvent.click(screen.getByRole("button", { name: "Beta" }));

    await waitFor(() => expect(screen.getByText("Beta updates selected")).toBeInTheDocument());
    expect(screen.getByText("2026.7.4-unstable.52.1")).toBeInTheDocument();
  });

  it("shows an offline sync status when the last sync could not reach the service", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
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
            updateChannel: "unstable",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            device: { device: "cuda", compute: "float16" },
            history: [],
            dictatePro: ACTIVE_PRO,
            sync: {
              enabled: true,
              accountId: "acct_1",
              deviceId: "dev_1",
              keyAvailable: true,
              lastSeq: 4,
              lastResult: { error: "sync push failed: network unreachable" },
            },
          }),
        };
      }
      if (path === "/api/pro/devices") return { ok: true, json: async () => ({ devices: [] }) };
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("Dictate account and status"));

    expect(screen.getByText("Not connected")).toBeInTheDocument();
  });

  it("shows action needed when encrypted sync is enabled but the local key is missing", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
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
            updateChannel: "unstable",
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            device: { device: "cuda", compute: "float16" },
            history: [],
            dictatePro: ACTIVE_PRO,
            sync: { enabled: true, accountId: "acct_1", deviceId: "dev_1", keyAvailable: false, lastSeq: 4 },
          }),
        };
      }
      if (path === "/api/pro/devices") return { ok: true, json: async () => ({ devices: [] }) };
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));
    fireEvent.click(screen.getByLabelText("Dictate account and status"));

    expect(screen.getByText("Not connected")).toBeInTheDocument();
    expect(screen.getByText("Action needed")).toBeInTheDocument();
    expect(screen.getByText("The encryption key is missing from this device.")).toBeInTheDocument();
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

  it("keeps a completed local meeting accessible in Dictations", async () => {
    render(<App />);
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

  it("provider-degraded SSE loudly persists the on-device model", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
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

    // Privacy toggle is genuinely Local and the model change is persisted.
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(document.querySelector(".privpill.degraded")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchSpy.mock.calls.some(([, opts]) =>
      String(opts?.body || "").includes("parakeet-tdt-0.6b-v2")
    )).toBe(true));

    // Mic remains functional (recording still active)
    expect(screen.getByLabelText("Pause recording")).toBeInTheDocument();
  });

  it("ignores late provider recovery after fallback persisted Local", async () => {
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

    expect(screen.queryByText(/Back online/)).not.toBeInTheDocument();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    // Home screen is still reachable (mic not disabled)
    expect(screen.getByLabelText("Start recording")).toBeInTheDocument();
  });

  it("hydrated degradation is persisted as Local before recording starts", async () => {
    const sources = [];
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() { sources.push(this); }
      close() {}
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        history: [],
        providerHealth: { healthy: false, status: "unreachable", mode: "online", degraded: true, reason: "unreachable", active: "faster-whisper" },
      }),
    });

    render(<App />);
    await waitFor(() => expect(sources).toHaveLength(1));

    // Start recording after hydration has committed the Local model.
    act(() => {
      sources[0].onmessage({
        data: JSON.stringify({ type: "note-recording", active: true }),
      });
    });

    await waitFor(() => expect(fetchSpy.mock.calls.some(([, opts]) =>
      String(opts?.body || "").includes("parakeet-tdt-0.6b-v2")
    )).toBe(true));
    expect(document.querySelector(".privpill.degraded")).not.toBeInTheDocument();
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText("Pause recording")).toBeInTheDocument();
  });

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
            dictatePro: { signedIn: false, account: null },
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
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
    expect(await screen.findByRole("button", { name: /Restarting/i }, { timeout: 3000 })).toBeInTheDocument();
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
            dictatePro: { signedIn: false, account: null },
            sync: { enabled: false, accountId: null, deviceId: "dev_1", keyAvailable: false, lastSeq: 0 },
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
