import { aggregateLegoPlacements, type LegoPartGroup } from "./legoPartsList";
import type { LegoModel } from "./schemas/legoModels";

export interface LegoBuildStep {
  stepNumber: number;
  layerZ: number;
  placements: LegoModel["placements"];
  partCount: number;
  cumulativePartCount: number;
  totalModelPartCount: number;
  parts: LegoPartGroup[];
}

export type PlacementBuildStage = "previous" | "current" | "future";

export function deriveLegoBuildSteps(model: LegoModel): LegoBuildStep[] {
  const placementsByLayer = new Map<number, LegoModel["placements"]>();

  for (const placement of model.placements) {
    const layerPlacements = placementsByLayer.get(placement.position.z);
    if (layerPlacements) {
      layerPlacements.push(placement);
    } else {
      placementsByLayer.set(placement.position.z, [placement]);
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
