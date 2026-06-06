import { describe, it, expect, afterEach, vi } from "vitest";
import { ipc, isLive } from "../ipc.js";

afterEach(() => {
  delete window.__DICTATE__;
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("ipc bridge", () => {
  it("reports not-live without an injected bridge", () => {
    expect(isLive()).toBe(false);
    expect(ipc.isLive()).toBe(false);
  });

  it("defaults to a Linux (gnome) platform in the browser", () => {
    expect(ipc.platform()).toBe("gnome");
  });

  it("reads the injected platform when live", () => {
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "kde" };
    expect(ipc.isLive()).toBe(true);
    expect(ipc.platform()).toBe("kde");
  });

  it("windowControl is a no-op (false) without Tauri", async () => {
    expect(await ipc.windowControl("close")).toBe(false);
  });

  it("subscribe returns a no-op unsubscribe without a bridge", () => {
    const unsub = ipc.subscribe(() => {});
    expect(typeof unsub).toBe("function");
    expect(() => unsub()).not.toThrow();
  });

  it("refreshes the bridge and retries when the server port is stale", async () => {
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "old", platform: "gnome" };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:2",
          token: "new",
          platform: "gnome",
        }),
      },
    };
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("connection refused"))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      });

    await expect(ipc.getState()).resolves.toEqual({ ok: true });
    expect(window.__TAURI__.core.invoke).toHaveBeenCalledWith("refresh_bridge");
    expect(globalThis.fetch).toHaveBeenLastCalledWith(
      "http://127.0.0.1:2/api/state",
      expect.objectContaining({
        headers: { Authorization: "Bearer new" },
      }),
    );
  });

  it("refreshes the bridge and retries stale-token 401 responses", async () => {
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "old", platform: "gnome" };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn().mockResolvedValue({
          baseUrl: "http://127.0.0.1:1",
          token: "new",
          platform: "gnome",
        }),
      },
    };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        statusText: "Unauthorized",
        json: async () => ({ error: "unauthorized" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ saved: true }),
      });

    await expect(ipc.patchConfig({ prefs: { theme: "dark" } })).resolves.toEqual({ saved: true });
    expect(globalThis.fetch).toHaveBeenLastCalledWith(
      "http://127.0.0.1:1/api/config",
      expect.objectContaining({
        method: "PATCH",
        headers: { Authorization: "Bearer new", "Content-Type": "application/json" },
      }),
    );
  });
});
