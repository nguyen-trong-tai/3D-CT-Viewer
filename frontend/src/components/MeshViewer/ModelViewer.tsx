import React, { Suspense, useMemo, useCallback, useRef, useEffect } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { PerspectiveCamera, OrbitControls, Grid, Environment, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { meshApi } from '../../services/api';
import { Box, RotateCcw, Move3d } from 'lucide-react';
import { useViewerStore } from '../../stores/viewerStore';
import { DRACO_DECODER_PATH } from '../../utils/draco';

interface ModelViewerProps {
    caseId: string;
    currentSliceIndex: number;
    voxelSpacing: [number, number, number];
    showWireframe: boolean;
    totalSlices: number;
    showSliceIndicator?: boolean;
    showGrid?: boolean;
}

const COMPONENT_COLOR_MAP: Record<string, string> = {
    lung: '#ef4444',
    left_lung: '#60a5fa',
    right_lung: '#34d399',
};

const FALLBACK_COMPONENT_COLORS = ['#f59e0b', '#a855f7', '#14b8a6', '#fb7185'];

const normalizeComponentKey = (value: string | undefined): string =>
    (value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');

const getMaterialColor = (material: THREE.Material | THREE.Material[]): THREE.Color | null => {
    const firstMaterial = Array.isArray(material) ? material[0] : material;
    if (firstMaterial && 'color' in firstMaterial && firstMaterial.color instanceof THREE.Color) {
        return firstMaterial.color.clone();
    }
    return null;
};

const resolveMeshColor = (mesh: THREE.Mesh, fallbackColor: string, index: number): THREE.Color => {
    const candidateKeys = [
        mesh.name,
        mesh.parent?.name,
        typeof mesh.userData?.component_key === 'string' ? mesh.userData.component_key : undefined,
    ]
        .map(normalizeComponentKey)
        .filter(Boolean);

    for (const key of candidateKeys) {
        const mapped = COMPONENT_COLOR_MAP[key];
        if (mapped) {
            return new THREE.Color(mapped);
        }
    }

    return (
        getMaterialColor(mesh.material) ??
        new THREE.Color(FALLBACK_COMPONENT_COLORS[index % FALLBACK_COMPONENT_COLORS.length] || fallbackColor)
    );
};


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
    const { invalidate: triggerInvalidate } = useThree();

    const { scene } = useGLTF(url, DRACO_DECODER_PATH, false);

    // Clone the scene and center it as a whole to preserve multi-mesh alignment.
    const { clonedScene, materials } = useMemo(() => {
        const clone = scene.clone(true);
        const bounds = new THREE.Box3().setFromObject(clone);
        const createdMaterials: THREE.MeshStandardMaterial[] = [];
        let meshIndex = 0;

        if (!bounds.isEmpty()) {
            const center = new THREE.Vector3();
            bounds.getCenter(center);
            clone.position.sub(center);
        }

        clone.traverse((child: THREE.Object3D) => {
            if ((child as THREE.Mesh).isMesh) {
                const mesh = child as THREE.Mesh;
                const material = new THREE.MeshStandardMaterial({
                    color: resolveMeshColor(mesh, color, meshIndex),
                    roughness: 0.35,
                    metalness: 0.05,
                    wireframe,
                    side: THREE.DoubleSide,
                    flatShading: false,
                });

                mesh.material = material;
                mesh.frustumCulled = true;
                createdMaterials.push(material);
                meshIndex += 1;
            }
        });

        return { clonedScene: clone, materials: createdMaterials };
    }, [scene, color, wireframe]);

    // Handle onLoad notification
    useEffect(() => {
        if (onLoad) {
            onLoad();
        }
        triggerInvalidate();
    }, [clonedScene, onLoad, triggerInvalidate]);

    // Update material properties efficiently
    useEffect(() => {
        materials.forEach((material) => {
            material.wireframe = wireframe;
            material.needsUpdate = true;
        });
        triggerInvalidate();
    }, [wireframe, materials, triggerInvalidate]);

    // Dispose only the material owned by this component. Geometry and source scene
    // are cached by useGLTF and can be reused across StrictMode remounts.
    useEffect(() => {
        return () => {
            materials.forEach((material) => material.dispose());
        };
    }, [materials]);

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
 * Active Tool Context wrapper for Orbit Controls
 * Isolated to prevent Canvas re-renders when activeTool changes
 */
const ViewerControls = () => {
    const activeTool = useViewerStore(state => state.activeTool);
    const controlsRef = useRef<OrbitControlsImpl | null>(null);

    // Listen to global reset view event from header toolbar
    useEffect(() => {
        const handleReset = () => {
            if (controlsRef.current) {
                controlsRef.current.reset();
            }
        };
        window.addEventListener('reset-view', handleReset);
        return () => window.removeEventListener('reset-view', handleReset);
    }, []);

    return (
        <OrbitControls
            ref={controlsRef}
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
                LEFT: activeTool === 'pan' ? THREE.MOUSE.PAN : 
                      activeTool === 'zoom' ? THREE.MOUSE.DOLLY : 
                      THREE.MOUSE.ROTATE,
                MIDDLE: THREE.MOUSE.DOLLY,
                RIGHT: THREE.MOUSE.PAN,
            }}
        />
    );
};

/**
 * 3D Model Viewer Component
 *
 * Uses drei OrbitControls for native, smooth 3D interactions.
 * enableDamping provides inertia, frameloop="always" keeps the
 * damping animation running continuously.
 */
export const ModelViewer: React.FC<ModelViewerProps> = (props) => {
    const handleModelLoad = useCallback(() => { }, []);

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
                <ViewerControls />
                <SceneContent
                    {...props}
                    onModelLoad={handleModelLoad}
                />
            </Canvas>

        </div>
    );
};

export default ModelViewer;
