import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import App from "../App.jsx";

afterEach(() => { cleanup(); delete window.__DICTATE__; vi.restoreAllMocks(); });

describe("Local engine toggle (English/Multilingual)", () => {
  it("shows English + Multilingual options in private mode", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "English" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Multilingual" })).toBeTruthy();
  });

  it("exactly one option is selected, reflecting the active backend", () => {
    render(<App />);
    const en = screen.getByRole("button", { name: "English" }).getAttribute("aria-pressed");
    const multi = screen.getByRole("button", { name: "Multilingual" }).getAttribute("aria-pressed");
    // Mutually exclusive; the default fresh/mock state is faster-whisper → Multilingual.
    expect([en, multi].filter((v) => v === "true")).toHaveLength(1);
    expect(multi).toBe("true");
  });

  it("clicking English switches selection to the English engine", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByRole("button", { name: "English" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Multilingual" }).getAttribute("aria-pressed")).toBe("false");
  });
});
