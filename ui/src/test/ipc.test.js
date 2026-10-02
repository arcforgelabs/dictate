import { describe, it, expect, afterEach, vi } from "vitest";
import { ipc, isLive, isMockMode } from "../ipc.js";

afterEach(() => {
  delete window.__DICTATE__;
  delete window.__TAURI__;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("ipc bridge", () => {
  it("reports not-live without an injected bridge", () => {
    expect(isLive()).toBe(false);
    expect(ipc.isLive()).toBe(false);
  });

  it("allows mock mode in browser tests without an injected shell", () => {
    expect(isMockMode()).toBe(true);
    expect(ipc.isMockMode()).toBe(true);
  });

  it("disables mock mode when only Tauri is present", () => {
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    expect(ipc.isLive()).toBe(false);
    expect(ipc.isShell()).toBe(true);
    expect(ipc.isMockMode()).toBe(false);
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

  it("keeps asking the shell for a bridge until a slow engine comes up", async () => {
    vi.useFakeTimers();
    window.__DICTATE__ = { platform: "win11" };
    const invoke = vi.fn()
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({ baseUrl: "http://127.0.0.1:3", token: "late", platform: "win11" });
    window.__TAURI__ = { core: { invoke } };
    const onLive = vi.fn();

    ipc.waitForBridge(onLive, 1000);
    await vi.advanceTimersByTimeAsync(0);
    expect(onLive).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2000);

    expect(invoke).toHaveBeenCalledTimes(3);
    expect(onLive).toHaveBeenCalledTimes(1);
    expect(ipc.isLive()).toBe(true);
    expect(window.__DICTATE__).toMatchObject({ baseUrl: "http://127.0.0.1:3", token: "late", platform: "win11" });
  });

  it("stops waiting for a bridge once cancelled", async () => {
    vi.useFakeTimers();
    window.__DICTATE__ = { platform: "win11" };
    const invoke = vi.fn().mockResolvedValue(null);
    window.__TAURI__ = { core: { invoke } };
    const onLive = vi.fn();

    const cancel = ipc.waitForBridge(onLive, 1000);
    await vi.advanceTimersByTimeAsync(0);
    cancel();
    await vi.advanceTimersByTimeAsync(5000);

    expect(invoke).toHaveBeenCalledTimes(1);
    expect(onLive).not.toHaveBeenCalled();
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

  it("reconnects to the restarted engine and re-hydrates when the stream drops", async () => {
    vi.useFakeTimers();
    const streams = [];
    class FakeEventSource {
      constructor(url) {
        this.url = url;
        streams.push(this);
      }
      close() {
        this.closed = true;
      }
    }
    vi.stubGlobal("EventSource", FakeEventSource);
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

    const onReconnect = vi.fn();
    const unsub = ipc.subscribe(() => {}, onReconnect);

    // Initial stream on the original engine; first open must NOT fire onReconnect.
    expect(streams).toHaveLength(1);
    expect(streams[0].url).toContain("http://127.0.0.1:1/api/events");
    streams[0].onopen();
    expect(onReconnect).not.toHaveBeenCalled();

    // Engine restarts → stream errors → re-resolve bridge and reopen on the new port.
    streams[0].onerror();
    await vi.advanceTimersByTimeAsync(1000);
    expect(window.__TAURI__.core.invoke).toHaveBeenCalledWith("refresh_bridge");
    expect(streams).toHaveLength(2);
    expect(streams[1].url).toContain("http://127.0.0.1:2/api/events");
    expect(streams[1].url).toContain("token=new");

    // Reopen fires onReconnect so the caller can re-sync missed state.
    streams[1].onopen();
    expect(onReconnect).toHaveBeenCalledTimes(1);

    unsub();
    expect(streams[1].closed).toBe(true);
  });

  it("starts the update flow through the authenticated backend route", async () => {
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => ({ mode: "release", url: "https://example.test/releases" }),
    });

    await expect(ipc.startUpdate()).resolves.toEqual({
      mode: "release",
      url: "https://example.test/releases",
    });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:1/api/update",
      expect.objectContaining({
        method: "POST",
        headers: { Authorization: "Bearer t" },
      }),
    );
  });

  it("starts and stops meetings through authenticated backend routes", async () => {
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ recording: true, mode: "meeting" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ recording: false, mode: "meeting" }),
      });

    await expect(ipc.startMeetingRecording()).resolves.toEqual({ recording: true, mode: "meeting" });
    await expect(ipc.stopMeetingRecording()).resolves.toEqual({ recording: false, mode: "meeting" });
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:1/api/meetings/start",
      expect.objectContaining({ method: "POST", headers: { Authorization: "Bearer t" } }),
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:1/api/meetings/stop",
      expect.objectContaining({ method: "POST", headers: { Authorization: "Bearer t" } }),
    );
  });

  it("exports local data through the authenticated backend route", async () => {
    window.__DICTATE__ = { baseUrl: "http://127.0.0.1:1", token: "t", platform: "gnome" };
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => ({ schema: "dictate.local-export.v1" }),
    });

    await expect(ipc.exportLocalData()).resolves.toEqual({ schema: "dictate.local-export.v1" });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:1/api/local/export",
      expect.objectContaining({ method: "GET", headers: { Authorization: "Bearer t" } }),
    );
  });
});
