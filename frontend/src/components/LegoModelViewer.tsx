import { Bounds, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";

import { classifyPlacementForBuildStep } from "../legoBuildInstructions";
import { generatedPartRenderGeometry, placementRenderGeometry } from "../legoRenderGeometry";
import { legoColorHex } from "../legoColors";
import type { LegoModel } from "../schemas/legoModels";

interface LegoModelViewerProps {
  model: LegoModel;
  currentLayerZ?: number;
  currentPlacementIndices?: number[];
  previousPlacementIndices?: number[];
}

export default function LegoModelViewer({
  model,
  currentLayerZ,
  currentPlacementIndices,
  previousPlacementIndices,
}: LegoModelViewerProps) {
  return (
    <Canvas className="model-viewer" camera={{ position: [9, 8, 11], fov: 38 }} dpr={[1, 2]}>
      <ambientLight intensity={1.1} />
      <directionalLight position={[8, 10, 6]} intensity={1.5} />
      <Bounds fit clip observe margin={1.3}>
        <group>
          {model.placements.map((placement, index) => {
            let buildStage = currentLayerZ === undefined
              ? "current"
              : classifyPlacementForBuildStep(placement, currentLayerZ);
            if (currentPlacementIndices !== undefined && previousPlacementIndices !== undefined) {
              if (currentPlacementIndices.includes(index)) {
                buildStage = "current";
              } else if (previousPlacementIndices.includes(index)) {
                buildStage = "previous";
              } else {
                buildStage = "future";
              }
            }
            let opacity = 1;
            if (buildStage === "previous") opacity = 0.28;
            if (buildStage === "future") opacity = 0;
            const material = (
              <meshStandardMaterial
                color={placement.colorHex ?? legoColorHex(placement.color)}
                roughness={0.72}
                transparent={opacity < 1}
                opacity={opacity}
                depthWrite={opacity === 1}
              />
            );
            const generatedGeometry = generatedPartRenderGeometry(placement, model);
            if (generatedGeometry !== null) {
              return (
                <mesh key={`${placement.brickType}-${index}`} castShadow receiveShadow>
                  <bufferGeometry>
                    <bufferAttribute attach="attributes-position" args={[generatedGeometry.vertices, 3]} />
                    <bufferAttribute attach="index" args={[generatedGeometry.indices, 1]} />
                  </bufferGeometry>
                  {material}
                </mesh>
              );
            }
            const brick = placementRenderGeometry(placement, model);
            return (
              <mesh key={`${placement.brickType}-${index}`} position={brick.center} castShadow receiveShadow>
                <boxGeometry args={brick.size} />
                {material}
              </mesh>
            );
          })}
        </group>
      </Bounds>
      <OrbitControls makeDefault enableDamping />
    </Canvas>
  );
}
