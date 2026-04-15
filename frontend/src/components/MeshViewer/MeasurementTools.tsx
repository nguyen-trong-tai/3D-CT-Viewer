import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useThree, type ThreeEvent } from '@react-three/fiber';
import { Html, Line } from '@react-three/drei';
import * as THREE from 'three';

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

interface MeasurementDisplayProps {
    measurements: Measurement[];
    pendingPoint: THREE.Vector3 | null;
    cursorPosition: THREE.Vector3 | null;
}

const generateId = () => Math.random().toString(36).slice(2, 11);

const calculateDistance = (
    p1: THREE.Vector3,
    p2: THREE.Vector3,
    voxelSpacing: [number, number, number]
): number => {
    const dx = (p2.x - p1.x) * voxelSpacing[0];
    const dy = (p2.y - p1.y) * voxelSpacing[1];
    const dz = (p2.z - p1.z) * voxelSpacing[2];
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
};

const isMeasurementDecoration = (object: THREE.Object3D | null | undefined): boolean => {
    if (!object) {
        return false;
    }

    return object.name.includes('measurement') || object.parent?.name.includes('measurement') === true;
};

const resolveMeasurementIntersection = (
    eventIntersections: THREE.Intersection<THREE.Object3D>[],
    raycaster: THREE.Raycaster,
    raycastTargets: THREE.Object3D[]
): THREE.Intersection<THREE.Object3D> | undefined => {
    const fromEvent = eventIntersections.find(
        (intersection) => intersection.object instanceof THREE.Mesh && !isMeasurementDecoration(intersection.object)
    );
    if (fromEvent) {
        return fromEvent;
    }

    return raycaster
        .intersectObjects(raycastTargets, true)
        .find((intersection) => intersection.object instanceof THREE.Mesh && !isMeasurementDecoration(intersection.object));
};

const PointMarker: React.FC<{
    position: THREE.Vector3;
    color?: string;
    size?: number;
}> = ({ position, color = '#22c55e', size = 3 }) => (
    <mesh position={position}>
        <sphereGeometry args={[size, 16, 16]} />
        <meshBasicMaterial color={color} />
    </mesh>
);

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

export const MeasurementDisplay: React.FC<MeasurementDisplayProps> = ({
    measurements,
    pendingPoint,
    cursorPosition,
}) => {
    return (
        <group name="measurements">
            {measurements.map((measurement) => (
                <group key={measurement.id}>
                    <Line
                        points={[measurement.startPoint.position, measurement.endPoint.position]}
                        color="#22c55e"
                        lineWidth={2}
                        dashed={false}
                    />
                    <PointMarker position={measurement.startPoint.position} />
                    <PointMarker position={measurement.endPoint.position} />
                    <DistanceLabel
                        startPoint={measurement.startPoint.position}
                        endPoint={measurement.endPoint.position}
                        distanceMm={measurement.distanceMm}
                    />
                </group>
            ))}

            {pendingPoint && (
                <>
                    <PointMarker position={pendingPoint} color="#f59e0b" />
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

export const MeasurementClickHandler: React.FC<{
    enabled: boolean;
    voxelSpacing: [number, number, number];
    setMeasurements: React.Dispatch<React.SetStateAction<Measurement[]>>;
    pendingPoint: THREE.Vector3 | null;
    setPendingPoint: React.Dispatch<React.SetStateAction<THREE.Vector3 | null>>;
    setCursorPosition: React.Dispatch<React.SetStateAction<THREE.Vector3 | null>>;
    targetObjects?: THREE.Object3D[];
}> = ({
    enabled,
    voxelSpacing,
    setMeasurements,
    pendingPoint,
    setPendingPoint,
    setCursorPosition,
    targetObjects,
}) => {
    const { raycaster, scene, invalidate } = useThree();
    const moveFrameRef = useRef<number | null>(null);
    const latestMoveEventRef = useRef<ThreeEvent<PointerEvent> | null>(null);

    const raycastTargets = useMemo(() => {
        const scopedTargets = targetObjects?.filter((object) => !isMeasurementDecoration(object));
        if (scopedTargets && scopedTargets.length > 0) {
            return scopedTargets;
        }

        return scene.children.filter((object) => !isMeasurementDecoration(object));
    }, [scene, targetObjects]);

    const handlePointerMove = useCallback((event: ThreeEvent<PointerEvent>) => {
        if (!enabled || !pendingPoint) {
            return;
        }

        latestMoveEventRef.current = event;
        if (moveFrameRef.current !== null) {
            return;
        }

        moveFrameRef.current = window.requestAnimationFrame(() => {
            moveFrameRef.current = null;
            const latestEvent = latestMoveEventRef.current;
            if (!latestEvent) {
                return;
            }

            const intersection = resolveMeasurementIntersection(
                latestEvent.intersections,
                raycaster,
                raycastTargets
            );

            setCursorPosition(intersection?.point.clone() ?? null);
            invalidate();
        });
    }, [enabled, invalidate, pendingPoint, raycastTargets, raycaster, setCursorPosition]);

    const handleClick = useCallback((event: ThreeEvent<PointerEvent>) => {
        if (!enabled) {
            return;
        }

        event.stopPropagation();

        const intersection = resolveMeasurementIntersection(
            event.intersections,
            raycaster,
            raycastTargets
        );
        if (!intersection) {
            return;
        }

        const clickedPoint = intersection.point.clone();

        if (!pendingPoint) {
            setPendingPoint(clickedPoint);
            setCursorPosition(clickedPoint);
            invalidate();
            return;
        }

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
        invalidate();
    }, [enabled, invalidate, pendingPoint, raycastTargets, raycaster, setCursorPosition, setMeasurements, setPendingPoint, voxelSpacing]);

    useEffect(() => {
        return () => {
            if (moveFrameRef.current !== null) {
                window.cancelAnimationFrame(moveFrameRef.current);
            }
        };
    }, []);

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
        setMeasurements((prev) => prev.filter((measurement) => measurement.id !== id));
    }, []);

    const toggleMeasurementMode = useCallback(() => {
        setMeasurementMode((prev) => {
            if (prev) {
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
