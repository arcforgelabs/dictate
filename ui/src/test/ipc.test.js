import { describe, it, expect, afterEach } from "vitest";
import { ipc, isLive } from "../ipc.js";

afterEach(() => {
  delete window.__DICTATE__;
  delete window.__TAURI__;
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
});
