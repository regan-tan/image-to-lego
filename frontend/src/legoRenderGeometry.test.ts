import { describe, expect, it } from "vitest";
import { BufferAttribute, BufferGeometry } from "three";

import {
  generatedPartRenderGeometry,
  placementRenderGeometry,
  rectangularStudRenderPositions,
} from "./legoRenderGeometry";
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

  it("renders 3001 through the generated geometry path", () => {
    const placement: LegoModel["placements"][number] = {
      brickType: "brick_2x4",
      partId: "3001",
      geometryAsset: "3001",
      dimensions: { lengthStuds: 4, widthStuds: 2, heightPlates: 3 },
      position: { x: 2, y: 1, z: 0 },
      orientationDegrees: 0,
      color: "blue",
    };

    const rendered = generatedPartRenderGeometry(placement, model);

    expect(rendered).not.toBeNull();
    expect(rendered?.vertices.length).toBeGreaterThan(0);
    expect(rendered?.indices.length).toBeGreaterThan(0);
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new BufferAttribute(rendered!.vertices, 3));
    geometry.setIndex(new BufferAttribute(rendered!.indices, 1));
    expect(geometry.getAttribute("position").count).toBe(rendered!.vertices.length / 3);
    geometry.dispose();
  });

  it.each([
    [0, [-1, -1]],
    [90, [-1, -1]],
    [180, [2, -1]],
    [270, [-1, 2]],
  ] as const)("transforms the 4286 local origin at %i degrees", (orientationDegrees, expectedOrigin) => {
    const placement: LegoModel["placements"][number] = {
      brickType: "slope_1x3",
      partId: "4286",
      partName: "Slope 33 3 x 1",
      shape: "slope_33_3x1",
      geometryAsset: "4286",
      dimensions: { lengthStuds: 3, widthStuds: 1, heightPlates: 3 },
      position: { x: 3, y: 2, z: 0 },
      orientationDegrees,
      color: "red",
    };

    const rendered = generatedPartRenderGeometry(placement, model);

    expect(rendered).not.toBeNull();
    const hasExpectedOrigin = rendered?.vertices.some((value, index, vertices) => (
      index % 3 === 0
      && Math.abs(value - expectedOrigin[0]) < 0.00001
      && Math.abs(vertices[index + 1] + 1.8) < 0.00001
      && Math.abs(vertices[index + 2] - expectedOrigin[1]) < 0.00001
    ));
    expect(hasExpectedOrigin).toBe(true);
  });

  it("keeps the rectangular fallback for a legacy placement without an asset", () => {
    const placement: LegoModel["placements"][number] = {
      brickType: "brick_2x3",
      partId: "3002",
      dimensions: { lengthStuds: 3, widthStuds: 2, heightPlates: 3 },
      position: { x: 0, y: 0, z: 0 },
      orientationDegrees: 0,
      color: "red",
    };

    expect(generatedPartRenderGeometry(placement, model)).toBeNull();
    expect(placementRenderGeometry(placement, model).size).toEqual([3, expect.closeTo(1.2), 2]);
    expect(rectangularStudRenderPositions(placement, model)).toHaveLength(6);
  });

  it("adds a top stud for every rectangular fallback footprint cell and none for slopes", () => {
    const rectangular: LegoModel["placements"][number] = {
      brickType: "plate_2x3",
      dimensions: { lengthStuds: 3, widthStuds: 2, heightPlates: 1 },
      position: { x: 0, y: 0, z: 0 },
      orientationDegrees: 90,
      color: "blue",
    };
    const slope: LegoModel["placements"][number] = {
      brickType: "slope_1x3",
      shape: "slope_33_3x1",
      dimensions: { lengthStuds: 3, widthStuds: 1, heightPlates: 3 },
      position: { x: 0, y: 0, z: 0 },
      orientationDegrees: 0,
      color: "red",
    };

    expect(rectangularStudRenderPositions(rectangular, model)).toHaveLength(6);
    expect(rectangularStudRenderPositions(slope, model)).toEqual([]);
  });
});
