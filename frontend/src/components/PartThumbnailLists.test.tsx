import { render, screen, within } from "@testing-library/react";
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
