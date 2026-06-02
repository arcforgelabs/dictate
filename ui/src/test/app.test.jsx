import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, within, cleanup } from "@testing-library/react";
import App from "../App.jsx";

afterEach(cleanup);

// Click a sidebar nav entry by its label, scoped to the rail so it never
// collides with same-named mini-cards or badges elsewhere on the page.
function navTo(container, label) {
  const nav = container.querySelector(".nav");
  fireEvent.click(within(nav).getByText(label));
}

describe("Quiet Console app (mock mode)", () => {
  it("renders the Status view by default", () => {
    render(<App />);
    expect(screen.getByText("Ready to dictate")).toBeInTheDocument();
    expect(screen.getByText("Hold to try dictation")).toBeInTheDocument();
  });

  it("navigates to the Model view and lists all four providers", () => {
    const { container } = render(<App />);
    navTo(container, "Model");
    expect(screen.getByText("Transcription model")).toBeInTheDocument();
    expect(screen.getByText("faster-whisper · turbo")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini-transcribe")).toBeInTheDocument();
    expect(screen.getByText("grok-speech-to-text")).toBeInTheDocument();
    expect(screen.getByText("gemini-3-flash-preview")).toBeInTheDocument();
  });

  it("adds and removes a hotword", () => {
    const { container } = render(<App />);
    navTo(container, "Hotwords");
    const input = screen.getByPlaceholderText("Add a word…");
    fireEvent.change(input, { target: { value: "Kubernetes" } });
    fireEvent.click(screen.getByText("Add word"));
    expect(screen.getByText("Kubernetes")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Remove Kubernetes"));
    expect(screen.queryByText("Kubernetes")).not.toBeInTheDocument();
  });

  it("toggles the theme via the rail button", () => {
    render(<App />);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    fireEvent.click(screen.getByTitle("Toggle theme"));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("wears GNOME chrome by default (close-only control)", () => {
    const { container } = render(<App />);
    expect(container.querySelector(".win")).toHaveClass("gnome");
    expect(container.querySelector(".adw")).toBeInTheDocument();
    expect(container.querySelector(".wincaps")).toBeNull();
  });

  it("opens the command palette with the title-bar search", () => {
    render(<App />);
    fireEvent.click(screen.getByText("Search settings & actions"));
    expect(screen.getByPlaceholderText(/Jump to a setting/i)).toBeInTheDocument();
  });
});
