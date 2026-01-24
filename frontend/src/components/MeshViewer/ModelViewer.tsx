import React, { Suspense, useMemo } from 'react';
import { Canvas, useLoader } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Grid, Environment } from '@react-three/drei';
import * as THREE from 'three';
// @ts-ignore
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader';
import { meshApi } from '../../services/api';
import { Box, RotateCcw, Move3d } from 'lucide-react';

interface ModelViewerProps {
    caseId: string;
    currentSliceIndex: number;
    voxelSpacing: [number, number, number];
    showWireframe: boolean;
    totalSlices: number;
    showSliceIndicator?: boolean;
}

/**
 * Slice Indicator Plane
 * Shows the current 2D slice position in 3D space
 */
const SliceIndicator: React.FC<{ zPos: number; wireframe: boolean }> = ({ zPos, wireframe }) => {
    return (
        <group position={[0, zPos, 0]}>
            {/* Semi-transparent plane */}
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <planeGeometry args={[400, 400]} />
                <meshBasicMaterial
                    color="#3b82f6"
                    transparent
                    opacity={wireframe ? 0.3 : 0.12}
                    side={THREE.DoubleSide}
                    depthWrite={false}
                />
            </mesh>
            {/* Edge ring */}
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[195, 200, 64]} />
                <meshBasicMaterial color="#3b82f6" opacity={0.6} transparent side={THREE.DoubleSide} />
            </mesh>
        </group>
    );
};

/**
 * 3D Mesh Component
 * Loads and renders the reconstructed mesh with proper material
 */
const ProcessedMesh: React.FC<{ url: string; wireframe: boolean; color?: string }> = ({
    url,
    wireframe,
    color = '#ef4444',
}) => {
    const obj = useLoader(OBJLoader, url);

    // Process mesh and apply material
    useMemo(() => {
        obj.traverse((child: THREE.Object3D) => {
            if ((child as THREE.Mesh).isMesh) {
                const mesh = child as THREE.Mesh;

                // Dispose old material to prevent memory leak
                if (mesh.material) {
                    if (Array.isArray(mesh.material)) {
                        mesh.material.forEach(m => m.dispose());
                    } else {
                        mesh.material.dispose();
                    }
                }

                // Create material with proper lighting
                mesh.material = new THREE.MeshStandardMaterial({
                    color: color,
                    roughness: 0.35,
                    metalness: 0.05,
                    wireframe: wireframe,
                    side: THREE.DoubleSide,
                    flatShading: false,
                });

                // Compute normals for better lighting
                mesh.geometry.computeVertexNormals();

                // Center the mesh for easier viewing
                mesh.geometry.computeBoundingBox();
                const center = new THREE.Vector3();
                mesh.geometry.boundingBox?.getCenter(center);
                mesh.position.sub(center);
            }
        });
    }, [obj, wireframe, color]);

    return <primitive object={obj} />;
};

/**
 * Loading Fallback for 3D Scene
 */
const LoadingFallback: React.FC = () => {
    return (
        <mesh>
            <boxGeometry args={[50, 50, 50]} />
            <meshBasicMaterial color="#1a1e26" wireframe />
        </mesh>
    );
};

/**
 * Scene Content
 */
const SceneContent: React.FC<ModelViewerProps> = ({
    caseId,
    currentSliceIndex,
    voxelSpacing,
    showWireframe,
    totalSlices,
    showSliceIndicator = true,
}) => {
    const meshUrl = meshApi.getMeshUrl(caseId);

    // Calculate slice position in physical space
    const centerSlice = totalSlices / 2;
    const zPos = (currentSliceIndex - centerSlice) * voxelSpacing[2];

    return (
        <>
            {/* Lighting */}
            <ambientLight intensity={0.4} />
            <directionalLight position={[100, 100, 50]} intensity={0.8} castShadow />
            <directionalLight position={[-50, 50, -50]} intensity={0.4} />
            <pointLight position={[0, 100, 0]} intensity={0.3} />

            {/* Environment for better reflections */}
            <Environment preset="city" background={false} />

            {/* Ground Grid */}
            <Grid
                infiniteGrid
                cellSize={50}
                sectionSize={200}
                fadeDistance={1000}
                sectionColor="#2a2e38"
                cellColor="#1a1e26"
                fadeStrength={1}
            />

            {/* 3D Mesh */}
            <Suspense fallback={<LoadingFallback />}>
                <ProcessedMesh url={meshUrl} wireframe={showWireframe} />
            </Suspense>

            {/* Slice Indicator */}
            {showSliceIndicator && <SliceIndicator zPos={zPos} wireframe={showWireframe} />}
        </>
    );
};

/**
 * 3D Model Viewer Component
 * Displays reconstructed mesh with orbit controls
 */
export const ModelViewer: React.FC<ModelViewerProps> = (props) => {
    return (
        <div
            style={{
                width: '100%',
                height: '100%',
                position: 'relative',
                background: 'linear-gradient(180deg, #0f1115 0%, #0a0c10 100%)',
            }}
        >
            {/* View Label */}
            <div
                style={{
                    position: 'absolute',
                    top: 'var(--space-md)',
                    left: 'var(--space-md)',
                    zIndex: 10,
                    display: 'flex',
                    gap: 'var(--space-sm)',
                    alignItems: 'center',
                }}
            >
                <div
                    style={{
                        background: 'var(--bg-glass)',
                        backdropFilter: 'blur(8px)',
                        padding: '4px 12px',
                        borderRadius: 'var(--radius-md)',
                        border: '1px solid var(--border-subtle)',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        color: 'var(--text-primary)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-xs)',
                    }}
                >
                    <Box size={14} />
                    3D Reconstruction
                </div>
            </div>

            {/* Controls Hint */}
            <div
                style={{
                    position: 'absolute',
                    bottom: 'var(--space-md)',
                    left: 'var(--space-md)',
                    zIndex: 10,
                    display: 'flex',
                    gap: 'var(--space-md)',
                }}
            >
                <div
                    style={{
                        background: 'var(--bg-glass)',
                        backdropFilter: 'blur(8px)',
                        padding: '6px 10px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        fontSize: '0.7rem',
                        color: 'var(--text-muted)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-xs)',
                    }}
                >
                    <RotateCcw size={12} />
                    Drag to rotate
                </div>
                <div
                    style={{
                        background: 'var(--bg-glass)',
                        backdropFilter: 'blur(8px)',
                        padding: '6px 10px',
                        borderRadius: 'var(--radius-sm)',
                        border: '1px solid var(--border-subtle)',
                        fontSize: '0.7rem',
                        color: 'var(--text-muted)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-xs)',
                    }}
                >
                    <Move3d size={12} />
                    Scroll to zoom
                </div>
            </div>

            {/* 3D Canvas */}
            <Canvas
                shadows
                gl={{ antialias: true, alpha: true }}
                style={{ background: 'transparent' }}
            >
                <PerspectiveCamera makeDefault position={[250, 200, 250]} fov={45} near={1} far={5000} />
                <OrbitControls
                    makeDefault
                    enableDamping
                    dampingFactor={0.05}
                    minDistance={50}
                    maxDistance={1000}
                    rotateSpeed={0.8}
                    zoomSpeed={1}
                />
                <SceneContent {...props} />
            </Canvas>

            {/* Disclaimer */}
            <div
                style={{
                    position: 'absolute',
                    bottom: 'var(--space-md)',
                    right: 'var(--space-md)',
                    zIndex: 10,
                    maxWidth: 280,
                    background: 'rgba(239, 68, 68, 0.1)',
                    border: '1px solid rgba(239, 68, 68, 0.3)',
                    borderRadius: 'var(--radius-sm)',
                    padding: 'var(--space-sm)',
                    fontSize: '0.65rem',
                    color: 'var(--accent-error)',
                    lineHeight: 1.4,
                }}
            >
                3D visualization is for research purposes only. Not intended for clinical diagnosis.
            </div>
        </div>
    );
};
