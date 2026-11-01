import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BrickProgress } from "./BrickProgress";
import { StatusBadge } from "./StatusBadge";

afterEach(cleanup);

describe("project detail status", () => {
  it("shows Needs photo rather than hiding the initial status", () => {
    render(<StatusBadge status="needs_photo" />);
    expect(screen.getByText("Needs photo")).toBeInTheDocument();
  });

  it("shows current generation even when an older LEGO result is available", () => {
    render(<StatusBadge status="model_ready" conversionStatus="running" legoModelReady />);
    expect(screen.getByText("Generating")).toBeInTheDocument();
    expect(screen.getByText("· LEGO conversion")).toBeInTheDocument();
    expect(screen.queryByText("Model ready")).not.toBeInTheDocument();
  });

  it("identifies a failed conversion and marks the LEGO stage as failed", () => {
    render(<><StatusBadge status="model_ready" conversionStatus="failed" legoModelReady /><BrickProgress status="model_ready" conversionStatus="failed" /></>);
    expect(screen.getByText("Failed")).toBeInTheDocument();
    const stages = within(screen.getByRole("list", { name: "Progress" })).getAllByRole("listitem");
    expect(stages[2]).toHaveAttribute("aria-current", "step");
    expect(stages[2]).toHaveAttribute("data-status", "failed");
    expect(stages[2]).toHaveTextContent("failed");
  });

  it("uses Model ready without extra wording for a finished LEGO build", () => {
    render(<StatusBadge status="model_ready" legoModelReady />);
    expect(screen.getByText("Model ready")).toBeInTheDocument();
    expect(screen.queryByText("· LEGO build")).not.toBeInTheDocument();
  });
});
