import React, { useRef, useCallback, useEffect, useState } from 'react';
import { useVolumeViewer } from '../../hooks/useVolumeViewer';
import { RotateCcw, ZoomIn, ZoomOut, Loader2 } from 'lucide-react';
import type { WindowPresetKey } from '../../types';

interface SliceViewerProps {
    caseId: string;
    totalSlices: number;
    currentIndex?: number;
    onIndexChange?: (index: number) => void;
    showControls?: boolean;
    viewLabel?: string;
    windowPreset?: WindowPresetKey;
    showSegmentation?: boolean;
    segmentationOpacity?: number;
    // Custom window for manual HU adjustment
    useCustomWindow?: boolean;
    customWindowLevel?: number;
    customWindowWidth?: number;
}

/**
 * CT Slice Viewer Component (Single Axial View)
 * Supports window presets, custom window values, and segmentation overlay
 */
export const SliceViewer: React.FC<SliceViewerProps> = ({
    caseId,
    totalSlices,
    showControls = true,
    viewLabel = 'Axial',
    windowPreset = 'SOFT_TISSUE',
    showSegmentation = false,
    segmentationOpacity = 0.5,
    useCustomWindow = false,
    customWindowLevel = 40,
    customWindowWidth = 400,
}) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const maskCanvasRef = useRef<HTMLCanvasElement>(null);
    const [zoom, setZoom] = useState(1);
    const [pan, setPan] = useState({ x: 0, y: 0 });
    const [isDragging, setIsDragging] = useState(false);
    const dragStartRef = useRef({ x: 0, y: 0 });

    const {
        isLoaded,
        loading,
        loadProgress,
        error,
        crosshair,
        setCrosshair,
        handleScroll,
        renderSliceToImageData,
        renderSliceWithCustomWindow,
        renderMaskSliceToImageData,
        getViewDimensions,
        setWindowPreset: setHookWindowPreset,
        hasMask,
    } = useVolumeViewer(caseId);

    // Sync window preset - use ref to avoid re-render loop
    const windowPresetRef = useRef(windowPreset);
    useEffect(() => {
        if (windowPresetRef.current !== windowPreset) {
            windowPresetRef.current = windowPreset;
            setHookWindowPreset(windowPreset);
        }
    }, [windowPreset, setHookWindowPreset]);

    // Render slice to canvas - use custom window if enabled
    const imageData = isLoaded
        ? (useCustomWindow
            ? renderSliceWithCustomWindow('AXIAL', crosshair.z, customWindowLevel, customWindowWidth)
            : renderSliceToImageData('AXIAL', crosshair.z, windowPreset))
        : null;
    const maskImageData = isLoaded && showSegmentation && hasMask
        ? renderMaskSliceToImageData('AXIAL', crosshair.z)
        : null;

    // Render CT slice
    useEffect(() => {
        if (!imageData || !canvasRef.current) return;

        const canvas = canvasRef.current;
        if (canvas.width !== imageData.width || canvas.height !== imageData.height) {
            canvas.width = imageData.width;
            canvas.height = imageData.height;
        }

        const ctx = canvas.getContext('2d', { alpha: false });
        if (ctx) {
            ctx.putImageData(imageData, 0, 0);
        }
    }, [imageData]);

    // Render mask overlay
    useEffect(() => {
        if (!maskCanvasRef.current) return;

        const maskCanvas = maskCanvasRef.current;
        const ctx = maskCanvas.getContext('2d', { alpha: true });
        if (!ctx) return;

        if (maskImageData && showSegmentation) {
            // Resize mask canvas to match
            if (maskCanvas.width !== maskImageData.width || maskCanvas.height !== maskImageData.height) {
                maskCanvas.width = maskImageData.width;
                maskCanvas.height = maskImageData.height;
            }

            // Clear and draw mask
            ctx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
            ctx.globalAlpha = segmentationOpacity;
            ctx.putImageData(maskImageData, 0, 0);
        } else {
            // Clear mask when not showing
            ctx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
        }
    }, [maskImageData, showSegmentation, segmentationOpacity]);

    const dims = getViewDimensions('AXIAL');
    const sliceCount = dims?.maxSlice || totalSlices;

    // Use native event listener for wheel to avoid passive issues
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const onWheel = (e: WheelEvent) => {
            e.preventDefault();
            handleScroll('AXIAL', Math.sign(e.deltaY));
        };

        container.addEventListener('wheel', onWheel, { passive: false });
        return () => container.removeEventListener('wheel', onWheel);
    }, [handleScroll]);

    // Handle pan
    const handleMouseDown = useCallback((e: React.MouseEvent) => {
        if (e.button === 0 && e.ctrlKey) {
            setIsDragging(true);
            dragStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
        }
    }, [pan]);

    const handleMouseMove = useCallback((e: React.MouseEvent) => {
        if (isDragging) {
            setPan({
                x: e.clientX - dragStartRef.current.x,
                y: e.clientY - dragStartRef.current.y,
            });
        }
    }, [isDragging]);

    const handleMouseUp = useCallback(() => {
        setIsDragging(false);
    }, []);

    const resetView = useCallback(() => {
        setZoom(1);
        setPan({ x: 0, y: 0 });
    }, []);

    // Loading state
    if (loading) {
        return (
            <div
                style={{
                    width: '100%',
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: '#000',
                    color: '#888',
                    gap: 12,
                }}
            >
                <Loader2 size={40} color="#6366f1" style={{ animation: 'spin 1s linear infinite' }} />
                <div>Loading volume... {loadProgress}%</div>
                <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
            </div>
        );
    }

    // Error state
    if (error) {
        return (
            <div
                style={{
                    width: '100%',
                    height: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    background: '#000',
                    color: '#ef4444',
                }}
            >
                Error: {error}
            </div>
        );
    }

    return (
        <div
            ref={containerRef}
            style={{
                width: '100%',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                background: '#000',
                position: 'relative',
                overflow: 'hidden',
                userSelect: 'none',
            }}
            onContextMenu={(e) => e.preventDefault()}
        >
            {/* View Label */}
            <div
                style={{
                    position: 'absolute',
                    top: 8,
                    left: 8,
                    zIndex: 10,
                    background: 'rgba(0,0,0,0.7)',
                    backdropFilter: 'blur(4px)',
                    padding: '4px 12px',
                    borderRadius: 4,
                    border: '1px solid rgba(99, 102, 241, 0.4)',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: '#6366f1',
                }}
            >
                {viewLabel}
            </div>

            {/* Window Preset Badge */}
            <div
                style={{
                    position: 'absolute',
                    top: 8,
                    left: 80,
                    zIndex: 10,
                    background: useCustomWindow ? 'rgba(59, 130, 246, 0.2)' : 'rgba(0,0,0,0.7)',
                    backdropFilter: 'blur(4px)',
                    padding: '4px 8px',
                    borderRadius: 4,
                    fontSize: '0.65rem',
                    fontWeight: 500,
                    color: useCustomWindow ? '#3b82f6' : '#94a3b8',
                    border: useCustomWindow ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid rgba(255,255,255,0.1)',
                }}
            >
                {useCustomWindow
                    ? `WL: ${customWindowLevel} / WW: ${customWindowWidth}`
                    : windowPreset.replace('_', ' ')}
            </div>

            {/* Segmentation Indicator */}
            {showSegmentation && hasMask && (
                <div
                    style={{
                        position: 'absolute',
                        top: 36,
                        left: 8,
                        zIndex: 10,
                        background: 'rgba(239, 68, 68, 0.2)',
                        backdropFilter: 'blur(4px)',
                        padding: '3px 8px',
                        borderRadius: 4,
                        fontSize: '0.65rem',
                        fontWeight: 500,
                        color: '#ef4444',
                        border: '1px solid rgba(239, 68, 68, 0.4)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                    }}
                >
                    <span
                        style={{
                            width: 6,
                            height: 6,
                            borderRadius: '50%',
                            background: '#ef4444',
                        }}
                    />
                    Segmentation {Math.round(segmentationOpacity * 100)}%
                </div>
            )}

            {/* Slice Counter */}
            <div
                style={{
                    position: 'absolute',
                    top: 8,
                    right: 8,
                    zIndex: 10,
                    background: 'rgba(0,0,0,0.7)',
                    padding: '4px 8px',
                    borderRadius: 4,
                    fontSize: '0.7rem',
                    fontFamily: 'monospace',
                    color: '#aaa',
                }}
            >
                {crosshair.z + 1}/{sliceCount}
            </div>

            {/* Canvas Container */}
            <div
                style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: isDragging ? 'grabbing' : 'crosshair',
                }}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
            >
                <div
                    style={{
                        position: 'relative',
                        transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                        transition: isDragging ? 'none' : 'transform 0.1s ease-out',
                    }}
                >
                    {/* CT Canvas (base layer) */}
                    <canvas
                        ref={canvasRef}
                        style={{
                            display: 'block',
                            imageRendering: 'pixelated',
                        }}
                    />

                    {/* Mask Overlay Canvas */}
                    <canvas
                        ref={maskCanvasRef}
                        style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            display: 'block',
                            imageRendering: 'pixelated',
                            pointerEvents: 'none',
                            mixBlendMode: 'normal',
                        }}
                    />
                </div>

                {/* Loading placeholder */}
                {!isLoaded && (
                    <div
                        style={{
                            position: 'absolute',
                            color: '#666',
                            fontSize: '0.9rem',
                        }}
                    >
                        Waiting for data...
                    </div>
                )}
            </div>

            {/* Bottom Controls */}
            {showControls && (
                <div
                    style={{
                        position: 'absolute',
                        bottom: 0,
                        left: 0,
                        right: 0,
                        background: 'linear-gradient(to top, rgba(0,0,0,0.8) 0%, transparent 100%)',
                        padding: '24px 12px 8px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                    }}
                >
                    <input
                        type="range"
                        min={0}
                        max={sliceCount - 1}
                        value={crosshair.z}
                        onChange={(e) => setCrosshair(prev => ({ ...prev, z: parseInt(e.target.value) }))}
                        style={{ flex: 1, height: 4 }}
                    />
                    <button
                        onClick={() => setZoom(z => Math.min(z * 1.25, 5))}
                        style={btnStyle}
                        title="Zoom In"
                    >
                        <ZoomIn size={14} />
                    </button>
                    <button
                        onClick={() => setZoom(z => Math.max(z / 1.25, 0.5))}
                        style={btnStyle}
                        title="Zoom Out"
                    >
                        <ZoomOut size={14} />
                    </button>
                    <button onClick={resetView} style={btnStyle} title="Reset View">
                        <RotateCcw size={14} />
                    </button>
                </div>
            )}
        </div>
    );
};

const btnStyle: React.CSSProperties = {
    width: 28,
    height: 28,
    padding: 0,
    background: 'rgba(255,255,255,0.1)',
    border: '1px solid rgba(255,255,255,0.2)',
    borderRadius: 4,
    color: '#aaa',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
};

export default SliceViewer;
