import { describe, expect, it } from "vitest";

import { placementRenderGeometry } from "./legoRenderGeometry";
import type { LegoModel } from "./schemas/legoModels";

const model = {
  partCount: 1,
  dimensions: { widthStuds: 8, depthStuds: 6, heightBricks: 3, widthMm: 64, depthMm: 48, heightMm: 28.8 },
  metadata: { algorithmVersion: "v1", sourceSha256: "a", targetParts: 1, occupiedCellCount: 1, gridSize: { widthStuds: 8, depthStuds: 6, heightBricks: 3 }, candidateCount: 1, occupancyMode: "surface" },
  placements: [],
} satisfies LegoModel;

describe("placementRenderGeometry", () => {
  it("maps 0-degree footprint and centers a brick without changing its source", () => {
    const placement: LegoModel["placements"][number] = { brickType: "brick_2x4", dimensions: { lengthStuds: 4, widthStuds: 2, heightBricks: 1 }, position: { x: 2, y: 1, z: 1 }, orientationDegrees: 0, color: "gray" };
    expect(placementRenderGeometry(placement, model)).toEqual({ size: [4, 1.2, 2], center: [0, 0, -1] });
    expect(placement.position).toEqual({ x: 2, y: 1, z: 1 });
  });

  it("swaps the footprint for 90 degrees and preserves brick-height scaling", () => {
    const placement: LegoModel["placements"][number] = { brickType: "brick_2x4", dimensions: { lengthStuds: 4, widthStuds: 2, heightBricks: 2 }, position: { x: 1, y: 2, z: 0 }, orientationDegrees: 90, color: "gray" };
    const rendered = placementRenderGeometry(placement, model);
    expect(rendered.size).toEqual([2, 2.4, 4]);
    expect(rendered.center[0]).toBe(-2);
    expect(rendered.center[1]).toBeCloseTo(-0.6);
    expect(rendered.center[2]).toBe(1);
  });
});
