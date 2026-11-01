import { Bounds } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";

import type { LegoPartGroup } from "../legoPartsList";
import { legoColorHex } from "../legoColors";
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

type LegoPartThumbnailVariant = "geometry" | "illustration";

export function LegoPartThumbnail({
  part,
  variant = "geometry",
}: {
  part: LegoPartGroup;
  variant?: LegoPartThumbnailVariant;
}) {
  const renderInput = partThumbnailRenderInput(part);
  if (renderInput === null) return <ThumbnailPlaceholder partId={part.partId} />;

  if (variant === "illustration") return <BrickThumbnailIllustration part={part} />;

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

function BrickThumbnailIllustration({ part }: { part: LegoPartGroup }) {
  const length = Math.min(Math.max(Math.round(part.lengthStuds), 1), 6);
  const width = Math.min(Math.max(Math.round(part.widthStuds), 1), 4);
  const height = Math.min(Math.max(Math.round(part.heightPlates), 1), 6);
  const brickWidth = 22 + length * 7;
  const brickHeight = 15 + height * 2.5;
  const depth = 8 + width * 2;
  const left = (72 - brickWidth) / 2;
  const top = 28 - brickHeight / 2;
  const color = part.colorHex ?? legoColorHex(part.color);
  const studCount = Math.min(length * width, 8);

  return (
    <div
      className="lego-part-thumbnail lego-part-thumbnail--illustration"
      data-testid="lego-part-thumbnail"
      data-part-id={part.partId ?? "legacy"}
      role="img"
      aria-label={`${part.partId ?? "Legacy part"} ${part.partName} brick preview`}
    >
      <svg viewBox="0 0 72 56" aria-hidden="true">
        <path d={`M${left} ${top} L${left + brickWidth} ${top} L${left + brickWidth - depth} ${top - depth} L${left + depth} ${top - depth} Z`} fill={color} opacity="0.9" />
        <path d={`M${left} ${top} L${left + brickWidth - depth} ${top - depth} L${left + brickWidth - depth} ${top + brickHeight - depth} L${left} ${top + brickHeight} Z`} fill={color} opacity="0.72" />
        <path d={`M${left + brickWidth - depth} ${top - depth} L${left + brickWidth} ${top} L${left + brickWidth} ${top + brickHeight} L${left + brickWidth - depth} ${top + brickHeight - depth} Z`} fill={color} opacity="0.55" />
        {Array.from({ length: studCount }, (_, index) => {
          const column = index % length;
          const row = Math.floor(index / length);
          const x = left + depth + 4 + column * ((brickWidth - depth - 8) / Math.max(length - 1, 1));
          const y = top - depth / 2 + 2 + row * 4;
          return <ellipse key={index} cx={x} cy={y} rx="2.6" ry="1.5" fill={color} stroke="rgb(0 0 0 / 18%)" strokeWidth="0.6" />;
        })}
      </svg>
    </div>
  );
}

function ThumbnailPlaceholder({ partId }: { partId?: string }) {
  return (
    <div className="lego-part-thumbnail lego-part-thumbnail--unavailable" data-testid="lego-part-thumbnail-unavailable" data-part-id={partId ?? "legacy"} role="img" aria-label={`${partId ?? "Legacy part"} thumbnail unavailable`}>
      <span>{partId ?? "Legacy part"}</span>
    </div>
  );
}
