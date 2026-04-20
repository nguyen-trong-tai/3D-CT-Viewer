import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { PerspectiveCamera, OrbitControls, Grid, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { meshApi } from '../../services/api';
import { Box, RotateCcw, Move3d } from 'lucide-react';
import { useViewerStore, type ToolMode } from '../../stores/viewerStore';
import { DRACO_DECODER_PATH } from '../../utils/draco';
import type {
    CrosshairPosition,
    MeshVisibilityPreset,
    SegmentationVisibility,
} from '../../types';

interface ModelViewerProps {
    caseId: string;
    volumeDimensions: [number, number, number];
    voxelSpacing: [number, number, number];
    showWireframe: boolean;
    showCrosshairGuide?: boolean;
    showGrid?: boolean;
}

type MeshEntry = {
    mesh: THREE.Mesh;
    material: THREE.MeshStandardMaterial;
    baseColor: THREE.Color;
    componentKey: string;
    meshComponentName: string;
    visibilityKey: string;
};

type NoduleFocusTarget = {
    id: string;
    center: THREE.Vector3;
    radius: number;
};

type NoduleTooltipState = {
    id: string;
    x: number;
    y: number;
};

type NoduleHoverPayload = NoduleTooltipState | null;

type SceneAlignment = {
    center: THREE.Vector3;
    size: THREE.Vector3;
};

const COMPONENT_COLOR_MAP: Record<string, string> = {
    lung: '#ef4444',
    left_lung: '#60a5fa',
    right_lung: '#34d399',
    nodule: '#f97316',
};

const FALLBACK_COMPONENT_COLORS = ['#f59e0b', '#a855f7', '#14b8a6', '#fb7185'];
const MATERIAL_EMISSIVE_INTENSITY = 0.18;
const SELECTED_NODULE_EMISSIVE_INTENSITY = 0.7;
const HOVERED_NODULE_EMISSIVE_INTENSITY = 0.38;
const DIMMED_NODULE_OPACITY = 0.28;
const MIN_FOCUS_DISTANCE = 80;
const MAX_FOCUS_DISTANCE = 320;
const HOVER_TINT = new THREE.Color('#fff7ed');
const DEFAULT_CAMERA_POSITION = new THREE.Vector3(250, 200, 250);
const DEFAULT_CAMERA_TARGET = new THREE.Vector3(0, 0, 0);

const formatTooltipVolume = (volumeMm3: number, volumeMl: number): string =>
    volumeMl >= 0.1 ? `${volumeMl.toFixed(2)} ml` : `${volumeMm3.toFixed(1)} mm3`;

const normalizeComponentKey = (value: string | undefined): string =>
    (value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');

const resolveComponentGroupKey = (value: string): string =>
    value.startsWith('nodule_') ? 'nodule' : value;

const expandComponentKeys = (candidateKeys: string[]): string[] => {
    const expanded = new Set<string>();

    candidateKeys.forEach((candidateKey) => {
        if (!candidateKey) {
            return;
        }

        expanded.add(candidateKey);
        expanded.add(resolveComponentGroupKey(candidateKey));
    });

    return Array.from(expanded);
};

const getObjectComponentHints = (object: THREE.Object3D | null | undefined): string[] =>
    [
        typeof object?.userData?.mesh_component_name === 'string' ? object.userData.mesh_component_name : undefined,
        typeof object?.userData?.component_key === 'string' ? object.userData.component_key : undefined,
        object?.name,
        object?.parent?.name,
    ]
        .map(normalizeComponentKey)
        .filter(Boolean);

const pickPrimaryComponentKey = (candidateKeys: string[]): string =>
    candidateKeys.find((candidateKey) =>
        candidateKey.startsWith('nodule_')
        || candidateKey === 'nodule'
        || candidateKey.includes('lung')
    ) ?? candidateKeys[0] ?? '';

const resolveMeshComponentNameFromObject = (object: THREE.Object3D | null | undefined): string | null => {
    let current: THREE.Object3D | null | undefined = object;

    while (current) {
        const componentName = pickPrimaryComponentKey(getObjectComponentHints(current));
        if (componentName) {
            return componentName;
        }
        current = current.parent;
    }

    return null;
};

const resolveNoduleComponentNameFromEvent = (event: ThreeEvent<PointerEvent | MouseEvent>): string | null => {
    for (const intersection of event.intersections) {
        const componentName = resolveMeshComponentNameFromObject(intersection.object);
        if (componentName?.startsWith('nodule_')) {
            return componentName;
        }
    }

    const fallbackName = resolveMeshComponentNameFromObject(event.object);
    return fallbackName?.startsWith('nodule_') ? fallbackName : null;
};

const findMatchingLabel = (
    candidateKeys: string[],
    labels: Array<{
        key: string;
        color: string;
        mesh_component_name?: string | null;
    }>
) => {
    for (const candidateKey of expandComponentKeys(candidateKeys)) {
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

const clampCrosshairToVolume = (
    crosshair: CrosshairPosition,
    volumeDimensions: [number, number, number]
) => ({
    x: THREE.MathUtils.clamp(crosshair.x, 0, Math.max(volumeDimensions[0] - 1, 0)),
    y: THREE.MathUtils.clamp(crosshair.y, 0, Math.max(volumeDimensions[1] - 1, 0)),
    z: THREE.MathUtils.clamp(crosshair.z, 0, Math.max(volumeDimensions[2] - 1, 0)),
});

const crosshairToScenePoint = (
    crosshair: CrosshairPosition,
    voxelSpacing: [number, number, number],
    sceneAlignment: SceneAlignment
) =>
    new THREE.Vector3(
        crosshair.x * voxelSpacing[0],
        crosshair.y * voxelSpacing[1],
        crosshair.z * voxelSpacing[2]
    ).sub(sceneAlignment.center);

const CrosshairGuide: React.FC<{
    crosshair: CrosshairPosition;
    volumeDimensions: [number, number, number];
    voxelSpacing: [number, number, number];
    sceneAlignment: SceneAlignment;
    visible: boolean;
}> = ({ crosshair, volumeDimensions, voxelSpacing, sceneAlignment, visible }) => {
    if (!visible) return null;

    const clampedCrosshair = clampCrosshairToVolume(crosshair, volumeDimensions);
    const position = crosshairToScenePoint(clampedCrosshair, voxelSpacing, sceneAlignment);
    const lineThickness = Math.max(Math.min(sceneAlignment.size.length() * 0.003, 1.8), 0.8);
    const markerRadius = Math.max(Math.min(sceneAlignment.size.length() * 0.012, 7), 3.2);
    const axisLengths = {
        x: Math.max(sceneAlignment.size.x + 28, 120),
        y: Math.max(sceneAlignment.size.y + 28, 120),
        z: Math.max(sceneAlignment.size.z + 28, 120),
    };

    return (
        <group position={position.toArray()}>
            <mesh>
                <boxGeometry args={[axisLengths.x, lineThickness, lineThickness]} />
                <meshBasicMaterial color="#f59e0b" transparent opacity={0.78} depthWrite={false} depthTest={false} />
            </mesh>
            <mesh>
                <boxGeometry args={[lineThickness, axisLengths.y, lineThickness]} />
                <meshBasicMaterial color="#10b981" transparent opacity={0.78} depthWrite={false} depthTest={false} />
            </mesh>
            <mesh>
                <boxGeometry args={[lineThickness, lineThickness, axisLengths.z]} />
                <meshBasicMaterial color="#60a5fa" transparent opacity={0.82} depthWrite={false} depthTest={false} />
            </mesh>
            <mesh>
                <sphereGeometry args={[markerRadius, 20, 20]} />
                <meshBasicMaterial color="#f8fafc" transparent opacity={0.92} depthWrite={false} depthTest={false} />
            </mesh>
        </group>
    );
};

const ProcessedMesh: React.FC<{
    url: string;
    wireframe: boolean;
    componentVisibility: SegmentationVisibility;
    visibilityPreset: MeshVisibilityPreset;
    activeTool: ToolMode;
    selectedNoduleId: string | null;
    hoveredNoduleId: string | null;
    labels: Array<{
        key: string;
        color: string;
        mesh_component_name?: string | null;
    }>;
    color?: string;
    onLoad?: () => void;
    onNoduleClick?: (noduleId: string) => void;
    onHoverNoduleChange?: (payload: NoduleHoverPayload) => void;
    onFocusTargetsReady?: (targets: NoduleFocusTarget[]) => void;
    crosshair: CrosshairPosition;
    volumeDimensions: [number, number, number];
    voxelSpacing: [number, number, number];
    showCrosshairGuide: boolean;
}> = ({
    url,
    wireframe,
    componentVisibility,
    visibilityPreset,
    activeTool,
    selectedNoduleId,
    hoveredNoduleId,
    labels,
    color = '#ef4444',
    onLoad,
    onNoduleClick,
    onHoverNoduleChange,
    onFocusTargetsReady,
    crosshair,
    volumeDimensions,
    voxelSpacing,
    showCrosshairGuide,
}) => {
    const invalidate = useThree((state) => state.invalidate);
    const { scene } = useGLTF(url, DRACO_DECODER_PATH, false);

    const { clonedScene, meshEntries, materials, focusTargets, sceneAlignment } = useMemo(() => {
        const clone = scene.clone(true);
        const bounds = new THREE.Box3().setFromObject(clone);
        const createdMaterials: THREE.MeshStandardMaterial[] = [];
        const createdEntries: MeshEntry[] = [];
        let meshIndex = 0;
        const alignment: SceneAlignment = {
            center: new THREE.Vector3(),
            size: bounds.isEmpty() ? new THREE.Vector3(200, 200, 200) : bounds.getSize(new THREE.Vector3()),
        };

        if (!bounds.isEmpty()) {
            bounds.getCenter(alignment.center);
            clone.position.sub(alignment.center);
        }

        clone.traverse((child) => {
            if (!(child as THREE.Mesh).isMesh) {
                return;
            }

            const mesh = child as THREE.Mesh;
            const candidateKeys = getObjectComponentHints(mesh);
            const meshComponentName = pickPrimaryComponentKey(candidateKeys);
            const componentKey = resolveComponentGroupKey(meshComponentName);
            const matchedLabel = findMatchingLabel(candidateKeys, labels);
            const visibilityKey = matchedLabel?.key ?? componentKey ?? meshComponentName;
            const surfaceColor = matchedLabel?.color
                ? new THREE.Color(matchedLabel.color)
                : resolveMeshColor(mesh, color, meshIndex);

            const material = new THREE.MeshStandardMaterial({
                color: surfaceColor,
                emissive: surfaceColor.clone(),
                emissiveIntensity: MATERIAL_EMISSIVE_INTENSITY,
                roughness: 0.22,
                metalness: 0.03,
                transparent: true,
                opacity: 1.0,
                side: THREE.DoubleSide,
            });

            mesh.material = material;
            mesh.userData.component_key = componentKey;
            mesh.userData.mesh_component_name = meshComponentName;
            mesh.frustumCulled = true;

            createdMaterials.push(material);
            createdEntries.push({
                mesh,
                material,
                baseColor: surfaceColor.clone(),
                componentKey,
                meshComponentName,
                visibilityKey,
            });
            meshIndex += 1;
        });

        clone.updateMatrixWorld(true);

        const createdFocusTargets = createdEntries
            .filter((entry) => entry.componentKey === 'nodule' && entry.meshComponentName.startsWith('nodule_'))
            .map((entry) => {
                const box = new THREE.Box3().setFromObject(entry.mesh);
                const center = box.getCenter(new THREE.Vector3());
                const size = box.getSize(new THREE.Vector3());

                return {
                    id: entry.meshComponentName,
                    center,
                    radius: Math.max(size.length() * 0.3, 14),
                };
            });

        return {
            clonedScene: clone,
            meshEntries: createdEntries,
            materials: createdMaterials,
            focusTargets: createdFocusTargets,
            sceneAlignment: alignment,
        };
    }, [color, labels, scene]);

    useEffect(() => {
        onLoad?.();
        invalidate();
    }, [clonedScene, invalidate, onLoad]);

    useEffect(() => {
        onFocusTargetsReady?.(focusTargets);
    }, [focusTargets, onFocusTargetsReady]);

    useEffect(() => {
        if (activeTool === 'pan' || activeTool === 'zoom') {
            onHoverNoduleChange?.(null);
        }
    }, [activeTool, onHoverNoduleChange]);

    useEffect(() => {
        meshEntries.forEach(({ mesh, componentKey, visibilityKey }) => {
            const resolvedVisibilityKey = visibilityKey || componentKey;
            mesh.visible = resolvedVisibilityKey ? (componentVisibility[resolvedVisibilityKey] ?? true) : true;
        });
        invalidate();
    }, [componentVisibility, invalidate, meshEntries]);

    useEffect(() => {
        const hasNoduleSelection = Boolean(selectedNoduleId);

        meshEntries.forEach(({ componentKey, meshComponentName, material, baseColor }) => {
            const baseOpacity = getOpacityForComponent(componentKey, visibilityPreset);
            const isSelectedNodule = componentKey === 'nodule' && selectedNoduleId === meshComponentName;
            const isHoveredNodule =
                componentKey === 'nodule'
                && hoveredNoduleId === meshComponentName
                && !isSelectedNodule;
            const isOtherNodule = componentKey === 'nodule' && hasNoduleSelection && !isSelectedNodule;
            const opacity = isHoveredNodule
                ? Math.max(baseOpacity, hasNoduleSelection ? 0.55 : baseOpacity)
                : isOtherNodule
                    ? Math.min(baseOpacity, DIMMED_NODULE_OPACITY)
                    : baseOpacity;

            material.color.copy(baseColor);
            if (isHoveredNodule) {
                material.color.lerp(HOVER_TINT, 0.16);
            }
            material.emissive.copy(baseColor);
            material.emissiveIntensity = isSelectedNodule
                ? SELECTED_NODULE_EMISSIVE_INTENSITY
                : isHoveredNodule
                    ? HOVERED_NODULE_EMISSIVE_INTENSITY
                : componentKey === 'nodule' && hasNoduleSelection
                    ? 0.08
                    : MATERIAL_EMISSIVE_INTENSITY;
            material.roughness = isSelectedNodule ? 0.12 : isHoveredNodule ? 0.16 : 0.22;
            material.opacity = opacity;
            material.transparent = opacity < 0.999 || wireframe;
            material.depthWrite = opacity >= 0.999 && !wireframe;
            material.wireframe = wireframe;
            material.needsUpdate = true;
        });
        invalidate();
    }, [hoveredNoduleId, invalidate, meshEntries, selectedNoduleId, visibilityPreset, wireframe]);

    useEffect(() => {
        return () => {
            materials.forEach((material) => material.dispose());
        };
    }, [materials]);

    const handleSceneClick = useCallback((event: ThreeEvent<MouseEvent>) => {
        if (!onNoduleClick || activeTool === 'pan' || activeTool === 'zoom' || event.delta > 4) {
            return;
        }

        const meshComponentName = resolveNoduleComponentNameFromEvent(event);
        if (!meshComponentName) {
            return;
        }

        event.stopPropagation();
        onNoduleClick(meshComponentName);
        invalidate();
    }, [activeTool, invalidate, onNoduleClick]);

    const handlePointerMove = useCallback((event: ThreeEvent<PointerEvent>) => {
        if (!onHoverNoduleChange || activeTool === 'pan' || activeTool === 'zoom') {
            return;
        }

        const meshComponentName = resolveNoduleComponentNameFromEvent(event);
        onHoverNoduleChange(
            meshComponentName
                ? {
                    id: meshComponentName,
                    x: event.nativeEvent.offsetX,
                    y: event.nativeEvent.offsetY,
                }
                : null
        );
    }, [activeTool, onHoverNoduleChange]);

    const handlePointerLeave = useCallback(() => {
        onHoverNoduleChange?.(null);
    }, [onHoverNoduleChange]);

    return (
        <group
            onClick={handleSceneClick}
            onPointerMove={handlePointerMove}
            onPointerLeave={handlePointerLeave}
        >
            <primitive object={clonedScene} />
            <CrosshairGuide
                crosshair={crosshair}
                volumeDimensions={volumeDimensions}
                voxelSpacing={voxelSpacing}
                sceneAlignment={sceneAlignment}
                visible={showCrosshairGuide}
            />
        </group>
    );
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
    activeTool: ToolMode;
    selectedNoduleId: string | null;
    hoveredNoduleId: string | null;
    onNoduleClick?: (noduleId: string) => void;
    onHoverNoduleChange?: (payload: NoduleHoverPayload) => void;
    onFocusTargetsReady?: (targets: NoduleFocusTarget[]) => void;
    crosshair: CrosshairPosition;
}>(function SceneContent({
    caseId,
    volumeDimensions,
    voxelSpacing,
    showWireframe,
    showCrosshairGuide = true,
    showGrid = false,
    onModelLoad,
    visibilityPreset,
    activeTool,
    selectedNoduleId,
    hoveredNoduleId,
    onNoduleClick,
    onHoverNoduleChange,
    onFocusTargetsReady,
    crosshair,
}) {
    const meshUrl = meshApi.getMeshUrl(caseId);
    const componentVisibility = useViewerStore((state) => state.segmentationVisibility);
    const segmentationLabels = useViewerStore((state) => state.segmentationLabels);

    return (
        <>
            <ambientLight intensity={0.8} />
            <hemisphereLight
                args={['#dbeafe', '#05070a', 0.72]}
            />
            <directionalLight position={[120, 160, 90]} intensity={1.15} color="#fff4d6" />
            <directionalLight position={[-90, 60, -110]} intensity={0.45} color="#bfdbfe" />
            <directionalLight position={[10, 40, -220]} intensity={0.55} color="#a5f3fc" />

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

            <Suspense fallback={<LoadingFallback />}>
                <ProcessedMesh
                    url={meshUrl}
                    wireframe={showWireframe}
                    componentVisibility={componentVisibility}
                    visibilityPreset={visibilityPreset}
                    activeTool={activeTool}
                    selectedNoduleId={selectedNoduleId}
                    hoveredNoduleId={hoveredNoduleId}
                    labels={segmentationLabels}
                    onLoad={onModelLoad}
                    onNoduleClick={onNoduleClick}
                    onHoverNoduleChange={onHoverNoduleChange}
                    onFocusTargetsReady={onFocusTargetsReady}
                    crosshair={crosshair}
                    volumeDimensions={volumeDimensions}
                    voxelSpacing={voxelSpacing}
                    showCrosshairGuide={showCrosshairGuide}
                />
            </Suspense>
        </>
    );
});

type CameraFocusTween = {
    startPosition: THREE.Vector3;
    endPosition: THREE.Vector3;
    startTarget: THREE.Vector3;
    endTarget: THREE.Vector3;
    startTime: number;
    durationMs: number;
};

const ViewerControls: React.FC<{
    focusTarget: NoduleFocusTarget | null;
    focusVersion: number;
}> = ({ focusTarget, focusVersion }) => {
    const activeTool = useViewerStore((state) => state.activeTool);
    const controlsRef = useRef<OrbitControlsImpl | null>(null);
    const tweenRef = useRef<CameraFocusTween | null>(null);
    const defaultViewRef = useRef<{ position: THREE.Vector3; target: THREE.Vector3 } | null>(null);
    const previousFocusedIdRef = useRef<string | null>(null);
    const camera = useThree((state) => state.camera);
    const invalidate = useThree((state) => state.invalidate);

    const startCameraTween = useCallback((endPosition: THREE.Vector3, endTarget: THREE.Vector3) => {
        const controls = controlsRef.current;
        if (!controls) {
            return;
        }

        tweenRef.current = {
            startPosition: camera.position.clone(),
            endPosition,
            startTarget: controls.target.clone(),
            endTarget,
            startTime: performance.now(),
            durationMs: 520,
        };

        invalidate();
    }, [camera, invalidate]);

    useEffect(() => {
        const controls = controlsRef.current;
        if (!controls || defaultViewRef.current) {
            return;
        }

        camera.position.copy(DEFAULT_CAMERA_POSITION);
        controls.target.copy(DEFAULT_CAMERA_TARGET);
        controls.update();
        defaultViewRef.current = {
            position: DEFAULT_CAMERA_POSITION.clone(),
            target: DEFAULT_CAMERA_TARGET.clone(),
        };
        controls.saveState();
        invalidate();
    }, [camera, invalidate]);

    useEffect(() => {
        const handleReset = () => {
            tweenRef.current = null;
            controlsRef.current?.reset();
            invalidate();
        };

        window.addEventListener('reset-view', handleReset);
        return () => window.removeEventListener('reset-view', handleReset);
    }, [invalidate]);

    useEffect(() => {
        invalidate();
    }, [activeTool, invalidate]);

    useEffect(() => {
        if (!focusTarget || !controlsRef.current) {
            if (previousFocusedIdRef.current && defaultViewRef.current) {
                startCameraTween(
                    defaultViewRef.current.position.clone(),
                    defaultViewRef.current.target.clone()
                );
            }
            previousFocusedIdRef.current = null;
            return;
        }

        const controls = controlsRef.current;
        const direction = camera.position.clone().sub(controls.target);

        if (direction.lengthSq() < 1e-6) {
            direction.set(1, 0.7, 1);
        }

        direction.normalize();

        const focusDistance = THREE.MathUtils.clamp(
            focusTarget.radius * 4.4,
            MIN_FOCUS_DISTANCE,
            MAX_FOCUS_DISTANCE
        );
        const focusOffset = direction.multiplyScalar(focusDistance).add(new THREE.Vector3(
            focusTarget.radius * 0.2,
            focusTarget.radius * 0.35,
            focusTarget.radius * 0.2
        ));

        startCameraTween(
            focusTarget.center.clone().add(focusOffset),
            focusTarget.center.clone()
        );
        previousFocusedIdRef.current = focusTarget.id;
    }, [camera, focusTarget, focusVersion, startCameraTween]);

    useFrame(() => {
        const tween = tweenRef.current;
        const controls = controlsRef.current;
        if (!tween || !controls) {
            return;
        }

        const elapsed = performance.now() - tween.startTime;
        const progress = Math.min(1, elapsed / tween.durationMs);
        const eased = 1 - Math.pow(1 - progress, 3);

        camera.position.lerpVectors(tween.startPosition, tween.endPosition, eased);
        controls.target.lerpVectors(tween.startTarget, tween.endTarget, eased);
        controls.update();
        invalidate();

        if (progress >= 1) {
            tweenRef.current = null;
        }
    });

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
    const noduleEntities = useViewerStore((state) => state.noduleEntities);
    const visibilityPreset = useViewerStore((state) => state.meshVisibilityPreset);
    const setMeshVisibilityPreset = useViewerStore((state) => state.setMeshVisibilityPreset);
    const activeTool = useViewerStore((state) => state.activeTool);
    const selectedNoduleId = useViewerStore((state) => state.selectedNoduleId);
    const focusedNoduleId = useViewerStore((state) => state.focusedNoduleId);
    const noduleFocusVersion = useViewerStore((state) => state.noduleFocusVersion);
    const focusNodule = useViewerStore((state) => state.focusNodule);
    const crosshair = useViewerStore((state) => state.mprCrosshair);
    const setMprCrosshair = useViewerStore((state) => state.setMprCrosshair);
    const setMprCrosshairCaseId = useViewerStore((state) => state.setMprCrosshairCaseId);
    const meshLoadMeasuredRef = useRef(false);
    const lastSyncedFocusIdRef = useRef<string | null>(null);
    const [focusTargets, setFocusTargets] = useState<NoduleFocusTarget[]>([]);
    const [hoveredNoduleId, setHoveredNoduleId] = useState<string | null>(null);
    const [hoveredTooltip, setHoveredTooltip] = useState<NoduleTooltipState | null>(null);
    const has3DLung = segmentationLabels.some(
        (label) => label.available && label.render_3d && (label.key === 'left_lung' || label.key === 'right_lung' || label.key === 'lung')
    );
    const has3DNodule = segmentationLabels.some(
        (label) => label.available && label.render_3d && label.key === 'nodule'
    );
    const supportsNoduleFocus = has3DLung && has3DNodule;

    useEffect(() => {
        meshLoadMeasuredRef.current = false;
        setFocusTargets([]);
        setHoveredNoduleId(null);
        setHoveredTooltip(null);
        performance.mark(`case-mesh-load-start:${props.caseId}`);
    }, [props.caseId]);

    useEffect(() => {
        if (selectedNoduleId) {
            setHoveredNoduleId(null);
            setHoveredTooltip(null);
        }
    }, [selectedNoduleId]);

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

    const selectedFocusTarget = useMemo(
        () => focusTargets.find((target) => target.id === focusedNoduleId) ?? null,
        [focusTargets, focusedNoduleId]
    );
    const hoveredNoduleEntity = useMemo(
        () => noduleEntities.find((nodule) => nodule.id === hoveredTooltip?.id) ?? null,
        [hoveredTooltip?.id, noduleEntities]
    );
    const focusedNoduleEntity = useMemo(
        () => noduleEntities.find((nodule) => nodule.id === focusedNoduleId) ?? null,
        [focusedNoduleId, noduleEntities]
    );
    const canvasCursor = hoveredNoduleId ? 'pointer' : 'default';
    const handleHoverNoduleChange = useCallback((payload: NoduleHoverPayload) => {
        const nextId = payload?.id ?? null;
        setHoveredNoduleId((current) => (current === nextId ? current : nextId));
        setHoveredTooltip(payload);
    }, []);
    const syncCrosshairToNodule = useCallback((nodule: typeof focusedNoduleEntity) => {
        if (!nodule) {
            return;
        }

        const nextCrosshair = clampCrosshairToVolume(
            {
                x: Math.round(nodule.centroid_xyz[0]),
                y: Math.round(nodule.centroid_xyz[1]),
                z: Math.round(nodule.centroid_xyz[2]),
            },
            props.volumeDimensions
        );

        setMprCrosshairCaseId(props.caseId);
        setMprCrosshair(nextCrosshair);
    }, [props.caseId, props.volumeDimensions, setMprCrosshair, setMprCrosshairCaseId]);

    useEffect(() => {
        if (!focusedNoduleEntity) {
            lastSyncedFocusIdRef.current = null;
            return;
        }

        if (lastSyncedFocusIdRef.current === focusedNoduleEntity.id) {
            return;
        }

        syncCrosshairToNodule(focusedNoduleEntity);
        lastSyncedFocusIdRef.current = focusedNoduleEntity.id;
    }, [focusedNoduleEntity, syncCrosshairToNodule]);

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
                {props.showCrosshairGuide && (
                    <div
                        style={{
                            background: 'var(--bg-glass)',
                            backdropFilter: 'blur(8px)',
                            padding: '4px 12px',
                            borderRadius: 'var(--radius-md)',
                            border: '1px solid var(--border-subtle)',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            color: 'var(--text-secondary)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: 'var(--space-xs)',
                            fontFamily: 'monospace',
                        }}
                    >
                        {`X ${crosshair.x} | Y ${crosshair.y} | Z ${crosshair.z}`}
                    </div>
                )}
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
                style={{ background: 'transparent', cursor: canvasCursor }}
            >
                <PerspectiveCamera
                    makeDefault
                    position={DEFAULT_CAMERA_POSITION.toArray()}
                    fov={45}
                    near={1}
                    far={3000}
                />
                <ViewerControls focusTarget={selectedFocusTarget} focusVersion={noduleFocusVersion} />
                <SceneContent
                    {...props}
                    onModelLoad={handleModelLoad}
                    visibilityPreset={visibilityPreset}
                    activeTool={activeTool}
                    selectedNoduleId={selectedNoduleId}
                    hoveredNoduleId={hoveredNoduleId}
                    onNoduleClick={focusNodule}
                    onHoverNoduleChange={handleHoverNoduleChange}
                    onFocusTargetsReady={setFocusTargets}
                    crosshair={crosshair}
                />
            </Canvas>

            {hoveredTooltip && hoveredNoduleEntity && (
                <div
                    style={{
                        position: 'absolute',
                        left: hoveredTooltip.x + 14,
                        top: hoveredTooltip.y + 14,
                        zIndex: 25,
                        minWidth: 160,
                        maxWidth: 220,
                        pointerEvents: 'none',
                        padding: '10px 12px',
                        borderRadius: 'var(--radius-md)',
                        background: 'rgba(12, 16, 24, 0.92)',
                        border: '1px solid rgba(249, 115, 22, 0.35)',
                        boxShadow: 'var(--shadow-lg)',
                        backdropFilter: 'blur(10px)',
                    }}
                >
                    <div style={{ fontSize: '0.84rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
                        {hoveredNoduleEntity.display_name}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
                        {hoveredNoduleEntity.estimated_diameter_mm.toFixed(1)} mm
                        {' • '}
                        {formatTooltipVolume(hoveredNoduleEntity.volume_mm3, hoveredNoduleEntity.volume_ml)}
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 4 }}>
                        Slice {hoveredNoduleEntity.slice_range[0]}-{hoveredNoduleEntity.slice_range[1]}
                    </div>
                </div>
            )}
        </div>
    );
};

export default ModelViewer;
