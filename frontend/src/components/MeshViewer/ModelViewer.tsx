import React, { Suspense, useMemo, useCallback, useRef, useEffect } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { PerspectiveCamera, OrbitControls, Grid, Environment, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { DRACOLoader } from 'three-stdlib';
import { meshApi } from '../../services/api';
import { Box, RotateCcw, Move3d } from 'lucide-react';

// Configure Draco decoder path
const DRACO_DECODER_PATH = 'https://www.gstatic.com/draco/versioned/decoders/1.5.6/';

interface ModelViewerProps {
    caseId: string;
    currentSliceIndex: number;
    voxelSpacing: [number, number, number];
    showWireframe: boolean;
    totalSlices: number;
    showSliceIndicator?: boolean;
    showGrid?: boolean;
}


/**
 * Slice Indicator Plane
 * Shows the current 2D slice position in 3D space
 * Optimized: simplified geometry, no transparency calculations when possible
 */
const SliceIndicator: React.FC<{
    zPos: number;
    wireframe: boolean;
    visible: boolean;
}> = ({ zPos, wireframe, visible }) => {
    if (!visible) return null;

    return (
        <group position={[0, zPos, 0]}>
            {/* Semi-transparent plane - simplified */}
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
            {/* Edge ring - reduced segments from 64 to 32 */}
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[195, 200, 32]} />
                <meshBasicMaterial color="#3b82f6" opacity={0.6} transparent side={THREE.DoubleSide} />
            </mesh>
        </group>
    );
};

/**
 * 3D Mesh Component using GLTF + Draco
 * Loads and renders the reconstructed mesh with proper material
 * Optimized: GLTF format, Draco compression, strict memory management
 */
const ProcessedMesh: React.FC<{
    url: string;
    wireframe: boolean;
    color?: string;
    onLoad?: () => void;
}> = ({ url, wireframe, color = '#ef4444', onLoad }) => {
    // Get invalidate from R3F context
    const { invalidate: triggerInvalidate } = useThree();

    // Refs for cleanup
    const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);
    const meshesRef = useRef<THREE.Mesh[]>([]);
    const previousUrlRef = useRef<string | null>(null);
    const isInitializedRef = useRef(false);

    // Load GLTF with Draco compression
    const { scene } = useGLTF(url, true, true, (loader) => {
        const dracoLoader = new DRACOLoader();
        dracoLoader.setDecoderPath(DRACO_DECODER_PATH);
        loader.setDRACOLoader(dracoLoader);
    });

    // Clone the scene to avoid modifying the cached original
    const clonedScene = useMemo(() => scene.clone(true), [scene]);

    // Create shared material once
    const sharedMaterial = useMemo(() => {
        return new THREE.MeshStandardMaterial({
            color: color,
            roughness: 0.35,
            metalness: 0.05,
            wireframe: wireframe,
            side: THREE.DoubleSide,
            flatShading: false,
        });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Update material properties efficiently (without re-traversing)
    useEffect(() => {
        if (sharedMaterial) {
            sharedMaterial.wireframe = wireframe;
            sharedMaterial.color.set(color);
            sharedMaterial.needsUpdate = true;
            triggerInvalidate(); // Trigger re-render
        }
    }, [wireframe, color, sharedMaterial, triggerInvalidate]);

    // Initialize meshes once when scene loads
    useEffect(() => {
        if (isInitializedRef.current) return;
        isInitializedRef.current = true;

        materialRef.current = sharedMaterial;
        meshesRef.current = [];

        // Single traverse to set up all meshes
        clonedScene.traverse((child: THREE.Object3D) => {
            if ((child as THREE.Mesh).isMesh) {
                const mesh = child as THREE.Mesh;

                // Store reference for cleanup
                meshesRef.current.push(mesh);

                // Dispose old material if different from our shared material
                if (mesh.material && mesh.material !== materialRef.current) {
                    if (Array.isArray(mesh.material)) {
                        mesh.material.forEach((m) => m.dispose());
                    } else {
                        (mesh.material as THREE.Material).dispose();
                    }
                }

                // Apply shared material
                mesh.material = materialRef.current!;

                // NOTE: Normals are pre-calculated in GLTF, no runtime computation needed

                // Center the mesh for easier viewing (only once)
                if (!mesh.userData.centered) {
                    mesh.geometry.computeBoundingBox();
                    const center = new THREE.Vector3();
                    mesh.geometry.boundingBox?.getCenter(center);
                    mesh.position.sub(center);
                    mesh.userData.centered = true;
                }

                // Enable frustum culling for all meshes
                mesh.frustumCulled = true;
            }
        });

        // Notify when model is loaded
        if (onLoad) {
            onLoad();
        }
        triggerInvalidate(); // Trigger re-render for demand frameloop
    }, [clonedScene, sharedMaterial, onLoad, triggerInvalidate]);

    // Strict memory cleanup on unmount or model change
    useEffect(() => {
        previousUrlRef.current = url;

        return () => {
            // Dispose all geometries from tracked meshes
            meshesRef.current.forEach((mesh) => {
                if (mesh.geometry) {
                    mesh.geometry.dispose();
                }
            });
            meshesRef.current = [];

            // Dispose shared material
            if (materialRef.current) {
                materialRef.current.dispose();
                materialRef.current = null;
            }

            // Clear GLTF cache for this URL to free memory
            if (previousUrlRef.current) {
                useGLTF.clear(previousUrlRef.current);
            }

            isInitializedRef.current = false;
        };
    }, [url]);

    return <primitive object={clonedScene} />;
};

/**
 * Loading Fallback for 3D Scene
 * Simplified placeholder
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
 * Scene Content — React.memo prevents re-renders from parent state changes.
 */
const SceneContent = React.memo<ModelViewerProps & {
    onModelLoad?: () => void;
}>(function SceneContent({
    caseId,
    currentSliceIndex,
    voxelSpacing,
    showWireframe,
    totalSlices,
    showSliceIndicator = false,
    showGrid = false,
    onModelLoad,
}) {
    const meshUrl = meshApi.getMeshUrl(caseId);

    const centerSlice = totalSlices / 2;
    const zPos = (currentSliceIndex - centerSlice) * voxelSpacing[2];

    return (
        <>
            {/* Lighting */}
            <ambientLight intensity={0.5} />
            <directionalLight position={[100, 100, 50]} intensity={0.7} />
            <directionalLight position={[-50, 50, -50]} intensity={0.35} />
            <Environment preset="studio" background={false} />

            {/* Extras */}
            <group>
                {showGrid && (
                    <Grid
                        infiniteGrid
                        cellSize={50}
                        sectionSize={200}
                        fadeDistance={800}
                        sectionColor="#2a2e38"
                        cellColor="#1a1e26"
                        fadeStrength={1.5}
                    />
                )}
                {showSliceIndicator && (
                    <SliceIndicator zPos={zPos} wireframe={showWireframe} visible />
                )}
            </group>

            {/* 3D Mesh */}
            <Suspense fallback={<LoadingFallback />}>
                <ProcessedMesh
                    url={meshUrl}
                    wireframe={showWireframe}
                    onLoad={onModelLoad}
                />
            </Suspense>
        </>
    );
});



/**
 * 3D Model Viewer Component
 *
 * Uses drei OrbitControls for native, smooth 3D interactions.
 * enableDamping provides inertia, frameloop="always" keeps the
 * damping animation running continuously.
 */
export const ModelViewer: React.FC<ModelViewerProps> = (props) => {
    const handleModelLoad = useCallback(() => {}, []);

    const glProps = useMemo(() => ({
        antialias: true,
        stencil: false,
        alpha: true,
        powerPreference: 'high-performance' as const,
        precision: 'mediump' as const,
    }), []);

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
                frameloop="always"
                dpr={[1, 2]}
                gl={glProps}
                style={{ background: 'transparent' }}
            >
                <PerspectiveCamera
                    makeDefault
                    position={[250, 200, 250]}
                    fov={45}
                    near={1}
                    far={3000}
                />
                <OrbitControls
                    enableDamping
                    dampingFactor={0.08}
                    rotateSpeed={0.8}
                    panSpeed={0.6}
                    zoomSpeed={0.8}
                    minDistance={50}
                    maxDistance={800}
                    minPolarAngle={0.1}
                    maxPolarAngle={Math.PI - 0.1}
                    enablePan
                    mouseButtons={{
                        LEFT: THREE.MOUSE.ROTATE,
                        MIDDLE: THREE.MOUSE.DOLLY,
                        RIGHT: THREE.MOUSE.PAN,
                    }}
                />
                <SceneContent
                    {...props}
                    onModelLoad={handleModelLoad}
                />
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

export default ModelViewer;
