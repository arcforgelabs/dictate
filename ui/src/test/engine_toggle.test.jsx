import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import App from "../App.jsx";

afterEach(() => { cleanup(); delete window.__DICTATE__; delete window.EventSource; vi.restoreAllMocks(); });

const ACTIVE_PRO = {
  signedIn: true,
  entitlements: { active: true, display_name: "Dictate Pro", status: "active" },
};

describe("Language toggle", () => {
  it("shows English and cloud-only Multilingual actions in private mode", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "English" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Multilingual" })).toBeTruthy();
  });

  it("keeps English selected when a stale whisperx config is hydrated in private mode", async () => {
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() {}
      close() {}
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts = {}) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            model: { id: "whisperx/large-v3" },
            history: [],
            providers: { xai: { configured: false } },
            dictatePro: { signedIn: false },
          }),
        };
      }
      if (path === "/api/config" && opts.method === "PATCH") {
        return { ok: true, json: async () => ({}) };
      }
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });

    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: "English" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("button", { name: "Multilingual" })).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: "English" }));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith(
      "http://127.0.0.1:1/api/config",
      expect.objectContaining({
        method: "PATCH",
      }),
    ));
    expect(fetchSpy.mock.calls.some(([, opts]) => String(opts?.body || "").includes("parakeet-tdt-0.6b-v2"))).toBe(true);
  });

  it("allows cloud mode when Pro is active without a personal xAI key", async () => {
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    window.EventSource = class {
      constructor() {}
      close() {}
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, opts = {}) => {
      const path = String(url).replace("http://127.0.0.1:1", "");
      if (path === "/api/state") {
        return {
          ok: true,
          json: async () => ({
            model: { id: "parakeet/parakeet-tdt-0.6b-v2" },
            history: [],
            providers: { xai: { configured: false } },
            dictatePro: ACTIVE_PRO,
          }),
        };
      }
      if (path === "/api/config" && opts.method === "PATCH") {
        return { ok: true, json: async () => ({}) };
      }
      return { ok: true, json: async () => ({ updateAvailable: false, checked: true }) };
    });

    render(<App />);
    await waitFor(() => expect(screen.getByRole("button", { name: "English" })).toHaveAttribute("aria-pressed", "true"));

    fireEvent.click(screen.getByRole("button", { name: "Multilingual" }));

    expect(await screen.findByText("Multilingual is available in Cloud mode only.")).toBeTruthy();
    await waitFor(() => expect(fetchSpy.mock.calls.some(([, opts]) => String(opts?.method) === "PATCH")).toBe(true));
    expect(fetchSpy.mock.calls.some(([, opts]) => String(opts?.body || "").includes("grok-speech-to-text"))).toBe(true);
  });

  it("keeps English selected for the bundled local engine", () => {
    render(<App />);
    const en = screen.getByRole("button", { name: "English" }).getAttribute("aria-pressed");
    const multi = screen.getByRole("button", { name: "Multilingual" }).getAttribute("aria-pressed");
    expect(en).toBe("true");
    expect(multi).toBe("false");
  });

  it("clicking Multilingual shows the cloud-only toast and keeps the sign-in flow intact", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Multilingual" }));

    expect(await screen.findByText("Multilingual is available in Cloud mode only.")).toBeTruthy();
    expect(screen.getByText("Cloud mode requires an active Dictate Pro subscription or personal xAI API key.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "English" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Multilingual" }).getAttribute("aria-pressed")).toBe("false");
  });
});
