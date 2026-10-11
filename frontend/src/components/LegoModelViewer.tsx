import { Bounds, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";

import { classifyPlacementForBuildStep } from "../legoBuildInstructions";
import { placementRenderGeometry, slopeRenderGeometry } from "../legoRenderGeometry";
import { legoColorHex } from "../legoColors";
import type { LegoModel } from "../schemas/legoModels";

interface LegoModelViewerProps {
  model: LegoModel;
  currentLayerZ?: number;
}

export default function LegoModelViewer({ model, currentLayerZ }: LegoModelViewerProps) {
  return (
    <Canvas className="model-viewer" camera={{ position: [9, 8, 11], fov: 38 }} dpr={[1, 2]}>
      <ambientLight intensity={1.1} />
      <directionalLight position={[8, 10, 6]} intensity={1.5} />
      <Bounds fit clip observe margin={1.3}>
        <group>
          {model.placements.map((placement, index) => {
            const buildStage = currentLayerZ === undefined
              ? "current"
              : classifyPlacementForBuildStep(placement, currentLayerZ);
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
            if (placement.shape === "slope_33_3x1") {
              const slope = slopeRenderGeometry(placement, model);
              return (
                <mesh key={`${placement.brickType}-${index}`} castShadow receiveShadow>
                  <bufferGeometry>
                    <bufferAttribute attach="attributes-position" args={[slope.vertices, 3]} />
                    <bufferAttribute attach="index" args={[slope.indices, 1]} />
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
