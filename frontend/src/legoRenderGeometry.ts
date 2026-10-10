import type { LegoModel } from "./schemas/legoModels";

const BRICK_HEIGHT_UNITS = 1.2;

export interface RenderedBrick {
  size: [number, number, number];
  center: [number, number, number];
}

export function placementRenderGeometry(
  placement: LegoModel["placements"][number],
  model: LegoModel,
): RenderedBrick {
  const length = placement.orientationDegrees === 0
    ? placement.dimensions.lengthStuds
    : placement.dimensions.widthStuds;
  const depth = placement.orientationDegrees === 0
    ? placement.dimensions.widthStuds
    : placement.dimensions.lengthStuds;
  const height = placement.dimensions.heightBricks * BRICK_HEIGHT_UNITS;
  return {
    size: [length, height, depth],
    center: [
      placement.position.x + length / 2 - model.dimensions.widthStuds / 2,
      placement.position.z * BRICK_HEIGHT_UNITS + height / 2 - model.dimensions.heightBricks * BRICK_HEIGHT_UNITS / 2,
      placement.position.y + depth / 2 - model.dimensions.depthStuds / 2,
    ],
  };
}
