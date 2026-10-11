import { describe, expect, it } from "vitest";

import { classifyPlacementForBuildStep, deriveLegoBuildSteps } from "./legoBuildInstructions";
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
});

describe("classifyPlacementForBuildStep", () => {
  it.each([
    [0, 1, "previous"],
    [1, 1, "current"],
    [2, 1, "future"],
  ] as const)("classifies base layer %i at current layer %i as %s", (baseLayer, currentLayer, expected) => {
    expect(classifyPlacementForBuildStep(placement(baseLayer), currentLayer)).toBe(expected);
  });
});
