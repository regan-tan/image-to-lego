import { Bounds, Center, Html, OrbitControls, useGLTF } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Suspense } from "react";

interface ModelViewerProps {
  url: string;
}

/**
 * Interactive GLB viewer. Loaded lazily by the project page so Three.js is only downloaded when a
 * 3D model is actually shown.
 */
export default function ModelViewer({ url }: ModelViewerProps) {
  return (
    <Canvas className="model-viewer" camera={{ position: [0, 0.6, 3], fov: 40 }} dpr={[1, 2]}>
      <ambientLight intensity={0.9} />
      <directionalLight position={[4, 6, 5]} intensity={1.6} />
      <directionalLight position={[-5, -2, -4]} intensity={0.5} />
      <Suspense
        fallback={(
          <Html center>
            <span className="model-viewer__loading">Loading 3D model…</span>
          </Html>
        )}
      >
        <Bounds fit clip observe margin={1.2}>
          <Center>
            <GeneratedModel url={url} />
          </Center>
        </Bounds>
      </Suspense>
      <OrbitControls makeDefault enableDamping />
    </Canvas>
  );
}

function GeneratedModel({ url }: ModelViewerProps) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}
