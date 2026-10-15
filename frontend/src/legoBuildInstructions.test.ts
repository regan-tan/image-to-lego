import { describe, expect, it } from "vitest";

import { deriveLegoBuildSteps, placementBuildStagesForStep } from "./legoBuildInstructions";
import type { LegoModel } from "./schemas/legoModels";

type Placement = LegoModel["placements"][number];

function placement(z: number, overrides: Partial<Placement> = {}): Placement {
  return {
    brickType: "brick_2x4",
    dimensions: { lengthStuds: 2, widthStuds: 4, heightBricks: 1 },
    position: { x: 0, y: 0, z },
    orientationDegrees: 0,
    color: "green",
    ...overrides,
  };
}

function model(placements: Placement[]): LegoModel {
  return {
    partCount: placements.length,
    dimensions: { widthStuds: 8, depthStuds: 8, heightBricks: 6, widthMm: 64, depthMm: 64, heightMm: 57.6 },
    metadata: {
      algorithmVersion: "test",
      sourceSha256: "a",
      targetParts: 10,
      occupiedCellCount: 1,
      gridSize: { widthStuds: 8, depthStuds: 8, heightBricks: 6 },
      candidateCount: 1,
      occupancyMode: "test",
    },
    placements,
  };
}

describe("deriveLegoBuildSteps", () => {
  it("sorts occupied layers without adding steps for gaps", () => {
    const steps = deriveLegoBuildSteps(model([placement(3), placement(0), placement(1)]));

    expect(steps.map((step) => step.layerZ)).toEqual([0, 1, 3]);
    expect(steps.map((step) => step.stepNumber)).toEqual([1, 2, 3]);
  });

  it("uses explicit backend instruction steps instead of grouping by z layer", () => {
    const first = placement(0, { position: { x: 0, y: 0, z: 0 } });
    const second = placement(0, { position: { x: 2, y: 0, z: 0 } });
    const third = placement(3, { position: { x: 0, y: 0, z: 3 } });
    const buildModel = model([first, second, third]);
    buildModel.instructionSteps = [
      { stepNumber: 1, placementIndices: [0] },
      { stepNumber: 2, placementIndices: [1, 2] },
    ];

    const steps = deriveLegoBuildSteps(buildModel);

    expect(steps.map((step) => step.placementIndices)).toEqual([[0], [1, 2]]);
    expect(steps[1]?.placements).toEqual([second, third]);
    expect(steps.map((step) => step.cumulativePartCount)).toEqual([1, 3]);
  });

  it("groups a layer while preserving canonical placement order", () => {
    const first = placement(2, { position: { x: 2, y: 0, z: 2 } });
    const second = placement(0);
    const third = placement(2, { position: { x: 4, y: 0, z: 2 } });

    const steps = deriveLegoBuildSteps(model([first, second, third]));

    expect(steps[1]?.placements).toEqual([first, third]);
    expect(steps[1]?.partCount).toBe(2);
    expect(steps.map((step) => step.cumulativePartCount)).toEqual([1, 3]);
    expect(steps.at(-1)?.cumulativePartCount).toBe(3);
    expect(steps.at(-1)?.totalModelPartCount).toBe(3);
  });

  it("uses the full BOM identity and deterministic ordering for each step", () => {
    const steps = deriveLegoBuildSteps(model([
      placement(0, { orientationDegrees: 0 }),
      placement(0, { orientationDegrees: 90, position: { x: 2, y: 0, z: 0 } }),
      placement(0, { color: "blue" }),
      placement(0, { brickType: "brick_2x2", dimensions: { lengthStuds: 2, widthStuds: 2, heightBricks: 1 } }),
    ]));

    expect(steps[0]?.parts).toEqual([
      expect.objectContaining({ lengthStuds: 2, widthStuds: 4, color: "blue", quantity: 1 }),
      expect.objectContaining({ lengthStuds: 2, widthStuds: 4, color: "green", quantity: 2 }),
      expect.objectContaining({ lengthStuds: 2, widthStuds: 2, color: "green", quantity: 1 }),
    ]);
  });

  it("creates one step for one layer and no steps for an empty model", () => {
    expect(deriveLegoBuildSteps(model([placement(4)]))).toHaveLength(1);
    expect(deriveLegoBuildSteps(model([]))).toEqual([]);
  });

  it("introduces a taller brick only at its base layer", () => {
    const tallBrick = placement(1, { dimensions: { lengthStuds: 2, widthStuds: 4, heightBricks: 3 } });
    const steps = deriveLegoBuildSteps(model([placement(0), tallBrick, placement(3)]));

    expect(steps[1]?.placements).toEqual([tallBrick]);
  });

  it("uses plate-layer z positions for plate build steps", () => {
    const plate = placement(1, { brickType: "plate_2x4", dimensions: { lengthStuds: 2, widthStuds: 4, heightPlates: 1 } });
    const steps = deriveLegoBuildSteps(model([placement(0), plate, placement(2)]));

    expect(steps.map((step) => step.layerZ)).toEqual([0, 1, 2]);
    expect(steps[1]?.placements).toEqual([plate]);
  });

  it("keeps a directional slope in its base-layer build step", () => {
    const slope = placement(2, {
      brickType: "slope_1x3",
      partId: "4286",
      partName: "Slope 33 3 x 1",
      shape: "slope_33_3x1",
      dimensions: { lengthStuds: 3, widthStuds: 1, heightPlates: 3 },
      orientationDegrees: 270,
    });

    const steps = deriveLegoBuildSteps(model([placement(0), slope]));

    expect(steps[1]?.placements).toEqual([slope]);
    expect(steps[1]?.parts[0]).toEqual(
      expect.objectContaining({ partId: "4286", partName: "Slope 33 3 x 1" }),
    );
  });
});

describe("placementBuildStagesForStep", () => {
  it("keeps earlier placements visible, highlights the current step, and hides future placements", () => {
    const buildModel = model([placement(0), placement(0), placement(2), placement(4)]);
    buildModel.instructionSteps = [
      { stepNumber: 1, placementIndices: [0] },
      { stepNumber: 2, placementIndices: [1, 2] },
      { stepNumber: 3, placementIndices: [3] },
    ];
    const steps = deriveLegoBuildSteps(buildModel);

    expect(placementBuildStagesForStep(buildModel, steps, 1)).toEqual([
      "previous",
      "current",
      "current",
      "future",
    ]);
    expect(placementBuildStagesForStep(buildModel, steps, 2)).toEqual([
      "previous",
      "previous",
      "previous",
      "current",
    ]);
  });

  it("uses the current step only when grouping its part list", () => {
    const buildModel = model([
      placement(0, { partId: "3001", color: "red", colorId: "ldraw:4" }),
      placement(1, { partId: "3020", color: "black", colorId: "ldraw:0" }),
      placement(1, { partId: "3020", color: "black", colorId: "ldraw:0" }),
      placement(2, { partId: "3001", color: "red", colorId: "ldraw:4" }),
    ]);
    buildModel.instructionSteps = [
      { stepNumber: 1, placementIndices: [0] },
      { stepNumber: 2, placementIndices: [1, 2] },
      { stepNumber: 3, placementIndices: [3] },
    ];

    const currentStep = deriveLegoBuildSteps(buildModel)[1];

    expect(currentStep?.parts).toEqual([
      expect.objectContaining({ partId: "3020", colorId: "ldraw:0", quantity: 2 }),
    ]);
    expect(currentStep?.partCount).toBe(2);
    expect(currentStep?.cumulativePartCount).toBe(3);
    expect(currentStep?.totalModelPartCount).toBe(4);
  });

  it("treats slopes and historical z-layer steps like every other placement", () => {
    const slope = placement(1, {
      brickType: "slope_1x3",
      partId: "4286",
      shape: "slope_33_3x1",
      dimensions: { lengthStuds: 3, widthStuds: 1, heightPlates: 3 },
    });
    const historicalModel = model([placement(0), slope, placement(2)]);
    const legacySteps = deriveLegoBuildSteps(historicalModel);

    expect(legacySteps.map((step) => step.placementIndices)).toEqual([[0], [1], [2]]);
    expect(placementBuildStagesForStep(historicalModel, legacySteps, 0)).toEqual([
      "current",
      "future",
      "future",
    ]);
    expect(placementBuildStagesForStep(historicalModel, legacySteps, 1)).toEqual([
      "previous",
      "current",
      "future",
    ]);
  });

  it("returns the same stages for the same model and selected step", () => {
    const buildModel = model([placement(0), placement(1), placement(2)]);
    const steps = deriveLegoBuildSteps(buildModel);

    expect(placementBuildStagesForStep(buildModel, steps, 1)).toEqual(
      placementBuildStagesForStep(buildModel, steps, 1),
    );
  });
});
