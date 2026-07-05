import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Toggle, Combo, Chip, Seg, Tooltip } from "../primitives.jsx";

describe("primitives", () => {
  it("Toggle reflects and reports state", () => {
    const onChange = vi.fn();
    const { rerender } = render(<Toggle on={false} onChange={onChange} />);
    const sw = screen.getByRole("switch");
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledWith(true);
    rerender(<Toggle on={true} onChange={onChange} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("Combo renders each key with separators", () => {
    const { container } = render(<Combo keys={["Ctrl", "Shift", "R"]} />);
    expect(container.querySelectorAll(".kbd")).toHaveLength(3);
    expect(container.querySelectorAll(".plus")).toHaveLength(2);
  });

  it("Chip carries the live modifier", () => {
    const { container } = render(<Chip live>LOCAL</Chip>);
    expect(container.querySelector(".chip")).toHaveClass("live");
  });

  it("Seg selects the active option", () => {
    const onChange = vi.fn();
    render(<Seg options={[{ v: "hold", l: "Hold" }, { v: "toggle", l: "Toggle" }]} value="hold" onChange={onChange} />);
    fireEvent.click(screen.getByText("Toggle"));
    expect(onChange).toHaveBeenCalledWith("toggle");
  });

  it("Tooltip positions below trigger and stays visible on hover", () => {
    const { container } = render(
      <div className="win" style={{ width: 400, height: 300 }}>
        <Tooltip label="Private mode">
          <button type="button">Toggle</button>
        </Tooltip>
      </div>
    );
    const wrap = container.querySelector(".tip-wrap");
    const tip = container.querySelector(".tip");
    expect(wrap).not.toHaveClass("show");
    fireEvent.mouseEnter(wrap);
    expect(wrap).toHaveClass("show");
    expect(tip).toBeVisible();
    fireEvent.mouseLeave(wrap);
    expect(wrap).not.toHaveClass("show");
  });

  it("Tooltip hides after click even when the trigger keeps focus", () => {
    const { container } = render(
      <div className="win" style={{ width: 400, height: 300 }}>
        <Tooltip label="Private mode">
          <button type="button">Toggle</button>
        </Tooltip>
      </div>
    );
    const wrap = container.querySelector(".tip-wrap");
    const btn = screen.getByRole("button", { name: "Toggle" });
    fireEvent.mouseEnter(wrap);
    expect(wrap).toHaveClass("show");
    fireEvent.pointerDown(btn);
    expect(wrap).not.toHaveClass("show");
    btn.focus();
    fireEvent.mouseLeave(wrap);
    expect(wrap).not.toHaveClass("show");
  });

  it("Tooltip hides when the label changes", () => {
    const { container, rerender } = render(
      <Tooltip label="Private mode">
        <button type="button">Toggle</button>
      </Tooltip>
    );
    const wrap = container.querySelector(".tip-wrap");
    fireEvent.mouseEnter(wrap);
    expect(wrap).toHaveClass("show");
    rerender(
      <Tooltip label="Cloud mode">
        <button type="button">Toggle</button>
      </Tooltip>
    );
    expect(wrap).not.toHaveClass("show");
  });
});
