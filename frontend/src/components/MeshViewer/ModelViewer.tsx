import React, { Suspense, useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { Canvas, useLoader, useThree } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Grid, Environment } from '@react-three/drei';
import * as THREE from 'three';
// @ts-ignore
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader';
import { meshApi } from '../../services/api';
import { Box, RotateCcw, Move3d, Zap } from 'lucide-react';

interface ModelViewerProps {
    caseId: string;
    currentSliceIndex: number;
    voxelSpacing: [number, number, number];
    showWireframe: boolean;
    totalSlices: number;
    showSliceIndicator?: boolean;
}

// Performance quality levels
type QualityLevel = 'high' | 'low';

/**
 * Adaptive Quality Controller
 * Monitors interaction and switches quality dynamically
 */
const AdaptiveQualityController: React.FC<{
    isInteracting: boolean;
    quality: QualityLevel;
}> = ({ isInteracting, quality }) => {
    const { gl } = useThree();

    useEffect(() => {
        // Adjust pixel ratio based on quality
        const dpr = quality === 'high' ? Math.min(window.devicePixelRatio, 2) : 1;
        gl.setPixelRatio(dpr);
    }, [quality, gl]);

    return null;
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
 * 3D Mesh Component
 * Loads and renders the reconstructed mesh with proper material
 * Optimized: reuses material, proper geometry disposal
 */
const ProcessedMesh: React.FC<{
    url: string;
    wireframe: boolean;
    color?: string;
    quality: QualityLevel;
}> = ({
    url,
    wireframe,
    color = '#ef4444',
    quality,
}) => {
        const obj = useLoader(OBJLoader, url);
        const materialRef = useRef<THREE.MeshStandardMaterial | null>(null);

        // Create/update material only when needed
        useMemo(() => {
            // Create material once and reuse
            if (!materialRef.current) {
                materialRef.current = new THREE.MeshStandardMaterial({
                    color: color,
                    roughness: 0.35,
                    metalness: 0.05,
                    wireframe: wireframe,
                    side: THREE.DoubleSide,
                    flatShading: false,
                });
            } else {
                // Update existing material properties
                materialRef.current.wireframe = wireframe;
                materialRef.current.color.set(color);
                materialRef.current.needsUpdate = true;
            }

            obj.traverse((child: THREE.Object3D) => {
                if ((child as THREE.Mesh).isMesh) {
                    const mesh = child as THREE.Mesh;

                    // Dispose old material if different
                    if (mesh.material && mesh.material !== materialRef.current) {
                        if (Array.isArray(mesh.material)) {
                            mesh.material.forEach(m => m.dispose());
                        } else {
                            mesh.material.dispose();
                        }
                    }

                    // Apply shared material
                    mesh.material = materialRef.current!;

                    // Compute normals only once
                    if (!mesh.geometry.getAttribute('normal')) {
                        mesh.geometry.computeVertexNormals();
                    }

                    // Center the mesh for easier viewing (only once)
                    if (!mesh.userData.centered) {
                        mesh.geometry.computeBoundingBox();
                        const center = new THREE.Vector3();
                        mesh.geometry.boundingBox?.getCenter(center);
                        mesh.position.sub(center);
                        mesh.userData.centered = true;
                    }

                    // Frustum culling optimization
                    mesh.frustumCulled = true;
                }
            });
        }, [obj, wireframe, color, quality]);

        // Cleanup on unmount
        useEffect(() => {
            return () => {
                if (materialRef.current) {
                    materialRef.current.dispose();
                }
            };
        }, []);

        return <primitive object={obj} />;
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
 * Optimized Grid Component
 * Only renders when not interacting for performance
 */
const OptimizedGrid: React.FC<{ visible: boolean }> = ({ visible }) => {
    if (!visible) return null;

    return (
        <Grid
            infiniteGrid
            cellSize={50}
            sectionSize={200}
            fadeDistance={800}
            sectionColor="#2a2e38"
            cellColor="#1a1e26"
            fadeStrength={1.5}
        />
    );
};

/**
 * Scene Content with quality-aware rendering
 */
const SceneContent: React.FC<ModelViewerProps & {
    quality: QualityLevel;
    isInteracting: boolean;
}> = ({
    caseId,
    currentSliceIndex,
    voxelSpacing,
    showWireframe,
    totalSlices,
    showSliceIndicator = true,
    quality,
    isInteracting,
}) => {
        const meshUrl = meshApi.getMeshUrl(caseId);

        // Calculate slice position in physical space
        const centerSlice = totalSlices / 2;
        const zPos = (currentSliceIndex - centerSlice) * voxelSpacing[2];

        // Show grid and slice indicator only in high quality mode (not during interaction)
        const showExtras = quality === 'high' && !isInteracting;

        return (
            <>
                {/* Quality Controller */}
                <AdaptiveQualityController isInteracting={isInteracting} quality={quality} />

                {/* Optimized Lighting - reduced light count */}
                <ambientLight intensity={0.5} />
                <directionalLight
                    position={[100, 100, 50]}
                    intensity={0.7}
                // No shadows for performance
                />
                <directionalLight position={[-50, 50, -50]} intensity={0.35} />

                {/* Simplified Environment - studio is lighter than city */}
                <Environment preset="studio" background={false} />

                {/* Grid - hidden during interaction */}
                <OptimizedGrid visible={showExtras} />

                {/* 3D Mesh */}
                <Suspense fallback={<LoadingFallback />}>
                    <ProcessedMesh
                        url={meshUrl}
                        wireframe={showWireframe}
                        quality={quality}
                    />
                </Suspense>

                {/* Slice Indicator - hidden during interaction */}
                <SliceIndicator
                    zPos={zPos}
                    wireframe={showWireframe}
                    visible={showSliceIndicator && showExtras}
                />
            </>
        );
    };

/**
 * Performance Monitor Badge
 */
const PerformanceBadge: React.FC<{ quality: QualityLevel; isInteracting: boolean }> = ({
    quality,
    isInteracting
}) => {
    if (!isInteracting && quality === 'high') return null;

    return (
        <div
            style={{
                position: 'absolute',
                top: 'var(--space-md)',
                right: 'var(--space-md)',
                zIndex: 10,
                background: 'rgba(34, 197, 94, 0.15)',
                border: '1px solid rgba(34, 197, 94, 0.4)',
                borderRadius: 'var(--radius-sm)',
                padding: '4px 8px',
                fontSize: '0.65rem',
                color: '#22c55e',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
            }}
        >
            <Zap size={10} />
            Performance Mode
        </div>
    );
};

/**
 * 3D Model Viewer Component - Optimized Version
 * 
 * Performance optimizations:
 * - Adaptive quality: reduces DPR and hides extras during interaction
 * - Demand-based rendering: only re-renders when needed
 * - Optimized controls: tuned damping and speeds
 * - Simplified environment: lighter preset
 * - Material reuse: single material instance
 */
export const ModelViewer: React.FC<ModelViewerProps> = (props) => {
    const [isInteracting, setIsInteracting] = useState(false);
    const [quality, setQuality] = useState<QualityLevel>('high');
    const idleTimerRef = useRef<number | null>(null);

    // Handle interaction start
    const handleInteractionStart = useCallback(() => {
        // Clear any pending idle timer
        if (idleTimerRef.current) {
            clearTimeout(idleTimerRef.current);
            idleTimerRef.current = null;
        }

        setIsInteracting(true);
        setQuality('low');
    }, []);

    // Handle interaction end
    const handleInteractionEnd = useCallback(() => {
        setIsInteracting(false);

        // Debounce quality restoration to avoid flashing
        idleTimerRef.current = window.setTimeout(() => {
            setQuality('high');
        }, 300);
    }, []);

    // Cleanup timer on unmount
    useEffect(() => {
        return () => {
            if (idleTimerRef.current) {
                clearTimeout(idleTimerRef.current);
            }
        };
    }, []);

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

            {/* Performance Badge */}
            <PerformanceBadge quality={quality} isInteracting={isInteracting} />

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

            {/* Optimized 3D Canvas */}
            <Canvas
                // Performance: render only when something changes
                frameloop="demand"
                // Performance: limit DPR, no shadows
                dpr={[1, 2]}
                gl={{
                    antialias: quality === 'high',
                    alpha: true,
                    powerPreference: 'high-performance',
                    // Reduce precision for performance
                    precision: 'mediump',
                }}
                style={{ background: 'transparent' }}
                // Invalidate on any change to trigger re-render
                onCreated={({ invalidate }) => {
                    // Force initial render
                    invalidate();
                }}
            >
                <PerspectiveCamera
                    makeDefault
                    position={[250, 200, 250]}
                    fov={45}
                    near={1}
                    far={3000}  // Reduced far plane
                />
                <OrbitControls
                    makeDefault
                    enableDamping
                    dampingFactor={0.08}  // Slightly higher for snappier feel
                    minDistance={50}
                    maxDistance={800}  // Reduced max distance
                    rotateSpeed={1.0}  // Faster rotation
                    zoomSpeed={1.2}    // Faster zoom
                    panSpeed={0.8}
                    // Interaction callbacks for adaptive quality
                    onStart={handleInteractionStart}
                    onEnd={handleInteractionEnd}
                />
                <SceneContent
                    {...props}
                    quality={quality}
                    isInteracting={isInteracting}
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
