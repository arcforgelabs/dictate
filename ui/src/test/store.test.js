import { describe, it, expect, vi, afterEach } from "vitest";
import { formatHistoryTime } from "../store.jsx";

afterEach(() => {
  vi.useRealTimers();
});

describe("formatHistoryTime", () => {
  it("renders just-now labels from raw timestamps", () => {
    vi.setSystemTime(new Date("2026-06-03T12:00:30Z"));
    expect(formatHistoryTime("2026-06-03T12:00:00Z")).toMatch(/just now$/);
  });

  it("ages minute and hour labels without server strings", () => {
    vi.setSystemTime(new Date("2026-06-03T13:05:00Z"));
    expect(formatHistoryTime("2026-06-03T13:03:00Z")).toMatch(/2m ago$/);
    expect(formatHistoryTime("2026-06-03T11:00:00Z")).toMatch(/2h ago$/);
  });
});
