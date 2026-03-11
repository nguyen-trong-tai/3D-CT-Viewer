import React, { useState, useRef, useCallback, useMemo } from 'react';
import { useThree, type ThreeEvent } from '@react-three/fiber';
import { Html, Line } from '@react-three/drei';
import * as THREE from 'three';

// Types
export interface MeasurementPoint {
    id: string;
    position: THREE.Vector3;
}

export interface Measurement {
    id: string;
    startPoint: MeasurementPoint;
    endPoint: MeasurementPoint;
    distanceMm: number;
}

interface MeasurementToolsProps {
    enabled: boolean;
    voxelSpacing: [number, number, number];
    onMeasurementComplete?: (measurement: Measurement) => void;
}

interface MeasurementDisplayProps {
    measurements: Measurement[];
    pendingPoint: THREE.Vector3 | null;
    cursorPosition: THREE.Vector3 | null;
}

// Generate unique ID
const generateId = () => Math.random().toString(36).substr(2, 9);

/**
 * Calculate real-world distance considering voxel spacing
 */
const calculateDistance = (
    p1: THREE.Vector3,
    p2: THREE.Vector3,
    voxelSpacing: [number, number, number]
): number => {
    // Apply voxel spacing to convert from model units to mm
    const dx = (p2.x - p1.x) * voxelSpacing[0];
    const dy = (p2.y - p1.y) * voxelSpacing[1];
    const dz = (p2.z - p1.z) * voxelSpacing[2];
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
};

/**
 * Point Marker Component
 * Renders a small sphere at measurement point
 */
const PointMarker: React.FC<{
    position: THREE.Vector3;
    color?: string;
    size?: number;
}> = ({ position, color = '#22c55e', size = 3 }) => {
    return (
        <mesh position={position}>
            <sphereGeometry args={[size, 16, 16]} />
            <meshBasicMaterial color={color} />
        </mesh>
    );
};

/**
 * Distance Label Component
 * Shows distance value at midpoint of measurement line
 */
const DistanceLabel: React.FC<{
    startPoint: THREE.Vector3;
    endPoint: THREE.Vector3;
    distanceMm: number;
}> = ({ startPoint, endPoint, distanceMm }) => {
    const midpoint = useMemo(() => {
        return new THREE.Vector3(
            (startPoint.x + endPoint.x) / 2,
            (startPoint.y + endPoint.y) / 2,
            (startPoint.z + endPoint.z) / 2
        );
    }, [startPoint, endPoint]);

    // Format distance
    const displayValue = distanceMm >= 10 
        ? `${distanceMm.toFixed(1)} mm`
        : `${distanceMm.toFixed(2)} mm`;

    return (
        <Html position={midpoint} center>
            <div
                style={{
                    background: 'rgba(0, 0, 0, 0.85)',
                    color: '#22c55e',
                    padding: '4px 8px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    fontWeight: 600,
                    fontFamily: 'monospace',
                    whiteSpace: 'nowrap',
                    border: '1px solid rgba(34, 197, 94, 0.5)',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
                    pointerEvents: 'none',
                }}
            >
                {displayValue}
            </div>
        </Html>
    );
};

/**
 * Measurement Display Component
 * Renders all measurements (lines, points, labels)
 */
export const MeasurementDisplay: React.FC<MeasurementDisplayProps> = ({
    measurements,
    pendingPoint,
    cursorPosition,
}) => {
    return (
        <group name="measurements">
            {/* Completed measurements */}
            {measurements.map((m) => (
                <group key={m.id}>
                    {/* Line between points */}
                    <Line
                        points={[m.startPoint.position, m.endPoint.position]}
                        color="#22c55e"
                        lineWidth={2}
                        dashed={false}
                    />
                    {/* Start point marker */}
                    <PointMarker position={m.startPoint.position} />
                    {/* End point marker */}
                    <PointMarker position={m.endPoint.position} />
                    {/* Distance label */}
                    <DistanceLabel
                        startPoint={m.startPoint.position}
                        endPoint={m.endPoint.position}
                        distanceMm={m.distanceMm}
                    />
                </group>
            ))}

            {/* Pending measurement (first point selected, waiting for second) */}
            {pendingPoint && (
                <>
                    <PointMarker position={pendingPoint} color="#f59e0b" />
                    {/* Preview line to cursor */}
                    {cursorPosition && (
                        <Line
                            points={[pendingPoint, cursorPosition]}
                            color="#f59e0b"
                            lineWidth={1}
                            dashed
                        />
                    )}
                </>
            )}
        </group>
    );
};

/**
 * Measurement Click Handler Component
 * Handles raycasting and point selection
 */
export const MeasurementClickHandler: React.FC<{
    enabled: boolean;
    voxelSpacing: [number, number, number];
    measurements: Measurement[];
    setMeasurements: React.Dispatch<React.SetStateAction<Measurement[]>>;
    pendingPoint: THREE.Vector3 | null;
    setPendingPoint: React.Dispatch<React.SetStateAction<THREE.Vector3 | null>>;
    setCursorPosition: React.Dispatch<React.SetStateAction<THREE.Vector3 | null>>;
}> = ({
    enabled,
    voxelSpacing,
    measurements,
    setMeasurements,
    pendingPoint,
    setPendingPoint,
    setCursorPosition,
}) => {
    const { camera, raycaster, scene } = useThree();

    // Handle pointer move for preview line
    const handlePointerMove = useCallback((event: ThreeEvent<PointerEvent>) => {
        if (!enabled || !pendingPoint) return;
        
        // Get intersection point with mesh
        const intersects = raycaster.intersectObjects(scene.children, true);
        const meshIntersect = intersects.find(
            (i) => i.object.type === 'Mesh' && i.object.name !== 'measurements'
        );
        
        if (meshIntersect) {
            setCursorPosition(meshIntersect.point.clone());
        }
    }, [enabled, pendingPoint, raycaster, scene, setCursorPosition]);

    // Handle click to add measurement point
    const handleClick = useCallback((event: ThreeEvent<MouseEvent>) => {
        if (!enabled) return;

        // Prevent event propagation
        event.stopPropagation();

        // Get intersection point with mesh
        const intersects = raycaster.intersectObjects(scene.children, true);
        const meshIntersect = intersects.find(
            (i) => i.object.type === 'Mesh' && 
                   !i.object.name.includes('measurement') &&
                   !i.object.parent?.name.includes('measurement')
        );

        if (!meshIntersect) return;

        const clickedPoint = meshIntersect.point.clone();

        if (!pendingPoint) {
            // First point - start new measurement
            setPendingPoint(clickedPoint);
        } else {
            // Second point - complete measurement
            const distance = calculateDistance(pendingPoint, clickedPoint, voxelSpacing);
            
            const newMeasurement: Measurement = {
                id: generateId(),
                startPoint: {
                    id: generateId(),
                    position: pendingPoint,
                },
                endPoint: {
                    id: generateId(),
                    position: clickedPoint,
                },
                distanceMm: distance,
            };

            setMeasurements((prev) => [...prev, newMeasurement]);
            setPendingPoint(null);
            setCursorPosition(null);
        }
    }, [enabled, pendingPoint, raycaster, scene, voxelSpacing, setMeasurements, setPendingPoint, setCursorPosition]);

    // Invisible plane to catch all clicks when measurement mode is active
    if (!enabled) return null;

    return (
        <mesh
            name="measurement-click-catcher"
            onClick={handleClick}
            onPointerMove={handlePointerMove}
            visible={false}
        >
            <sphereGeometry args={[2000, 32, 32]} />
            <meshBasicMaterial side={THREE.BackSide} transparent opacity={0} />
        </mesh>
    );
};

/**
 * Main Measurement Tools Hook
 * Manages measurement state and provides components
 */
export const useMeasurementTools = (voxelSpacing: [number, number, number]) => {
    const [measurements, setMeasurements] = useState<Measurement[]>([]);
    const [pendingPoint, setPendingPoint] = useState<THREE.Vector3 | null>(null);
    const [cursorPosition, setCursorPosition] = useState<THREE.Vector3 | null>(null);
    const [measurementMode, setMeasurementMode] = useState(false);

    const clearMeasurements = useCallback(() => {
        setMeasurements([]);
        setPendingPoint(null);
        setCursorPosition(null);
    }, []);

    const cancelPending = useCallback(() => {
        setPendingPoint(null);
        setCursorPosition(null);
    }, []);

    const deleteMeasurement = useCallback((id: string) => {
        setMeasurements((prev) => prev.filter((m) => m.id !== id));
    }, []);

    const toggleMeasurementMode = useCallback(() => {
        setMeasurementMode((prev) => {
            if (prev) {
                // Turning off - cancel pending
                setPendingPoint(null);
                setCursorPosition(null);
            }
            return !prev;
        });
    }, []);

    return {
        measurements,
        setMeasurements,
        pendingPoint,
        setPendingPoint,
        cursorPosition,
        setCursorPosition,
        measurementMode,
        setMeasurementMode,
        toggleMeasurementMode,
        clearMeasurements,
        cancelPending,
        deleteMeasurement,
        voxelSpacing,
    };
};

export default useMeasurementTools;
