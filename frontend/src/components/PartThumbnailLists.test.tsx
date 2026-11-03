import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { deriveLegoBuildSteps } from "../legoBuildInstructions";
import { createLegoPartsList, type LegoPartGroup } from "../legoPartsList";
import type { LegoModel } from "../schemas/legoModels";
import { BuildGuideWorkspace } from "./BuildGuideWorkspace";
import { PartsListWorkspace } from "./PartsListWorkspace";

vi.mock("./LegoPartThumbnail", () => ({
  LegoPartThumbnail: ({ part }: { part: LegoPartGroup }) => (
    <div data-testid="lego-part-thumbnail" data-part-id={part.partId} data-color={part.colorHex ?? part.color} />
  ),
}));

vi.mock("./LegoModelViewer", () => ({
  default: () => <div data-testid="lego-model-viewer" />,
}));

function placement(partId: string, color: string, z: number): LegoModel["placements"][number] {
  return {
    brickType: "brick_2x4",
    partId,
    partName: `Brick ${partId}`,
    geometryAsset: partId === "3001" ? "3001" : undefined,
    dimensions: { lengthStuds: 4, widthStuds: 2, heightPlates: 3 },
    position: { x: 0, y: 0, z },
    orientationDegrees: 0,
    color,
    colorId: color === "red" ? "ldraw:4" : "ldraw:1",
    colorHex: color === "red" ? "#C91A09" : "#0055BF",
  };
}

function model(): LegoModel {
  const placements = [placement("3001", "red", 0), placement("3020", "blue", 1), placement("3020", "blue", 1)];
  return {
    partCount: placements.length,
    dimensions: { widthStuds: 4, depthStuds: 2, heightPlates: 6, widthMm: 32, depthMm: 16, heightMm: 19.2 },
    metadata: {
      algorithmVersion: "test",
      sourceSha256: "test",
      occupiedCellCount: 1,
      gridSize: { widthStuds: 4, depthStuds: 2, heightPlates: 6 },
      candidateCount: 1,
      occupancyMode: "test",
    },
    placements,
  };
}

describe("part thumbnail list integration", () => {
  it("adds an exact part/color thumbnail to each aggregated parts-list row without changing quantity", () => {
    const partsList = createLegoPartsList(model());
    render(<PartsListWorkspace partsList={partsList} />);

    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]!).getByTestId("lego-part-thumbnail")).toHaveAttribute("data-part-id", "3020");
    expect(within(rows[1]!).getByTestId("lego-part-thumbnail")).toHaveAttribute("data-color", "#0055BF");
    expect(within(rows[1]!).getByText("2")).toBeInTheDocument();
    expect(within(rows[2]!).getByTestId("lego-part-thumbnail")).toHaveAttribute("data-part-id", "3001");
  });

  it("keeps all part types in the independently scrollable inventory table", () => {
    const placements = Array.from({ length: 19 }, (_, index) => placement(`part-${index + 1}`, "red", index));
    const partsList = createLegoPartsList({ ...model(), partCount: placements.length, placements });
    render(<PartsListWorkspace partsList={partsList} />);

    const inventory = screen.getAllByRole("region", { name: "Parts inventory" }).at(-1);
    expect(inventory).toBeDefined();
    const rows = within(inventory!).getAllByRole("row");
    expect(rows).toHaveLength(20);
    expect(within(rows.at(-1)!).getByText("part-19")).toBeInTheDocument();
  });

  it("keeps one inventory export and shows verification guidance in a dismissible tooltip", () => {
    const partsList = createLegoPartsList(model());
    const { container } = render(
      <PartsListWorkspace
        partsList={partsList}
        algorithmVersion="surface-grid-v3"
        partColorVerificationVersion="catalogue-v1"
      />,
    );

    const view = within(container);
    expect(view.queryByRole("button", { name: "Download purchase-ready CSV" })).not.toBeInTheDocument();
    expect(view.getAllByRole("button", { name: "Download parts list (.csv)" })).toHaveLength(1);
    expect(view.getByRole("button", { name: "Download parts list (.csv)" })).toBeEnabled();
    expect(view.queryByRole("tooltip")).not.toBeInTheDocument();

    const info = view.getByRole("button", { name: "About parts list verification" });
    fireEvent.mouseEnter(info);
    expect(view.getByRole("tooltip")).toHaveTextContent("The CSV includes the complete model inventory");
    expect(view.getByRole("tooltip")).toHaveTextContent("does not confirm current availability, stock, pricing, or sellers");
    expect(view.getByRole("tooltip")).toHaveTextContent("additional verification");
    fireEvent.mouseLeave(info);
    expect(view.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.focus(info);
    expect(info).toHaveAttribute("aria-describedby", view.getByRole("tooltip").id);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(view.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.click(info);
    expect(view.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    expect(view.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("edits the step number, validates the range, and supports cancellation", () => {
    const buildModel = model();
    const steps = deriveLegoBuildSteps(buildModel);
    const onStepChange = vi.fn();
    const { container, unmount } = render(<BuildGuideWorkspace model={buildModel} steps={steps} currentStepIndex={0} onStepChange={onStepChange} />);
    const view = within(container);
    fireEvent.click(view.getByRole("button", { name: /Step 1. Click to jump/ }));
    const input = view.getByRole("spinbutton", { name: "Step number" });
    expect(input).toHaveFocus();
    fireEvent.change(input, { target: { value: "999" } });
    fireEvent.submit(input.closest("form")!);
    expect(onStepChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "2" } });
    fireEvent.submit(input.closest("form")!);
    expect(onStepChange).toHaveBeenCalledWith(1);
    fireEvent.click(view.getByRole("button", { name: /Step 1. Click to jump/ }));
    fireEvent.keyDown(view.getByRole("spinbutton"), { key: "Escape" });
    expect(view.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(onStepChange).toHaveBeenCalledTimes(1);
    expect(view.queryByRole("slider")).not.toBeInTheDocument();
    unmount();
  });

  it("adds thumbnails only for the selected step's grouped parts", () => {
    const buildModel = model();
    const steps = deriveLegoBuildSteps(buildModel);
    render(<BuildGuideWorkspace model={buildModel} steps={steps} currentStepIndex={1} onStepChange={() => undefined} />);

    const partsPanel = screen.getByRole("heading", { name: "Parts needed this step" }).parentElement;
    expect(partsPanel).not.toBeNull();
    expect(within(partsPanel!).getByTestId("lego-part-thumbnail")).toHaveAttribute("data-part-id", "3020");
    expect(within(partsPanel!).getByText("×2")).toBeInTheDocument();
    expect(within(partsPanel!).queryByText("3001")).not.toBeInTheDocument();
  });
});
