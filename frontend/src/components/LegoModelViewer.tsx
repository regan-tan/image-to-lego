import { Bounds, Edges, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useState, type ReactNode } from "react";

import type { PlacementBuildStage } from "../legoBuildInstructions";
import {
  generatedPartRenderGeometry,
  placementRenderGeometry,
  rectangularStudRenderPositions,
  STUD_HEIGHT_UNITS,
} from "../legoRenderGeometry";
import { legoColorHex } from "../legoColors";
import type { LegoModel } from "../schemas/legoModels";
import { RetryIcon } from "./Icons";

const OUTLINE_COLOR = "#2677d8";
const STUD_RADIUS_UNITS = 0.3;
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

    const mesh = <LegoPlacement key={`${placement.brickType}-${index}`} model={model} placement={placement} stage={stage} />;
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

interface LegoPlacementProps {
  model: LegoModel;
  placement: LegoModel["placements"][number];
  stage?: PlacementBuildStage;
}

function LegoPlacement({ model, placement, stage }: LegoPlacementProps) {
  const isPreviousStep = stage === "previous";
  const isCurrentStep = stage === "current";
  const generatedGeometry = generatedPartRenderGeometry(placement, model);
  const color = placement.colorHex ?? legoColorHex(placement.color);
  const opacity = isPreviousStep ? 0.38 : 1;

  if (generatedGeometry !== null) {
    return (
      <mesh castShadow receiveShadow>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[generatedGeometry.vertices, 3]} />
          <bufferAttribute attach="index" args={[generatedGeometry.indices, 1]} />
        </bufferGeometry>
        <LegoMaterial color={color} isCurrentStep={isCurrentStep} opacity={opacity} />
        <PieceOutline opacity={opacity} />
      </mesh>
    );
  }

  const brick = placementRenderGeometry(placement, model);
  const studs = rectangularStudRenderPositions(placement, model);
  return (
    <group>
      <mesh position={brick.center} castShadow receiveShadow>
        <boxGeometry args={brick.size} />
        <LegoMaterial color={color} isCurrentStep={isCurrentStep} opacity={opacity} />
        <PieceOutline opacity={opacity} />
      </mesh>
      {studs.map((stud, index) => (
        <mesh key={index} position={stud.center} castShadow receiveShadow>
          <cylinderGeometry args={[STUD_RADIUS_UNITS, STUD_RADIUS_UNITS, STUD_HEIGHT_UNITS, 16]} />
          <LegoMaterial color={color} isCurrentStep={isCurrentStep} opacity={opacity} />
        </mesh>
      ))}
    </group>
  );
}

function LegoMaterial({
  color,
  isCurrentStep,
  opacity,
}: {
  color: string;
  isCurrentStep: boolean;
  opacity: number;
}) {
  return (
    <meshStandardMaterial
      color={color}
      emissive={isCurrentStep ? "#f5c542" : "#000000"}
      emissiveIntensity={isCurrentStep ? 0.28 : 0}
      roughness={0.42}
      metalness={0.05}
      transparent={opacity < 1}
      opacity={opacity}
      depthWrite={opacity === 1}
    />
  );
}

function PieceOutline({ opacity }: { opacity: number }) {
  return (
    <Edges
      color={OUTLINE_COLOR}
      lineWidth={1.25}
      transparent={opacity < 1}
      opacity={opacity < 1 ? 0.72 : 0.92}
      depthWrite={false}
    />
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
