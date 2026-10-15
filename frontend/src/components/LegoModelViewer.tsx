import { Bounds, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useState, type ReactNode } from "react";

import type { PlacementBuildStage } from "../legoBuildInstructions";
import type { LegoModel } from "../schemas/legoModels";
import { RetryIcon } from "./Icons";
import { LegoPartMesh } from "./LegoPartMesh";

const CAMERA_MARGIN = 1.35;

interface LegoModelViewerProps {
  model: LegoModel;
  placementStages?: PlacementBuildStage[];
}

export default function LegoModelViewer({
  model,
  placementStages,
}: LegoModelViewerProps) {
  const [fitVersion, setFitVersion] = useState(0);
  const [fittedDistance, setFittedDistance] = useState<number | null>(null);
  const isBuildGuide = placementStages !== undefined;
  const placementsByStage = {
    previous: [] as ReactNode[],
    current: [] as ReactNode[],
    all: [] as ReactNode[],
  };

  for (const [index, placement] of model.placements.entries()) {
    const stage = placementStages?.[index];
    if (stage === "future") continue;

    const mesh = <LegoPartMesh key={`${placement.brickType}-${index}`} model={model} placement={placement} stage={stage} />;
    if (stage === "previous" || stage === "current") {
      placementsByStage[stage].push(mesh);
    } else {
      placementsByStage.all.push(mesh);
    }
  }

  const visiblePlacements = isBuildGuide
    ? [...placementsByStage.previous, ...placementsByStage.current]
    : placementsByStage.all;
  const visibleStageKey = placementStages?.join(":") ?? "all";
  const minimumDistance = minimumCameraDistance(model);
  const maximumDistance = fittedDistance === null
    ? maximumCameraDistance(model)
    : fittedDistance * 2.5;

  return (
    <div className="lego-model-viewer">
      <Canvas className="model-viewer" camera={{ position: [9, 8, 11], fov: 38 }} dpr={[1, 2]}>
        <ambientLight intensity={1.1} />
        <directionalLight position={[8, 10, 6]} intensity={1.5} />
        <directionalLight position={[-6, 4, -4]} intensity={0.45} />
        <Bounds
          key={`${visibleStageKey}-${fitVersion}`}
          fit
          clip
          observe
          margin={CAMERA_MARGIN}
          onFit={({ distance }) => setFittedDistance(distance)}
        >
          <group>{visiblePlacements}</group>
        </Bounds>
        <OrbitControls
          makeDefault
          enableDamping
          enablePan={false}
          minDistance={minimumDistance}
          maxDistance={maximumDistance}
          minPolarAngle={0.1}
          maxPolarAngle={Math.PI * 0.48}
        />
      </Canvas>
      <button
        type="button"
        className="icon-button icon-button--overlay lego-model-viewer__fit"
        aria-label="Fit LEGO model in view"
        title="Fit model in view"
        onClick={() => setFitVersion((current) => current + 1)}
      >
        <RetryIcon />
      </button>
    </div>
  );
}

function minimumCameraDistance(model: LegoModel): number {
  const longestSide = Math.max(
    model.dimensions.widthStuds,
    model.dimensions.depthStuds,
    model.dimensions.heightPlates ?? (model.dimensions.heightBricks ?? 0) * 3,
  );
  return Math.max(0.75, longestSide * 0.08);
}

function maximumCameraDistance(model: LegoModel): number {
  const longestSide = Math.max(
    model.dimensions.widthStuds,
    model.dimensions.depthStuds,
    model.dimensions.heightPlates ?? (model.dimensions.heightBricks ?? 0) * 3,
  );
  return Math.max(8, longestSide * 3);
}
