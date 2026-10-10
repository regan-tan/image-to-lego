import { describe, expect, it } from "vitest";

import {
  buildComplexityForTargetParts,
  targetPartsForBuildComplexity,
} from "./legoBuildComplexity";

describe("LEGO build complexity presets", () => {
  it.each([
    ["simple", 100],
    ["balanced", 300],
    ["detailed", 600],
  ] as const)("maps %s to a target of %i parts", (complexity, targetParts) => {
    expect(targetPartsForBuildComplexity(complexity)).toBe(targetParts);
  });

  it.each([
    [100, "simple"],
    [300, "balanced"],
    [600, "detailed"],
  ] as const)("maps a target of %i parts back to %s", (targetParts, complexity) => {
    expect(buildComplexityForTargetParts(targetParts)).toBe(complexity);
  });

  it("does not treat an unknown target as a known preset", () => {
    expect(buildComplexityForTargetParts(450)).toBeUndefined();
    expect(buildComplexityForTargetParts(undefined)).toBeUndefined();
  });
});
