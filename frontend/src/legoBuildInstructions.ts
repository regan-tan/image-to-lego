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
}

export type PlacementBuildStage = "previous" | "current" | "future";

export function deriveLegoBuildSteps(model: LegoModel): LegoBuildStep[] {
  const instructionSteps = model.instructionSteps;
  if (instructionSteps !== undefined) {
    return instructionSteps.map((instructionStep, index) => {
      const placements = instructionStep.placementIndices.map((placementIndex) => {
        const placement = model.placements[placementIndex];
        if (!placement) throw new Error("An instruction step references an unknown placement.");
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
        totalModelPartCount: model.partCount,
        parts: aggregateLegoPlacements(placements),
      };
    });
  }

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
      totalModelPartCount: model.partCount,
      parts: aggregateLegoPlacements(placements),
    };
  });
}

export function classifyPlacementForBuildStep(
  placement: LegoModel["placements"][number],
  currentLayerZ: number,
): PlacementBuildStage {
  if (placement.position.z < currentLayerZ) return "previous";
  if (placement.position.z > currentLayerZ) return "future";
  return "current";
}
