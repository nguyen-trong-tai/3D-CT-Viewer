import React, { Suspense, useCallback, useEffect, useMemo, useRef } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { PerspectiveCamera, OrbitControls, Grid, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { meshApi } from '../../services/api';
import { Box, RotateCcw, Move3d } from 'lucide-react';
import { useViewerStore } from '../../stores/viewerStore';
import { DRACO_DECODER_PATH } from '../../utils/draco';
import type { MeshVisibilityPreset, SegmentationVisibility } from '../../types';

interface ModelViewerProps {
    caseId: string;
    currentSliceIndex: number;
    voxelSpacing: [number, number, number];
    showWireframe: boolean;
    totalSlices: number;
    showSliceIndicator?: boolean;
    showGrid?: boolean;
}

type MeshEntry = {
    mesh: THREE.Mesh;
    material: THREE.MeshStandardMaterial;
    componentKey: string;
    visibilityKey: string;
};

const COMPONENT_COLOR_MAP: Record<string, string> = {
    lung: '#ef4444',
    left_lung: '#60a5fa',
    right_lung: '#34d399',
    nodule: '#f97316',
};

const FALLBACK_COMPONENT_COLORS = ['#f59e0b', '#a855f7', '#14b8a6', '#fb7185'];

const normalizeComponentKey = (value: string | undefined): string =>
    (value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');

const findMatchingLabel = (
    candidateKeys: string[],
    labels: Array<{
        key: string;
        color: string;
        mesh_component_name?: string | null;
    }>
) => {
    for (const candidateKey of candidateKeys) {
        const match = labels.find((label) => {
            const meshKey = normalizeComponentKey(label.mesh_component_name ?? undefined);
            const labelKey = normalizeComponentKey(label.key);
            return candidateKey === meshKey || candidateKey === labelKey;
        });
        if (match) {
            return match;
        }
    }

    return null;
};

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

const getOpacityForComponent = (key: string, preset: MeshVisibilityPreset): number => {
    const isLung = key === 'left_lung' || key === 'right_lung' || key === 'lung';
    const isNodule = key === 'nodule';

    if (preset === 'nodule_focus') {
        if (isLung) return 0.08;
        if (isNodule) return 1.0;
        return 0.45;
    }

    return 1.0;
};

const SliceIndicator: React.FC<{
    zPos: number;
    wireframe: boolean;
    visible: boolean;
}> = ({ zPos, wireframe, visible }) => {
    if (!visible) return null;

    return (
        <group position={[0, zPos, 0]}>
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
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[195, 200, 32]} />
                <meshBasicMaterial color="#3b82f6" opacity={0.6} transparent side={THREE.DoubleSide} />
            </mesh>
        </group>
    );
};

const ProcessedMesh: React.FC<{
    url: string;
    wireframe: boolean;
    componentVisibility: SegmentationVisibility;
    visibilityPreset: MeshVisibilityPreset;
    labels: Array<{
        key: string;
        color: string;
        mesh_component_name?: string | null;
    }>;
    color?: string;
    onLoad?: () => void;
}> = ({ url, wireframe, componentVisibility, visibilityPreset, labels, color = '#ef4444', onLoad }) => {
    const invalidate = useThree((state) => state.invalidate);
    const { scene } = useGLTF(url, DRACO_DECODER_PATH, false);

    const { clonedScene, meshEntries, materials } = useMemo(() => {
        const clone = scene.clone(true);
        const bounds = new THREE.Box3().setFromObject(clone);
        const createdMaterials: THREE.MeshStandardMaterial[] = [];
        const createdEntries: MeshEntry[] = [];
        let meshIndex = 0;

        if (!bounds.isEmpty()) {
            const center = new THREE.Vector3();
            bounds.getCenter(center);
            clone.position.sub(center);
        }

        clone.traverse((child) => {
            if (!(child as THREE.Mesh).isMesh) {
                return;
            }

            const mesh = child as THREE.Mesh;
            const componentKey = [
                mesh.name,
                mesh.parent?.name,
                typeof mesh.userData?.component_key === 'string' ? mesh.userData.component_key : undefined,
            ]
                .map(normalizeComponentKey)
                .find(Boolean) ?? '';
            const candidateKeys = [
                mesh.name,
                mesh.parent?.name,
                typeof mesh.userData?.component_key === 'string' ? mesh.userData.component_key : undefined,
            ]
                .map(normalizeComponentKey)
                .filter(Boolean);
            const matchedLabel = findMatchingLabel(candidateKeys, labels);
            const visibilityKey = matchedLabel?.key ?? componentKey;

            const material = new THREE.MeshStandardMaterial({
                color: matchedLabel?.color
                    ? new THREE.Color(matchedLabel.color)
                    : resolveMeshColor(mesh, color, meshIndex),
                roughness: 0.35,
                metalness: 0.05,
                transparent: true,
                opacity: 1.0,
                side: THREE.DoubleSide,
            });

            mesh.material = material;
            mesh.userData.component_key = componentKey;
            mesh.frustumCulled = true;

            createdMaterials.push(material);
            createdEntries.push({ mesh, material, componentKey, visibilityKey });
            meshIndex += 1;
        });

        return {
            clonedScene: clone,
            meshEntries: createdEntries,
            materials: createdMaterials,
        };
    }, [color, labels, scene]);

    useEffect(() => {
        onLoad?.();
        invalidate();
    }, [clonedScene, invalidate, onLoad]);

    useEffect(() => {
        meshEntries.forEach(({ mesh, componentKey, visibilityKey }) => {
            const resolvedVisibilityKey = visibilityKey || componentKey;
            mesh.visible = resolvedVisibilityKey ? (componentVisibility[resolvedVisibilityKey] ?? true) : true;
        });
        invalidate();
    }, [componentVisibility, invalidate, meshEntries]);

    useEffect(() => {
        meshEntries.forEach(({ componentKey, material }) => {
            const opacity = getOpacityForComponent(componentKey, visibilityPreset);
            material.opacity = opacity;
            material.transparent = opacity < 0.999 || wireframe;
            material.depthWrite = opacity >= 0.999 && !wireframe;
            material.wireframe = wireframe;
            material.needsUpdate = true;
        });
        invalidate();
    }, [invalidate, meshEntries, visibilityPreset, wireframe]);

    useEffect(() => {
        return () => {
            materials.forEach((material) => material.dispose());
        };
    }, [materials]);

    return <primitive object={clonedScene} />;
};

const LoadingFallback: React.FC = () => (
    <mesh>
        <boxGeometry args={[50, 50, 50]} />
        <meshBasicMaterial color="#1a1e26" wireframe />
    </mesh>
);

const SceneContent = React.memo<ModelViewerProps & {
    onModelLoad?: () => void;
    visibilityPreset: MeshVisibilityPreset;
}>(function SceneContent({
    caseId,
    currentSliceIndex,
    voxelSpacing,
    showWireframe,
    totalSlices,
    showSliceIndicator = false,
    showGrid = false,
    onModelLoad,
    visibilityPreset,
}) {
    const meshUrl = meshApi.getMeshUrl(caseId);
    const componentVisibility = useViewerStore((state) => state.segmentationVisibility);
    const segmentationLabels = useViewerStore((state) => state.segmentationLabels);

    const centerSlice = totalSlices / 2;
    const zPos = (currentSliceIndex - centerSlice) * voxelSpacing[2];

    return (
        <>
            <ambientLight intensity={0.58} />
            <directionalLight position={[100, 120, 60]} intensity={0.72} />
            <directionalLight position={[-70, 40, -80]} intensity={0.28} />

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

            <Suspense fallback={<LoadingFallback />}>
                <ProcessedMesh
                    url={meshUrl}
                    wireframe={showWireframe}
                    componentVisibility={componentVisibility}
                    visibilityPreset={visibilityPreset}
                    labels={segmentationLabels}
                    onLoad={onModelLoad}
                />
            </Suspense>
        </>
    );
});

const ViewerControls: React.FC = () => {
    const activeTool = useViewerStore((state) => state.activeTool);
    const controlsRef = useRef<OrbitControlsImpl | null>(null);
    const invalidate = useThree((state) => state.invalidate);

    useEffect(() => {
        const handleReset = () => {
            controlsRef.current?.reset();
            invalidate();
        };

        window.addEventListener('reset-view', handleReset);
        return () => window.removeEventListener('reset-view', handleReset);
    }, [invalidate]);

    useEffect(() => {
        invalidate();
    }, [activeTool, invalidate]);

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
            onChange={() => invalidate()}
            mouseButtons={{
                LEFT:
                    activeTool === 'pan'
                        ? THREE.MOUSE.PAN
                        : activeTool === 'zoom'
                            ? THREE.MOUSE.DOLLY
                            : THREE.MOUSE.ROTATE,
                MIDDLE: THREE.MOUSE.DOLLY,
                RIGHT: THREE.MOUSE.PAN,
            }}
        />
    );
};

export const ModelViewer: React.FC<ModelViewerProps> = (props) => {
    const segmentationLabels = useViewerStore((state) => state.segmentationLabels);
    const visibilityPreset = useViewerStore((state) => state.meshVisibilityPreset);
    const setMeshVisibilityPreset = useViewerStore((state) => state.setMeshVisibilityPreset);
    const meshLoadMeasuredRef = useRef(false);
    const has3DLung = segmentationLabels.some(
        (label) => label.available && label.render_3d && (label.key === 'left_lung' || label.key === 'right_lung' || label.key === 'lung')
    );
    const has3DNodule = segmentationLabels.some(
        (label) => label.available && label.render_3d && label.key === 'nodule'
    );
    const supportsNoduleFocus = has3DLung && has3DNodule;

    useEffect(() => {
        meshLoadMeasuredRef.current = false;
        performance.mark(`case-mesh-load-start:${props.caseId}`);
    }, [props.caseId]);

    useEffect(() => {
        if (!supportsNoduleFocus && visibilityPreset !== 'default') {
            setMeshVisibilityPreset('default');
        }
    }, [setMeshVisibilityPreset, supportsNoduleFocus, visibilityPreset]);

    const handleModelLoad = useCallback(() => {
        if (meshLoadMeasuredRef.current) {
            return;
        }

        meshLoadMeasuredRef.current = true;
        performance.mark(`case-mesh-load-complete:${props.caseId}`);
        performance.measure(
            `case-mesh-load:${props.caseId}`,
            `case-mesh-load-start:${props.caseId}`,
            `case-mesh-load-complete:${props.caseId}`
        );
    }, [props.caseId]);

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

            {segmentationLabels.some((label) => label.available && label.render_3d) && (
                <div
                    style={{
                        position: 'absolute',
                        top: 'var(--space-md)',
                        right: 'var(--space-md)',
                        zIndex: 10,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 'var(--space-xs)',
                        padding: '8px 10px',
                        borderRadius: 'var(--radius-md)',
                        background: 'var(--bg-glass)',
                        backdropFilter: 'blur(8px)',
                        border: '1px solid var(--border-subtle)',
                    }}
                >
                    {segmentationLabels
                        .filter((label) => label.available && label.render_3d)
                        .map((label) => (
                            <div
                                key={label.key}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 8,
                                    fontSize: '0.72rem',
                                    color: 'var(--text-secondary)',
                                }}
                            >
                                <span
                                    style={{
                                        width: 10,
                                        height: 10,
                                        borderRadius: '50%',
                                        background: label.color,
                                    }}
                                />
                                {label.display_name}
                            </div>
                        ))}
                </div>
            )}

            <Canvas
                frameloop="demand"
                dpr={[1, 1.5]}
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
                    visibilityPreset={visibilityPreset}
                />
            </Canvas>
        </div>
    );
};

export default ModelViewer;
