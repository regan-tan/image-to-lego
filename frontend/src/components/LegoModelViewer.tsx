import { Bounds, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";

import { placementRenderGeometry } from "../legoRenderGeometry";
import type { LegoModel } from "../schemas/legoModels";

export default function LegoModelViewer({ model }: { model: LegoModel }) {
  return (
    <Canvas className="model-viewer" camera={{ position: [9, 8, 11], fov: 38 }} dpr={[1, 2]}>
      <ambientLight intensity={1.1} />
      <directionalLight position={[8, 10, 6]} intensity={1.5} />
      <Bounds fit clip observe margin={1.3}>
        <group>
          {model.placements.map((placement, index) => {
            const brick = placementRenderGeometry(placement, model);
            return (
              <mesh key={`${placement.brickType}-${index}`} position={brick.center} castShadow receiveShadow>
                <boxGeometry args={brick.size} />
                <meshStandardMaterial color="#a0a5a9" roughness={0.72} />
              </mesh>
            );
          })}
        </group>
      </Bounds>
      <OrbitControls makeDefault enableDamping />
    </Canvas>
  );
}
