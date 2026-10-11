import { heightInPlates, type LegoModel } from "./schemas/legoModels";

const PLATE_HEIGHT_UNITS = 0.4;

export interface RenderedBrick {
  size: [number, number, number];
  center: [number, number, number];
}

export interface RenderedSlope {
  vertices: Float32Array;
  indices: Uint16Array;
}

export function placementRenderGeometry(
  placement: LegoModel["placements"][number],
  model: LegoModel,
): RenderedBrick {
  const length = placement.orientationDegrees === 0 || placement.orientationDegrees === 180
    ? placement.dimensions.lengthStuds
    : placement.dimensions.widthStuds;
  const depth = placement.orientationDegrees === 0 || placement.orientationDegrees === 180
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

export function slopeRenderGeometry(
  placement: LegoModel["placements"][number],
  model: LegoModel,
): RenderedSlope {
  const height = heightInPlates(placement.dimensions) * PLATE_HEIGHT_UNITS;
  const positionZ = model.dimensions.heightPlates === undefined
    ? placement.position.z * 3
    : placement.position.z;
  const localVertices: Array<[number, number, number]> = [
    [0, 0, 0],
    [3, 0, 0],
    [3, 0, height],
    [0, 1, 0],
    [3, 1, 0],
    [3, 1, height],
  ];
  const vertices = localVertices.flatMap(([length, width, vertical]) => {
    const [gridX, gridY] = slopeHorizontalPosition(placement, length, width);
    return [
      gridX - model.dimensions.widthStuds / 2,
      positionZ * PLATE_HEIGHT_UNITS + vertical - heightInPlates(model.dimensions) * PLATE_HEIGHT_UNITS / 2,
      gridY - model.dimensions.depthStuds / 2,
    ];
  });
  return {
    vertices: new Float32Array(vertices),
    indices: new Uint16Array([
      0, 1, 2, 3, 5, 4,
      0, 4, 1, 0, 3, 4,
      1, 4, 5, 1, 5, 2,
      0, 2, 5, 0, 5, 3,
    ]),
  };
}

function slopeHorizontalPosition(
  placement: LegoModel["placements"][number],
  length: number,
  width: number,
): [number, number] {
  switch (placement.orientationDegrees) {
    case 0:
      return [placement.position.x + length, placement.position.y + width];
    case 90:
      return [placement.position.x + width, placement.position.y + length];
    case 180:
      return [placement.position.x + 3 - length, placement.position.y + width];
    case 270:
      return [placement.position.x + width, placement.position.y + 3 - length];
  }
}
