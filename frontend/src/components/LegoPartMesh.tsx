import { Edges } from "@react-three/drei";

import type { PlacementBuildStage } from "../legoBuildInstructions";
import {
  generatedPartRenderGeometry,
  placementRenderGeometry,
  rectangularStudRenderPositions,
  STUD_HEIGHT_UNITS,
} from "../legoRenderGeometry";
import { legoColorHex } from "../legoColors";
import type { LegoModel } from "../schemas/legoModels";

const OUTLINE_COLOR = "#2677d8";
const STUD_RADIUS_UNITS = 0.3;

interface LegoPartMeshProps {
  model: LegoModel;
  placement: LegoModel["placements"][number];
  stage?: PlacementBuildStage;
}

/** Renders one placement through the canonical detailed-asset or procedural fallback path. */
export function LegoPartMesh({ model, placement, stage }: LegoPartMeshProps) {
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

function LegoMaterial({ color, isCurrentStep, opacity }: { color: string; isCurrentStep: boolean; opacity: number }) {
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
  return <Edges color={OUTLINE_COLOR} lineWidth={1.25} transparent={opacity < 1} opacity={opacity < 1 ? 0.72 : 0.92} depthWrite={false} />;
}
