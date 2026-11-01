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

  it("accepts the additive V2 guide while preserving legacy artifacts", () => {
    const model = {
      ...legacyModel,
      instructionGuide: {
        version: "build-guide-v2",
        warnings: ["Physical assembly is not guaranteed."],
        steps: [{
          stepNumber: 1,
          placementIndices: [0],
          placements: [{
            placementIndex: 0,
            position: { x: 0, y: 0, z: 0 },
            orientationDegrees: 0,
          }],
          parts: [{ partId: "3001", color: "red", colorId: null, quantity: 1 }],
        }],
      },
    };

    expect(legoModelSchema.parse(model).instructionGuide?.version).toBe("build-guide-v2");
    expect(legoModelSchema.parse(legacyModel).instructionGuide).toBeUndefined();
  });

  it("accepts the catalogue part-color verification marker", () => {
    const model = {
      ...legacyModel,
      metadata: { ...legacyModel.metadata, partColorVerificationVersion: "catalogue-v1" },
      placements: [{ ...legacyModel.placements[0], partColorVerified: true }],
    };

    expect(legoModelSchema.parse(model).placements[0]?.partColorVerified).toBe(true);
  });

  it("accepts the null geometry asset the worker writes for ordinary parts", () => {
    const model = {
      ...legacyModel,
      placements: [{ ...legacyModel.placements[0], geometryAsset: null }],
    };

    expect(legoModelSchema.parse(model).placements[0]?.geometryAsset).toBeUndefined();
  });

  it("accepts catalogue-provenanced external part and color IDs", () => {
    const model = {
      ...legacyModel,
      placements: [{
        ...legacyModel.placements[0],
        externalIds: { bricklink: { partId: "3001", colorId: 5 } },
      }],
    };

    expect(legoModelSchema.parse(model).placements[0]?.externalIds).toEqual(
      { bricklink: { partId: "3001", colorId: 5 } },
    );
  });
});
