import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InspirationCarousel } from "./InspirationCarousel";

function mockMotionPreference(reduced: boolean) {
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: reduced,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })));
}

describe("InspirationCarousel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMotionPreference(false);
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("automatically cycles through all three images and loops", () => {
    render(<InspirationCarousel />);
    expect(screen.getAllByRole("img")).toHaveLength(1);
    expect(screen.getByRole("group", { name: "1 of 3" })).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("group", { name: "2 of 3" })).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("group", { name: "3 of 3" })).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByRole("group", { name: "1 of 3" })).toBeInTheDocument();
    const track = screen.getByRole("group", { name: "1 of 3" }).parentElement;
    // Continue forward to the end copy, then silently reset to its identical original.
    expect(track).toHaveStyle({ transform: "translateX(calc(-400% + 0px))" });
    act(() => { vi.advanceTimersByTime(550); });
    expect(track).toHaveStyle({ transform: "translateX(calc(-100% + 0px))", transitionProperty: "none" });
    act(() => { vi.advanceTimersByTime(2450); });
    expect(screen.getByRole("group", { name: "2 of 3" })).toBeInTheDocument();
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
  });

  it("loops backwards from the first image without traversing the other slides", () => {
    render(<InspirationCarousel />);
    const viewport = screen.getByLabelText("Drag to change image, or use the left and right arrow keys");
    fireEvent.keyDown(viewport, { key: "ArrowLeft" });
    const track = screen.getByRole("group", { name: "3 of 3" }).parentElement;
    expect(track).toHaveStyle({ transform: "translateX(calc(-0% + 0px))" });
    act(() => { vi.advanceTimersByTime(550); });
    expect(track).toHaveStyle({ transform: "translateX(calc(-300% + 0px))", transitionProperty: "none" });
  });

  it("supports dragging both directions and restarts the automatic countdown", () => {
    const { unmount } = render(<InspirationCarousel />);
    const viewport = screen.getByLabelText("Drag to change image, or use the left and right arrow keys");
    viewport.setPointerCapture = vi.fn();
    function pointer(type: string, x: number) {
      const event = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: 100, button: 0 });
      Object.defineProperties(event, {
        pointerId: { value: 1 }, pointerType: { value: "mouse" }, isPrimary: { value: true },
      });
      fireEvent(viewport, event);
    }
    act(() => { vi.advanceTimersByTime(1500); });
    pointer("pointerdown", 250);
    pointer("pointermove", 100);
    pointer("pointerup", 100);
    expect(screen.getByRole("group", { name: "2 of 3" })).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1500); });
    expect(screen.getByRole("group", { name: "2 of 3" })).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(1500); });
    expect(screen.getByRole("group", { name: "3 of 3" })).toBeInTheDocument();
    pointer("pointerdown", 100);
    pointer("pointerup", 250);
    expect(screen.getByRole("group", { name: "2 of 3" })).toBeInTheDocument();
    pointer("pointerdown", 100);
    pointer("pointerup", 110);
    expect(screen.getByRole("group", { name: "2 of 3" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
  it("does not auto-rotate when reduced motion is requested", () => {
    mockMotionPreference(true);
    render(<InspirationCarousel />);
    act(() => { vi.advanceTimersByTime(15000); });
    expect(screen.getByRole("group", { name: "1 of 3" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause slideshow" })).not.toBeInTheDocument();
  });
});
