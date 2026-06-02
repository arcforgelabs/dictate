import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import TitleBar from "../platform/TitleBar.jsx";

afterEach(cleanup);

describe("per-OS window chrome", () => {
  it("GNOME shows a single round close control", () => {
    const { container } = render(<TitleBar platform="gnome" onSearch={() => {}} />);
    expect(container.querySelector(".adw")).toBeTruthy();
    expect(container.querySelectorAll(".adw button")).toHaveLength(1);
  });

  it("KDE/Breeze shows minimize, maximize and close", () => {
    const { container } = render(<TitleBar platform="kde" onSearch={() => {}} />);
    expect(container.querySelector(".breeze")).toBeTruthy();
    expect(container.querySelectorAll(".breeze button")).toHaveLength(3);
  });

  it("Windows shows the caption cluster", () => {
    const { container } = render(<TitleBar platform="win11" onSearch={() => {}} />);
    expect(container.querySelectorAll(".wincaps button")).toHaveLength(3);
  });

  it("macOS shows native-style traffic lights, no custom cluster", () => {
    const { container } = render(<TitleBar platform="mac" onSearch={() => {}} />);
    expect(container.querySelector(".lights")).toBeTruthy();
    expect(container.querySelector(".adw")).toBeNull();
    expect(container.querySelector(".wincaps")).toBeNull();
  });
});
