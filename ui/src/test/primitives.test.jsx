import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Toggle, Combo, Chip, Seg } from "../primitives.jsx";

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
});
