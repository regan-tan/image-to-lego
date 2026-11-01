import { aggregateLegoPlacements, type LegoPartGroup } from "./legoPartsList";
import type { LegoModel } from "./schemas/legoModels";

export interface LegoBuildStep {
  stepNumber: number;
  layerZ: number;
  placementIndices: number[];
  placements: LegoModel["placements"];
  partCount: number;
  cumulativePartCount: number;
  totalModelPartCount: number;
  parts: LegoPartGroup[];
  placementGuidance: Array<{
    placementIndex: number;
    position: { x: number; y: number; z: number };
    orientationDegrees: 0 | 90 | 180 | 270;
  }>;
}

export type PlacementBuildStage = "previous" | "current" | "future";

export function deriveLegoBuildSteps(model: LegoModel): LegoBuildStep[] {
  const guide = model.instructionGuide;
  const legacySteps = model.instructionSteps;

  if (guide && isValidV2Guide(model, guide.steps, legacySteps)) {
    return createBuildSteps(model, guide.steps, guide.steps);
  }
  if (legacySteps && hasCompleteCanonicalCoverage(model, legacySteps)) {
    return createBuildSteps(model, legacySteps);
  }
  return createLayerBuildSteps(model);
}

function createBuildSteps(
  model: LegoModel,
  instructionSteps: NonNullable<LegoModel["instructionSteps"]>,
  guideSteps?: NonNullable<LegoModel["instructionGuide"]>["steps"],
): LegoBuildStep[] {
  return instructionSteps.map((instructionStep, index) => {
      const placements = instructionStep.placementIndices.map((placementIndex) => {
        const placement = model.placements[placementIndex];
        if (!placement) throw new Error("Validated instructions reference an unknown placement.");
        return placement;
      });
      const previousPartCount = instructionSteps
        .slice(0, index)
        .reduce((count, step) => count + step.placementIndices.length, 0);
      return {
        stepNumber: instructionStep.stepNumber,
        layerZ: Math.min(...placements.map((placement) => placement.position.z)),
        placementIndices: instructionStep.placementIndices,
        placements,
        partCount: placements.length,
        cumulativePartCount: previousPartCount + placements.length,
        totalModelPartCount: model.placements.length,
        parts: aggregateLegoPlacements(placements),
        placementGuidance: guideSteps?.[index]?.placements ?? instructionStep.placementIndices.map((placementIndex) => ({
            placementIndex,
            position: model.placements[placementIndex]!.position,
            orientationDegrees: model.placements[placementIndex]!.orientationDegrees,
          })),
      };
    });
}

function createLayerBuildSteps(model: LegoModel): LegoBuildStep[] {
  const placementsByLayer = new Map<number, LegoModel["placements"]>();
  const placementIndicesByLayer = new Map<number, number[]>();

  for (const [placementIndex, placement] of model.placements.entries()) {
    const layerPlacements = placementsByLayer.get(placement.position.z);
    if (layerPlacements) {
      layerPlacements.push(placement);
    } else {
      placementsByLayer.set(placement.position.z, [placement]);
    }
    const placementIndices = placementIndicesByLayer.get(placement.position.z);
    if (placementIndices) {
      placementIndices.push(placementIndex);
    } else {
      placementIndicesByLayer.set(placement.position.z, [placementIndex]);
    }
  }

  const occupiedLayers = [...placementsByLayer.keys()].sort((left, right) => left - right);
  let cumulativePartCount = 0;

  return occupiedLayers.map((layerZ, index) => {
    const placements = placementsByLayer.get(layerZ) ?? [];
    cumulativePartCount += placements.length;
    return {
      stepNumber: index + 1,
      layerZ,
      placementIndices: placementIndicesByLayer.get(layerZ) ?? [],
      placements,
      partCount: placements.length,
      cumulativePartCount,
      totalModelPartCount: model.placements.length,
      parts: aggregateLegoPlacements(placements),
      placementGuidance: (placementIndicesByLayer.get(layerZ) ?? []).map((placementIndex) => ({
        placementIndex,
        position: model.placements[placementIndex]!.position,
        orientationDegrees: model.placements[placementIndex]!.orientationDegrees,
      })),
    };
  });
}

export function buildGuideWarnings(model: LegoModel): string[] {
  if (model.instructionGuide && isValidV2Guide(
    model,
    model.instructionGuide.steps,
    model.instructionSteps,
  )) {
    return model.instructionGuide.warnings;
  }
  const fallbackWarning = model.instructionGuide
    ? "Build Guide V2 data did not pass integrity checks. Displayed steps use validated legacy or canonical placement data."
    : undefined;
  return [
    ...(fallbackWarning ? [fallbackWarning] : []),
    "Physical assembly is not validated for this legacy instruction artifact.",
  ];
}

function isValidV2Guide(
  model: LegoModel,
  guideSteps: NonNullable<LegoModel["instructionGuide"]>["steps"],
  legacySteps: LegoModel["instructionSteps"],
): boolean {
  if (!hasCompleteCanonicalCoverage(model, guideSteps)) return false;

  for (const step of guideSteps) {
    if (step.placements.length !== step.placementIndices.length) return false;
    for (const [placementOffset, placementIndex] of step.placementIndices.entries()) {
      const guidance = step.placements[placementOffset];
      const placement = model.placements[placementIndex];
      if (!guidance || !placement || guidance.placementIndex !== placementIndex) return false;
      if (
        guidance.position.x !== placement.position.x
        || guidance.position.y !== placement.position.y
        || guidance.position.z !== placement.position.z
        || guidance.orientationDegrees !== placement.orientationDegrees
      ) return false;
      if (guidance.partId !== undefined && guidance.partId !== canonicalPartId(placement)) return false;
      if (guidance.colorId !== undefined && guidance.colorId !== (placement.colorId ?? null)) return false;
    }
    if (!hasExactStepParts(model, step.placementIndices, step.parts)) return false;
  }

  // Current artifacts retain the generated legacy steps. When they are valid,
  // they are the available serialized record of the backend's precedence order.
  if (legacySteps && hasCompleteCanonicalCoverage(model, legacySteps)) {
    return guideSteps.every((step, index) => sameIndices(step.placementIndices, legacySteps[index]?.placementIndices));
  }
  return true;
}

function hasCompleteCanonicalCoverage(
  model: LegoModel,
  instructionSteps: NonNullable<LegoModel["instructionSteps"]>,
): boolean {
  const seen = new Set<number>();
  for (const [index, step] of instructionSteps.entries()) {
    if (step.stepNumber !== index + 1 || step.placementIndices.length === 0) return false;
    for (const placementIndex of step.placementIndices) {
      if (placementIndex < 0 || placementIndex >= model.placements.length || seen.has(placementIndex)) return false;
      seen.add(placementIndex);
    }
  }
  return seen.size === model.placements.length;
}

function hasExactStepParts(
  model: LegoModel,
  placementIndices: number[],
  parts: NonNullable<LegoModel["instructionGuide"]>["steps"][number]["parts"],
): boolean {
  const expected = new Map<string, number>();
  for (const placementIndex of placementIndices) {
    const placement = model.placements[placementIndex];
    if (!placement) return false;
    const key = partKey(canonicalPartId(placement), placement.color, placement.colorId ?? null);
    expected.set(key, (expected.get(key) ?? 0) + 1);
  }
  const actual = new Map<string, number>();
  for (const part of parts) {
    const key = partKey(part.partId, part.color, part.colorId);
    if (actual.has(key)) return false;
    actual.set(key, part.quantity);
  }
  return expected.size === actual.size && [...expected].every(([key, quantity]) => actual.get(key) === quantity);
}

function canonicalPartId(placement: LegoModel["placements"][number]): string {
  return placement.partId ?? placement.brickType;
}

function partKey(partId: string, color: string, colorId: string | null): string {
  return JSON.stringify([partId, color, colorId]);
}

function sameIndices(left: number[], right: number[] | undefined): boolean {
  return right !== undefined && left.length === right.length && left.every((value, index) => value === right[index]);
}

export function placementBuildStagesForStep(
  model: LegoModel,
  steps: LegoBuildStep[],
  currentStepIndex: number,
): PlacementBuildStage[] {
  const currentStep = steps[currentStepIndex];
  if (!currentStep) return model.placements.map(() => "future");

  const previousPlacementIndices = new Set(
    steps.slice(0, currentStepIndex).flatMap((step) => step.placementIndices),
  );
  const currentPlacementIndices = new Set(currentStep.placementIndices);

  return model.placements.map((_, placementIndex) => {
    if (currentPlacementIndices.has(placementIndex)) return "current";
    if (previousPlacementIndices.has(placementIndex)) return "previous";
    return "future";
  });
}
