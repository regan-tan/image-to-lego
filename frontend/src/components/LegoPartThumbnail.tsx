import { Bounds } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";

import type { LegoPartGroup } from "../legoPartsList";
import type { LegoModel } from "../schemas/legoModels";
import { ErrorBoundary } from "./ErrorBoundary";
import { LegoPartMesh } from "./LegoPartMesh";

const THUMBNAIL_CAMERA_POSITION: [number, number, number] = [5, 4, 6];
const THUMBNAIL_CAMERA_FOV = 38;
const THUMBNAIL_CAMERA_MARGIN = 1.35;

export interface LegoPartThumbnailRenderInput {
  model: LegoModel;
  placement: LegoModel["placements"][number];
}

/** Creates a deterministic, origin-centred representative placement for one grouped part. */
// eslint-disable-next-line react-refresh/only-export-components -- this pure builder is the thumbnail's deterministic test seam.
export function partThumbnailRenderInput(part: LegoPartGroup): LegoPartThumbnailRenderInput | null {
  if (
    part.brickType.length === 0
    || !Number.isFinite(part.lengthStuds)
    || !Number.isFinite(part.widthStuds)
    || !Number.isFinite(part.heightPlates)
    || part.lengthStuds <= 0
    || part.widthStuds <= 0
    || part.heightPlates <= 0
  ) return null;

  const model: LegoModel = {
    partCount: 1,
    dimensions: { widthStuds: part.lengthStuds, depthStuds: part.widthStuds, heightPlates: part.heightPlates, widthMm: 0, depthMm: 0, heightMm: 0 },
    metadata: {
      algorithmVersion: "thumbnail",
      sourceSha256: "thumbnail",
      occupiedCellCount: 1,
      gridSize: { widthStuds: part.lengthStuds, depthStuds: part.widthStuds, heightPlates: part.heightPlates },
      candidateCount: 1,
      occupancyMode: "thumbnail",
    },
    placements: [],
  };
  const placement: LegoModel["placements"][number] = {
    brickType: part.brickType,
    partId: part.partId,
    partName: part.partName,
    shape: part.shape,
    geometryAsset: part.geometryAsset,
    dimensions: { lengthStuds: part.lengthStuds, widthStuds: part.widthStuds, heightPlates: part.heightPlates },
    position: { x: 0, y: 0, z: 0 },
    orientationDegrees: 0,
    color: part.color,
    colorId: part.colorId,
    colorName: part.colorName,
    colorHex: part.colorHex,
  };

  return { model, placement };
}

export function LegoPartThumbnail({ part }: { part: LegoPartGroup }) {
  const renderInput = partThumbnailRenderInput(part);
  if (renderInput === null) return <ThumbnailPlaceholder partId={part.partId} />;

  return (
    <ErrorBoundary fallback={<ThumbnailPlaceholder partId={part.partId} />}>
      <div className="lego-part-thumbnail" data-testid="lego-part-thumbnail" data-part-id={part.partId ?? "legacy"} role="img" aria-label={`${part.partId ?? "Legacy part"} thumbnail`}>
        <Canvas camera={{ position: THUMBNAIL_CAMERA_POSITION, fov: THUMBNAIL_CAMERA_FOV }} dpr={[1, 1.5]} gl={{ alpha: true, antialias: true }}>
          <ambientLight intensity={1.1} />
          <directionalLight position={[8, 10, 6]} intensity={1.5} />
          <directionalLight position={[-6, 4, -4]} intensity={0.45} />
          <Bounds fit clip margin={THUMBNAIL_CAMERA_MARGIN}>
            <LegoPartMesh model={renderInput.model} placement={renderInput.placement} />
          </Bounds>
        </Canvas>
      </div>
    </ErrorBoundary>
  );
}

function ThumbnailPlaceholder({ partId }: { partId?: string }) {
  return (
    <div className="lego-part-thumbnail lego-part-thumbnail--unavailable" data-testid="lego-part-thumbnail-unavailable" data-part-id={partId ?? "legacy"} role="img" aria-label={`${partId ?? "Legacy part"} thumbnail unavailable`}>
      <span>{partId ?? "Legacy part"}</span>
    </div>
  );
}
