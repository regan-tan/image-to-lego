import { heightInPlates, type LegoModel } from "./schemas/legoModels";
import part3001 from "../../backend/app/conversion/part_geometry_assets/3001.json";
import part4286 from "../../backend/app/conversion/part_geometry_assets/4286.json";

const PLATE_HEIGHT_UNITS = 0.4;
const STUD_HEIGHT_UNITS = 0.18;

export interface RenderedBrick {
  size: [number, number, number];
  center: [number, number, number];
}

export interface RenderedPartGeometry {
  vertices: Float32Array;
  indices: Uint32Array;
}

export interface RenderedStud {
  center: [number, number, number];
}

interface PartGeometryAsset {
  partId: string;
  positions: number[];
  indices: number[];
}

const PART_GEOMETRY_ASSETS: Record<string, PartGeometryAsset> = {
  [part3001.partId]: part3001,
  [part4286.partId]: part4286,
};

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

export function generatedPartRenderGeometry(
  placement: LegoModel["placements"][number],
  model: LegoModel,
): RenderedPartGeometry | null {
  const assetName = placement.geometryAsset ?? placement.partId;
  const asset = assetName === undefined ? undefined : PART_GEOMETRY_ASSETS[assetName];
  if (asset === undefined) return null;

  const positionZ = model.dimensions.heightPlates === undefined
    ? placement.position.z * 3
    : placement.position.z;
  const vertices = asset.positions.flatMap((_, index, positions) => {
    if (index % 3 !== 0) return [];
    const [gridX, gridY] = transformedHorizontalPosition(
      placement,
      positions[index],
      positions[index + 1],
    );
    return [
      gridX - model.dimensions.widthStuds / 2,
      (positionZ + positions[index + 2]) * PLATE_HEIGHT_UNITS
        - heightInPlates(model.dimensions) * PLATE_HEIGHT_UNITS / 2,
      gridY - model.dimensions.depthStuds / 2,
    ];
  });
  return {
    vertices: new Float32Array(vertices),
    indices: new Uint32Array(asset.indices),
  };
}

/**
 * Returns top-stud centers for the simple rectangular fallback. Detailed part assets already
 * include their own LEGO geometry, while slopes keep their existing fallback shape unchanged.
 */
export function rectangularStudRenderPositions(
  placement: LegoModel["placements"][number],
  model: LegoModel,
): RenderedStud[] {
  if (placement.shape === "slope_33_3x1" || placement.brickType.startsWith("slope_")) return [];

  const brick = placementRenderGeometry(placement, model);
  const [length, height, depth] = brick.size;
  const left = brick.center[0] - length / 2;
  const front = brick.center[2] - depth / 2;
  const top = brick.center[1] + height / 2;
  const studs: RenderedStud[] = [];

  for (let x = 0; x < length; x += 1) {
    for (let z = 0; z < depth; z += 1) {
      studs.push({ center: [left + x + 0.5, top + STUD_HEIGHT_UNITS / 2, front + z + 0.5] });
    }
  }

  return studs;
}

export { STUD_HEIGHT_UNITS };

function transformedHorizontalPosition(
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
      return [
        placement.position.x + placement.dimensions.lengthStuds - length,
        placement.position.y + width,
      ];
    case 270:
      return [
        placement.position.x + width,
        placement.position.y + placement.dimensions.lengthStuds - length,
      ];
  }
}
