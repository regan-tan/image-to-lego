import { describe, expect, it } from "vitest";

import { legoModelSchema } from "./legoModels";

const legacyModel = {
  partCount: 1,
  dimensions: { widthStuds: 2, depthStuds: 4, heightBricks: 1, widthMm: 16, depthMm: 32, heightMm: 9.6 },
  metadata: {
    algorithmVersion: "surface-grid-v3",
    sourceSha256: "source",
    occupiedCellCount: 8,
    gridSize: { widthStuds: 2, depthStuds: 4, heightBricks: 1 },
    candidateCount: 1,
    occupancyMode: "surface",
  },
  placements: [{
    brickType: "brick_2x4",
    partId: "3001",
    partName: "Brick 2 x 4",
    dimensions: { lengthStuds: 2, widthStuds: 4, heightBricks: 1 },
    position: { x: 0, y: 0, z: 0 },
    orientationDegrees: 0,
    color: "red",
  }],
};

describe("legoModelSchema", () => {
  it("continues to parse artifacts without canonical color fields", () => {
    expect(legoModelSchema.parse(legacyModel).placements[0]?.colorId).toBeUndefined();
  });

  it("accepts the four directional orientations used by 4286", () => {
    for (const orientationDegrees of [0, 90, 180, 270]) {
      const model = {
        ...legacyModel,
        placements: [{
          ...legacyModel.placements[0],
          shape: "slope_33_3x1",
          orientationDegrees,
        }],
      };
      expect(legoModelSchema.parse(model).placements[0]?.orientationDegrees).toBe(orientationDegrees);
    }
  });

  it("accepts explicit placement-index instruction steps", () => {
    const model = {
      ...legacyModel,
      instructionSteps: [{ stepNumber: 1, placementIndices: [0] }],
    };

    expect(legoModelSchema.parse(model).instructionSteps).toEqual(model.instructionSteps);
  });
});
