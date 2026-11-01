import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectStatusFilter } from "./ProjectStatusFilter";

afterEach(cleanup);

describe("ProjectStatusFilter", () => {
  it("marks the selected option and returns the chosen status", () => {
    const onChange = vi.fn();
    render(<ProjectStatusFilter value="photo_ready" onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: "Filter projects" });
    expect(trigger).toHaveTextContent("Photo ready");
    fireEvent.click(trigger);
    const selected = screen.getByRole("menuitemradio", { name: "Photo ready" });
    expect(selected).toHaveAttribute("aria-checked", "true");
    expect(selected).toHaveFocus();
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Generating" }));
    expect(onChange).toHaveBeenCalledWith("generating");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("supports arrow keys, Home, End, and Escape without changing the filter", () => {
    const onChange = vi.fn();
    render(<ProjectStatusFilter value="all" onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: "Filter projects" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const menu = screen.getByRole("menu");
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitemradio", { name: "Needs photo" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "End" });
    expect(screen.getByRole("menuitemradio", { name: "Failed" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Home" });
    expect(screen.getByRole("menuitemradio", { name: "All projects" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(screen.getByRole("menuitemradio", { name: "Failed" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("dismisses on outside clicks without changing the filter", () => {
    const onChange = vi.fn();
    render(<ProjectStatusFilter value="all" onChange={onChange} />);
    const trigger = screen.getByRole("button", { name: "Filter projects" });
    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(onChange).not.toHaveBeenCalled();
  });
});
