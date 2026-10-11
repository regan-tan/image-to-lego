import { heightInPlates, type LegoModel } from "./schemas/legoModels";

const PLATE_HEIGHT_UNITS = 0.4;

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
  const height = heightInPlates(placement.dimensions) * PLATE_HEIGHT_UNITS;
  const positionZ = model.dimensions.heightPlates === undefined
    ? placement.position.z * 3
    : placement.position.z;
  return {
    size: [length, height, depth],
    center: [
      placement.position.x + length / 2 - model.dimensions.widthStuds / 2,
      positionZ * PLATE_HEIGHT_UNITS + height / 2 - heightInPlates(model.dimensions) * PLATE_HEIGHT_UNITS / 2,
      placement.position.y + depth / 2 - model.dimensions.depthStuds / 2,
    ],
  };
}
