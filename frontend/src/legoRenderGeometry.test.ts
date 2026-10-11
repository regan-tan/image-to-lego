import { describe, expect, it } from "vitest";

import { placementRenderGeometry, slopeRenderGeometry } from "./legoRenderGeometry";
import { legoModelSchema, type LegoModel } from "./schemas/legoModels";

const model = {
  partCount: 1,
  dimensions: { widthStuds: 8, depthStuds: 6, heightBricks: 3, widthMm: 64, depthMm: 48, heightMm: 28.8 },
  metadata: { algorithmVersion: "v1", sourceSha256: "a", targetParts: 1, occupiedCellCount: 1, gridSize: { widthStuds: 8, depthStuds: 6, heightBricks: 3 }, candidateCount: 1, occupancyMode: "surface" },
  placements: [],
} satisfies LegoModel;

describe("placementRenderGeometry", () => {
  it("accepts legacy brick-height artifacts", () => {
    expect(legoModelSchema.parse(model)).toEqual(model);
  });

  it("maps 0-degree footprint and centers a brick without changing its source", () => {
    const placement: LegoModel["placements"][number] = { brickType: "brick_2x4", dimensions: { lengthStuds: 4, widthStuds: 2, heightBricks: 1 }, position: { x: 2, y: 1, z: 1 }, orientationDegrees: 0, color: "gray" };
    const rendered = placementRenderGeometry(placement, model);
    expect(rendered.size).toEqual([4, expect.closeTo(1.2), 2]);
    expect(rendered.center).toEqual([0, expect.closeTo(0), -1]);
    expect(placement.position).toEqual({ x: 2, y: 1, z: 1 });
  });

  it("swaps the footprint for 90 degrees and preserves brick-height scaling", () => {
    const placement: LegoModel["placements"][number] = { brickType: "brick_2x4", dimensions: { lengthStuds: 4, widthStuds: 2, heightBricks: 2 }, position: { x: 1, y: 2, z: 0 }, orientationDegrees: 90, color: "gray" };
    const rendered = placementRenderGeometry(placement, model);
    expect(rendered.size).toEqual([2, expect.closeTo(2.4), 4]);
    expect(rendered.center[0]).toBe(-2);
    expect(rendered.center[1]).toBeCloseTo(-0.6);
    expect(rendered.center[2]).toBe(1);
  });

  it("renders a one-plate part at one plate layer", () => {
    const plate: LegoModel["placements"][number] = { brickType: "plate_2x4", dimensions: { lengthStuds: 4, widthStuds: 2, heightPlates: 1 }, position: { x: 2, y: 1, z: 1 }, orientationDegrees: 0, color: "blue" };
    const plateModel = { ...model, dimensions: { ...model.dimensions, heightPlates: 4, heightBricks: undefined } };

    const rendered = placementRenderGeometry(plate, plateModel);
    expect(rendered.size).toEqual([4, 0.4, 2]);
    expect(rendered.center).toEqual([0, expect.closeTo(-0.2), -1]);
  });

  it.each([
    [0, [2, -1]],
    [90, [-1, 2]],
    [180, [-1, -1]],
    [270, [-1, -1]],
  ] as const)("places the 4286 high end at %i degrees", (orientationDegrees, expectedHighEnd) => {
    const placement: LegoModel["placements"][number] = {
      brickType: "slope_1x3",
      partId: "4286",
      partName: "Slope 33 3 x 1",
      shape: "slope_33_3x1",
      dimensions: { lengthStuds: 3, widthStuds: 1, heightPlates: 3 },
      position: { x: 3, y: 2, z: 0 },
      orientationDegrees,
      color: "red",
    };

    const rendered = slopeRenderGeometry(placement, model);

    expect([rendered.vertices[6], rendered.vertices[8]]).toEqual(expectedHighEnd);
    expect(rendered.vertices[7]).toBeCloseTo(-0.6);
  });
});
