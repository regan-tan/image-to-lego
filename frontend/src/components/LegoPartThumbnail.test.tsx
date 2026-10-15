import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { generatedPartRenderGeometry, rectangularStudRenderPositions } from "../legoRenderGeometry";
import type { LegoPartGroup } from "../legoPartsList";
import { LegoPartThumbnail, partThumbnailRenderInput } from "./LegoPartThumbnail";

function part(overrides: Partial<LegoPartGroup> = {}): LegoPartGroup {
  return {
    brickType: "brick_2x4",
    partId: "3001",
    partName: "Brick 2 x 4",
    geometryAsset: "3001",
    lengthStuds: 4,
    widthStuds: 2,
    heightPlates: 3,
    color: "red",
    colorId: "ldraw:4",
    colorName: "Red",
    colorHex: "#C91A09",
    quantity: 2,
    ...overrides,
  };
}

describe("partThumbnailRenderInput", () => {
  it("preserves the grouped catalogue identity and canonical color for the shared renderer", () => {
    const renderInput = partThumbnailRenderInput(part());

    expect(renderInput?.placement).toEqual(expect.objectContaining({
      partId: "3001",
      geometryAsset: "3001",
      color: "red",
      colorId: "ldraw:4",
      colorHex: "#C91A09",
      orientationDegrees: 0,
    }));
    expect(renderInput && generatedPartRenderGeometry(renderInput.placement, renderInput.model)).not.toBeNull();
  });

  it("uses the existing rectangular geometry when no detailed asset exists", () => {
    const renderInput = partThumbnailRenderInput(part({ partId: "3002", geometryAsset: undefined, lengthStuds: 3 }));

    expect(renderInput && generatedPartRenderGeometry(renderInput.placement, renderInput.model)).toBeNull();
    expect(renderInput && rectangularStudRenderPositions(renderInput.placement, renderInput.model)).toHaveLength(6);
  });

  it("returns identical rendering inputs for the same part and color", () => {
    expect(partThumbnailRenderInput(part())).toEqual(partThumbnailRenderInput(part()));
  });

  it("shows an exact-ID placeholder instead of substituting a part when a thumbnail cannot be constructed", () => {
    const incompletePart = part({ partId: "unknown-999", lengthStuds: 0 });

    expect(partThumbnailRenderInput(incompletePart)).toBeNull();
    render(<LegoPartThumbnail part={incompletePart} />);
    expect(screen.getByTestId("lego-part-thumbnail-unavailable")).toHaveAttribute("data-part-id", "unknown-999");
    expect(screen.getByRole("img", { name: "unknown-999 thumbnail unavailable" })).toBeInTheDocument();
  });
});
