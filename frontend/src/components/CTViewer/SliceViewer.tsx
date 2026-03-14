import React, { useRef, useEffect } from 'react';
import { useVolumeViewer } from '../../hooks/useVolumeViewer';
import { RotateCcw, ZoomIn, ZoomOut, Loader2 } from 'lucide-react';
import { type WindowPresetKey, type MPRView } from '../../types';
import { useViewerStore } from '../../stores/viewerStore';
import { WindowPresetControl } from './WindowPresetControl';
import { useViewerInteractions } from '../../hooks/useViewerInteractions';

interface SliceViewerProps {
    caseId: string;
    totalSlices: number;
    currentIndex?: number;
    onIndexChange?: (index: number) => void;
    showControls?: boolean;
    viewLabel?: string;
    viewType?: MPRView;
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
    currentIndex,
    onIndexChange,
    showControls = true,
    viewLabel = 'Axial',
    viewType = 'AXIAL',
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

    const {
        isLoaded,
        loading,
        loadProgress,
        error,
        volume,
        crosshair,
        setCrosshair,
        renderSliceToImageData,
        renderSliceWithCustomWindow,
        renderMaskSliceToImageData,
        getViewDimensions,
        setWindowPreset: setHookWindowPreset,
        getSliceIndex,
        updateCrosshair,
        hasMask,
    } = useVolumeViewer(caseId);

    const activeTool = useViewerStore(state => state.activeTool);
    const viewMode = useViewerStore(state => state.viewMode);
    const currentSlice = getSliceIndex(viewType);
    const dims = getViewDimensions(viewType);

    const {
        zoom,
        setZoom,
        pan,
        isDragging,
        isZooming,
        crosshairPos,
        handleMouseDown,
        handleMouseMove,
        handleMouseUp,
        resetView
    } = useViewerInteractions({
        canvasRef,
        dims,
        volume,
        viewType,
        crosshair,
        setCrosshair,
        activeTool
    });

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
            ? renderSliceWithCustomWindow(viewType, currentSlice, customWindowLevel, customWindowWidth)
            : renderSliceToImageData(viewType, currentSlice, windowPreset))
        : null;
    const maskImageData = isLoaded && showSegmentation && hasMask
        ? renderMaskSliceToImageData(viewType, currentSlice)
        : null;

    // Sync external currentIndex to internal crosshair
    useEffect(() => {
        if (currentIndex !== undefined && currentIndex !== currentSlice) {
            updateCrosshair(viewType, currentIndex);
        }
    }, [currentIndex, currentSlice, updateCrosshair, viewType]);


    // Render CT slice
    useEffect(() => {
        if (loading || !imageData || !canvasRef.current) return;

        const canvas = canvasRef.current;
        if (canvas.width !== imageData.width || canvas.height !== imageData.height) {
            canvas.width = imageData.width;
            canvas.height = imageData.height;
        }

        const ctx = canvas.getContext('2d', { alpha: false });
        if (ctx) {
            ctx.putImageData(imageData, 0, 0);
        }
    }, [imageData, loading]);

    // Render mask overlay
    useEffect(() => {
        if (loading || !maskCanvasRef.current) return;

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
    }, [maskImageData, showSegmentation, segmentationOpacity, loading]);

    const sliceCount = dims?.maxSlice || totalSlices;
    const spacingAspect = dims ? (dims.spacing.y / dims.spacing.x) : 1;

    // Use native event listener for wheel to avoid passive issues
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const onWheel = (e: WheelEvent) => {
            e.preventDefault();
            // Calculate new index and sync it correctly
            const delta = Math.sign(e.deltaY);
            const newIndex = Math.max(0, Math.min(sliceCount - 1, currentSlice - delta));

            if (newIndex !== currentSlice) {
                updateCrosshair(viewType, newIndex);
                onIndexChange?.(newIndex);
            }
        };

        container.addEventListener('wheel', onWheel, { passive: false });
        // Make sure to add dependencies otherwise the handlers have stale state
        return () => container.removeEventListener('wheel', onWheel);
    }, [currentSlice, sliceCount, onIndexChange, updateCrosshair, viewType]);

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
                {currentSlice + 1}/{sliceCount}
            </div>

            {/* Canvas Container */}
            <div
                style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: isDragging ? 'grabbing' : isZooming ? 'ns-resize' : 'crosshair',
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
                            width: imageData ? imageData.width : undefined,
                            height: imageData ? imageData.height * spacingAspect : undefined,
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
                            width: imageData ? imageData.width : undefined,
                            height: imageData ? imageData.height * spacingAspect : undefined,
                        }}
                    />

                    {/* Crosshair Overlay */}
                    {(viewMode === 'MPR' || viewMode === 'MPR_3D' || activeTool === 'crosshair') && crosshairPos && (
                        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, pointerEvents: 'none' }}>
                            <div style={{ position: 'absolute', top: `${crosshairPos.cy}%`, left: 0, right: 0, height: `${1/zoom}px`, background: 'rgba(244, 63, 94, 0.7)', transform: 'translateY(-50%)' }} />
                            <div style={{ position: 'absolute', left: `${crosshairPos.cx}%`, top: 0, bottom: 0, width: `${1/zoom}px`, background: 'rgba(244, 63, 94, 0.7)', transform: 'translateX(-50%)' }} />
                        </div>
                    )}
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

            {/* Window Preset Control Overlay */}
            <WindowPresetControl />

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
                        value={currentSlice}
                        onChange={(e) => {
                            const newIndex = parseInt(e.target.value);
                            updateCrosshair(viewType, newIndex);
                            onIndexChange?.(newIndex);
                        }}
                        style={{ flex: 1, height: 4 }}
                    />
                    <button
                        onClick={() => setZoom(z => Math.min(z * 1.25, 20))}
                        style={btnStyle}
                        title="Zoom In"
                    >
                        <ZoomIn size={14} />
                    </button>
                    <button
                        onClick={() => setZoom(z => Math.max(z / 1.25, 0.1))}
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
