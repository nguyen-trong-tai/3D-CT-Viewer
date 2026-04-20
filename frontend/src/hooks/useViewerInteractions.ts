import React, { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { type MPRView } from '../types';

interface ViewerInteractionsProps {
    canvasRef: React.RefObject<HTMLCanvasElement | null>;
    dims: { width: number; height: number; maxSlice: number; spacing: { x: number; y: number } } | null;
    volume: any;
    viewType: MPRView;
    crosshair: { x: number; y: number; z: number };
    setCrosshair: (crosshair: { x: number; y: number; z: number }) => void;
    activeTool: string;
}

export function useViewerInteractions({
    canvasRef,
    dims,
    volume,
    viewType,
    crosshair,
    setCrosshair,
    activeTool
}: ViewerInteractionsProps) {
    const [zoom, setZoom] = useState(1);
    const [pan, setPan] = useState({ x: 0, y: 0 });
    const [isDragging, setIsDragging] = useState(false);
    const [isZooming, setIsZooming] = useState(false);
    const [isDraggingCrosshair, setIsDraggingCrosshair] = useState(false);

    const dragStartRef = useRef({ x: 0, y: 0 });
    const zoomStartRef = useRef({ x: 0, y: 0, initialZoom: 1 });

    const crosshairPos = useMemo(() => {
        if (!dims || !volume) return null;
        let cx = 0;
        let cy = 0;
        const widthDenominator = Math.max(dims.width - 1, 1);
        const heightDenominator = Math.max(dims.height - 1, 1);
        
        if (viewType === 'AXIAL') {
            cx = (crosshair.x / widthDenominator) * 100;
            cy = (crosshair.y / heightDenominator) * 100;
        } else if (viewType === 'CORONAL') {
            cx = (crosshair.x / widthDenominator) * 100;
            cy = ((dims.height - 1 - crosshair.z) / heightDenominator) * 100;
        } else if (viewType === 'SAGITTAL') {
            cx = (crosshair.y / widthDenominator) * 100;
            cy = ((dims.height - 1 - crosshair.z) / heightDenominator) * 100;
        }
        return { cx, cy };
    }, [viewType, crosshair, dims, volume]);

    const updateCrosshairFromMouse = useCallback((e: React.MouseEvent) => {
        if (!canvasRef.current || !dims || !volume) return;
        const rect = canvasRef.current.getBoundingClientRect();
        
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        const pctX = Math.max(0, Math.min(1, x / rect.width));
        const pctY = Math.max(0, Math.min(1, y / rect.height));

        const newX = Math.round(pctX * Math.max(dims.width - 1, 0));
        const newY = Math.round(pctY * Math.max(dims.height - 1, 0));

        let voxelX = crosshair.x;
        let voxelY = crosshair.y;
        let voxelZ = crosshair.z;

        if (viewType === 'AXIAL') {
            voxelX = newX;
            voxelY = newY;
        } else if (viewType === 'CORONAL') {
            voxelX = newX;
            voxelZ = dims.height - 1 - newY;
        } else if (viewType === 'SAGITTAL') {
            voxelY = newX;
            voxelZ = dims.height - 1 - newY;
        }

        voxelX = Math.max(0, Math.min(volume.shape[0] - 1, voxelX));
        voxelY = Math.max(0, Math.min(volume.shape[1] - 1, voxelY));
        voxelZ = Math.max(0, Math.min(volume.shape[2] - 1, voxelZ));

        setCrosshair({x: voxelX, y: voxelY, z: voxelZ});
    }, [canvasRef, dims, viewType, crosshair, volume, setCrosshair]);

    const handleMouseDown = useCallback((e: React.MouseEvent) => {
        if (e.button === 0) {
            // Left click overrides based on active tool
            if (activeTool === 'pan') {
                setIsDragging(true);
                dragStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
            } else if (activeTool === 'zoom') {
                setIsZooming(true);
                zoomStartRef.current = { x: e.clientX, y: e.clientY, initialZoom: zoom };
            } else if (activeTool === 'crosshair') {
                setIsDraggingCrosshair(true);
                updateCrosshairFromMouse(e);
            } else if (e.ctrlKey) {
                // Original behavior: left click + ctrl for pan
                setIsDragging(true);
                dragStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
            }
        } else if (e.button === 2) {
            // Original behavior: right click for zoom
            setIsZooming(true);
            zoomStartRef.current = { x: e.clientX, y: e.clientY, initialZoom: zoom };
        }
    }, [pan, zoom, activeTool, updateCrosshairFromMouse]);

    const handleMouseMove = useCallback((e: React.MouseEvent) => {
        if (isDraggingCrosshair) {
            updateCrosshairFromMouse(e);
        } else if (isDragging) {
            setPan({
                x: e.clientX - dragStartRef.current.x,
                y: e.clientY - dragStartRef.current.y,
            });
        } else if (isZooming) {
            const deltaX = e.clientX - zoomStartRef.current.x;
            const deltaY = e.clientY - zoomStartRef.current.y;

            const delta = deltaX - deltaY;

            // Apply zoom factor based on delta
            const zoomFactor = Math.pow(1.01, delta);
            const newZoom = Math.max(0.1, Math.min(20, zoomStartRef.current.initialZoom * zoomFactor));
            setZoom(newZoom);
        }
    }, [isDragging, isZooming, isDraggingCrosshair, updateCrosshairFromMouse]);

    const handleMouseUp = useCallback(() => {
        setIsDragging(false);
        setIsZooming(false);
        setIsDraggingCrosshair(false);
    }, []);

    const resetView = useCallback(() => {
        setZoom(1);
        setPan({ x: 0, y: 0 });
    }, []);

    // Listen to global reset view event from header toolbar
    useEffect(() => {
        const handleReset = () => resetView();
        window.addEventListener('reset-view', handleReset);
        return () => window.removeEventListener('reset-view', handleReset);
    }, [resetView]);

    return {
        zoom,
        setZoom,
        pan,
        setPan,
        isDragging,
        isZooming,
        crosshairPos,
        handleMouseDown,
        handleMouseMove,
        handleMouseUp,
        resetView
    };
}
