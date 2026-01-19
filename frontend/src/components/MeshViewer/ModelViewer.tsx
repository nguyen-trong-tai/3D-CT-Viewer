import React, { Suspense } from 'react';
import { Canvas, useLoader } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Grid } from '@react-three/drei';
import * as THREE from 'three';
// @ts-ignore
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader';
import { meshApi } from '../../services/api/mesh';

interface ModelViewerProps {
    caseId: string;
    currentSliceIndex: number;
    voxelSpacing: [number, number, number]; // [x, y, z]
    showWireframe: boolean;
    totalSlices: number;
}

const SliceIndicator = ({ zPos, wireframe }: { zPos: number, wireframe: boolean }) => {
    return (
        <group position={[0, zPos, 0]}>
            {/* Visual Plane showing the slice cut */}
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <planeGeometry args={[400, 400]} />
                <meshBasicMaterial
                    color="#3b82f6"
                    transparent
                    opacity={wireframe ? 0.3 : 0.15}
                    side={THREE.DoubleSide}
                    depthWrite={false}
                    wireframe={wireframe}
                />
            </mesh>
            {/* Frame */}
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[198, 200, 64]} />
                <meshBasicMaterial color="#3b82f6" opacity={0.5} transparent side={THREE.DoubleSide} />
            </mesh>
        </group>
    );
};

const ProcessedMesh = ({ url, wireframe }: { url: string, wireframe: boolean }) => {
    const obj = useLoader(OBJLoader, url);

    // Process material
    obj.traverse((child: THREE.Object3D) => {
        if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            mesh.material = new THREE.MeshStandardMaterial({
                color: "#ef4444",
                roughness: 0.4,
                metalness: 0.1,
                wireframe: wireframe,
                side: THREE.DoubleSide
            });

            // Adjust geometry center if needed, but backend should send physical coords.
            // Assuming backend sends coords where (0,0,0) is meaningful or consistent index space.
            // Often meshes come in positive coordinates. We might need to center it?
            // "Coordinate system is consistent with CT volume"
            // Usually CT volume 0,0,0 is corner. We orbit around center.
            // Let's auto-center for visualization convenience if it's off-screen.
            // Actually, for strictness, valid physical coords should be respected. 
            // We just ensure Camera looks at it.

            mesh.geometry.computeBoundingBox();
            const center = new THREE.Vector3();
            mesh.geometry.boundingBox?.getCenter(center);
            mesh.position.sub(center); // Center the mesh at world logic origin for rotation
        }
    });

    return <primitive object={obj} />;
};

const SceneContent = ({ caseId, currentSliceIndex, voxelSpacing, showWireframe, totalSlices }: ModelViewerProps) => {
    const meshUrl = meshApi.getMeshUrl(caseId);

    // Map slice index to World Z.
    // Center of volume is at TOTAL_SLICES / 2.
    // Z-spacing is voxelSpacing[2].

    // Note: If we centered the mesh above, we must conceptually center the slice indicator too.
    // Logic: Slice index N corresponds to Physical Z = (N * SpacingZ)
    // If Mesh is centered, then we shift Slice Z by (CenterZ).
    // Let's try relative movement.

    const centerSlice = totalSlices / 2;
    // We multiply by spacing to get physical units.
    // Backend mesh is in MM. So we use MM directly.
    const zPos = (currentSliceIndex - centerSlice) * voxelSpacing[2];

    return (
        <>
            <ambientLight intensity={0.5} />
            <pointLight position={[100, 100, 100]} intensity={1} />
            <directionalLight position={[-50, 50, -50]} intensity={0.5} />

            <Grid infiniteGrid cellSize={50} sectionSize={200} fadeDistance={1000} sectionColor="#404040" cellColor="#202020" />

            <Suspense fallback={null}>
                <ProcessedMesh url={meshUrl} wireframe={showWireframe} />
            </Suspense>

            <SliceIndicator zPos={zPos} wireframe={showWireframe} />
        </>
    );
};

export const ModelViewer: React.FC<ModelViewerProps> = (props) => {
    return (
        <div style={{ width: '100%', height: '100%' }}>
            <Canvas>
                <PerspectiveCamera makeDefault position={[200, 200, 200]} fov={50} />
                <OrbitControls makeDefault />
                <SceneContent {...props} />
            </Canvas>
        </div>
    );
};
