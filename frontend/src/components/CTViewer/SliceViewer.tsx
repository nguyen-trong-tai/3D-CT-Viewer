import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';
import { useVolumeViewer } from '../../hooks/useVolumeViewer';
import { useViewerInteractions } from '../../hooks/useViewerInteractions';
import { useViewerStore } from '../../stores/viewerStore';
import { type MPRView, type WindowPresetKey } from '../../types';
import { WindowPresetControl } from './WindowPresetControl';

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
    showNoduleNavigator?: boolean;
    showUiOverlays?: boolean;
    useCustomWindow?: boolean;
    customWindowLevel?: number;
    customWindowWidth?: number;
}

/**
 * CT Slice Viewer Component (Single Axial View)
 * Supports window presets, custom window values, and segmentation overlay.
 */
export const SliceViewer: React.FC<SliceViewerProps> = ({
    caseId,
    totalSlices,
    currentIndex,
    onIndexChange,
    showControls = true,
    viewLabel = 'Axial',
    viewType = 'AXIAL',
    windowPreset = 'LUNG',
    showSegmentation = false,
    segmentationOpacity = 0.5,
    showNoduleNavigator = false,
    showUiOverlays = true,
    useCustomWindow = false,
    customWindowLevel = 40,
    customWindowWidth = 400,
}) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const maskCanvasRef = useRef<HTMLCanvasElement>(null);
    const firstFrameMeasuredRef = useRef(false);

    const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

    const segmentationLabels = useViewerStore((state) => state.segmentationLabels);
    const segmentationVisibility = useViewerStore((state) => state.segmentationVisibility);
    const noduleEntities = useViewerStore((state) => state.noduleEntities);
    const selectedNoduleId = useViewerStore((state) => state.selectedNoduleId);
    const setSelectedNoduleId = useViewerStore((state) => state.setSelectedNoduleId);

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

    const activeTool = useViewerStore((state) => state.activeTool);
    const viewMode = useViewerStore((state) => state.viewMode);
    const currentSlice = getSliceIndex(viewType);
    const dims = getViewDimensions(viewType);
    const isMprCrosshairView = viewMode === 'MPR' || viewMode === 'MPR_3D';
    const isCrosshairToolActive = isMprCrosshairView && activeTool === 'crosshair';

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
        resetView,
    } = useViewerInteractions({
        canvasRef,
        dims,
        volume,
        viewType,
        crosshair,
        setCrosshair,
        activeTool,
    });

    const viewerCursor = isDragging
        ? 'grabbing'
        : isZooming
            ? 'ns-resize'
            : activeTool === 'pan'
                ? 'grab'
                : isCrosshairToolActive
                    ? 'crosshair'
                    : activeTool === 'zoom'
                        ? 'zoom-in'
                        : 'default';

    const windowPresetRef = useRef(windowPreset);
    useEffect(() => {
        if (windowPresetRef.current !== windowPreset) {
            windowPresetRef.current = windowPreset;
            setHookWindowPreset(windowPreset);
        }
    }, [setHookWindowPreset, windowPreset]);

    useEffect(() => {
        firstFrameMeasuredRef.current = false;
        performance.mark(`case-first-2d-frame-start:${caseId}:${viewType}`);
    }, [caseId, viewType]);

    const imageData = isLoaded
        ? (
            useCustomWindow
                ? renderSliceWithCustomWindow(viewType, currentSlice, customWindowLevel, customWindowWidth)
                : renderSliceToImageData(viewType, currentSlice, windowPreset)
        )
        : null;

    const maskImageData = isLoaded && showSegmentation && hasMask
        ? renderMaskSliceToImageData(viewType, currentSlice)
        : null;

    useEffect(() => {
        if (currentIndex !== undefined && currentIndex !== currentSlice) {
            updateCrosshair(viewType, currentIndex);
        }
    }, [currentIndex, currentSlice, updateCrosshair, viewType]);

    useEffect(() => {
        if (loading || !imageData || !canvasRef.current) {
            return;
        }

        const canvas = canvasRef.current;
        if (canvas.width !== imageData.width || canvas.height !== imageData.height) {
            canvas.width = imageData.width;
            canvas.height = imageData.height;
        }

        const ctx = canvas.getContext('2d', { alpha: false });
        if (!ctx) {
            return;
        }

        ctx.putImageData(imageData, 0, 0);

        if (!firstFrameMeasuredRef.current) {
            firstFrameMeasuredRef.current = true;
            performance.mark(`case-first-2d-frame-complete:${caseId}:${viewType}`);
            performance.measure(
                `case-first-2d-frame:${caseId}:${viewType}`,
                `case-first-2d-frame-start:${caseId}:${viewType}`,
                `case-first-2d-frame-complete:${caseId}:${viewType}`,
            );
        }
    }, [caseId, imageData, loading, viewType]);

    useEffect(() => {
        if (loading || !maskCanvasRef.current) {
            return;
        }

        const maskCanvas = maskCanvasRef.current;
        const ctx = maskCanvas.getContext('2d', { alpha: true });
        if (!ctx) {
            return;
        }

        if (maskImageData && showSegmentation) {
            if (maskCanvas.width !== maskImageData.width || maskCanvas.height !== maskImageData.height) {
                maskCanvas.width = maskImageData.width;
                maskCanvas.height = maskImageData.height;
            }

            ctx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
            ctx.globalAlpha = segmentationOpacity;
            ctx.putImageData(maskImageData, 0, 0);
            return;
        }

        ctx.clearRect(0, 0, maskCanvas.width, maskCanvas.height);
    }, [loading, maskImageData, segmentationLabels, segmentationOpacity, segmentationVisibility, showSegmentation]);

    const sliceCount = dims?.maxSlice || totalSlices;
    const spacingAspect = dims ? (dims.spacing.y / dims.spacing.x) : 1;
    const sortedNoduleEntities = useMemo(
        () => [...noduleEntities].sort((left, right) => (
            left.slice_range[0] - right.slice_range[0] ||
            right.estimated_diameter_mm - left.estimated_diameter_mm ||
            left.display_name.localeCompare(right.display_name)
        )),
        [noduleEntities],
    );

    const fittedCanvasSize = useMemo(() => {
        if (!dims || containerSize.width <= 0 || containerSize.height <= 0) {
            return null;
        }

        const sourceWidth = dims.width;
        const sourceHeight = dims.height * spacingAspect;
        const horizontalPadding = 24;
        const verticalPadding = showControls ? 40 : 24;
        const availableWidth = Math.max(containerSize.width - horizontalPadding * 2, 1);
        const availableHeight = Math.max(containerSize.height - verticalPadding * 2, 1);
        const fitScale = Math.min(availableWidth / sourceWidth, availableHeight / sourceHeight);

        return {
            width: Math.max(1, Math.floor(sourceWidth * fitScale)),
            height: Math.max(1, Math.floor(sourceHeight * fitScale)),
        };
    }, [containerSize.height, containerSize.width, dims, showControls, spacingAspect]);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) {
            return;
        }

        const updateSize = () => {
            const rect = container.getBoundingClientRect();
            setContainerSize({
                width: rect.width,
                height: rect.height,
            });
        };

        updateSize();

        const observer = new ResizeObserver(updateSize);
        observer.observe(container);

        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) {
            return;
        }

        const onWheel = (event: WheelEvent) => {
            event.preventDefault();

            const delta = Math.sign(event.deltaY);
            const nextSlice = Math.max(0, Math.min(sliceCount - 1, currentSlice - delta));

            if (nextSlice !== currentSlice) {
                updateCrosshair(viewType, nextSlice);
                onIndexChange?.(nextSlice);
            }
        };

        container.addEventListener('wheel', onWheel, { passive: false });
        return () => container.removeEventListener('wheel', onWheel);
    }, [currentSlice, onIndexChange, sliceCount, updateCrosshair, viewType]);

    const handleNoduleJump = (noduleId: string, targetSlice: number) => {
        const nextSlice = Math.max(0, Math.min(sliceCount - 1, targetSlice));
        setSelectedNoduleId(noduleId);
        updateCrosshair(viewType, nextSlice);
        onIndexChange?.(nextSlice);
    };

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
                <style>{'@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }'}</style>
            </div>
        );
    }

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

    const showAxialNavigator =
        showUiOverlays &&
        showNoduleNavigator &&
        viewType === 'AXIAL' &&
        sortedNoduleEntities.length > 0;
    const sliceProgressPercent = sliceCount > 1 ? (currentSlice / (sliceCount - 1)) * 100 : 0;

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
            onContextMenu={(event) => event.preventDefault()}
        >
            {showUiOverlays && (
                <>
                    <div
                        style={{
                            position: 'absolute',
                            top: 8,
                            left: 16,
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
                </>
            )}

            <div
                style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: viewerCursor,
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
                        transformOrigin: 'center center',
                        width: fittedCanvasSize ? `${fittedCanvasSize.width}px` : undefined,
                        height: fittedCanvasSize ? `${fittedCanvasSize.height}px` : undefined,
                        maxWidth: '100%',
                        maxHeight: '100%',
                    }}
                >
                    <canvas
                        ref={canvasRef}
                        style={{
                            display: 'block',
                            imageRendering: 'pixelated',
                            width: '100%',
                            height: '100%',
                        }}
                    />

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
                            width: '100%',
                            height: '100%',
                        }}
                    />

                    {isMprCrosshairView && crosshairPos && (
                        <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
                            <div
                                style={{
                                    position: 'absolute',
                                    top: `${crosshairPos.cy}%`,
                                    left: 0,
                                    right: 0,
                                    height: `${1 / zoom}px`,
                                    background: 'rgba(244, 63, 94, 0.7)',
                                    transform: 'translateY(-50%)',
                                }}
                            />
                            <div
                                style={{
                                    position: 'absolute',
                                    left: `${crosshairPos.cx}%`,
                                    top: 0,
                                    bottom: 0,
                                    width: `${1 / zoom}px`,
                                    background: 'rgba(244, 63, 94, 0.7)',
                                    transform: 'translateX(-50%)',
                                }}
                            />
                        </div>
                    )}
                </div>

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

            {showAxialNavigator && (
                <div
                    style={{
                        position: 'absolute',
                        right: 16,
                        bottom: showControls ? 56 : 16,
                        width: 'min(320px, calc(100% - 32px))',
                        maxHeight: 'min(320px, calc(100% - 240px))',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 8,
                        padding: '10px',
                        borderRadius: 12,
                        background: 'rgba(9, 12, 18, 0.84)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        backdropFilter: 'blur(12px)',
                        boxShadow: '0 18px 40px rgba(0, 0, 0, 0.32)',
                        zIndex: 12,
                    }}
                >
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: 8,
                        }}
                    >
                        <div>
                            <div
                                style={{
                                    fontSize: '0.72rem',
                                    fontWeight: 700,
                                    letterSpacing: '0.05em',
                                    textTransform: 'uppercase',
                                    color: '#fdba74',
                                }}
                            >
                                Nodule Slice List
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                Select a nodule to jump to its first slice
                            </div>
                        </div>
                        <span
                            style={{
                                padding: '2px 7px',
                                borderRadius: '999px',
                                background: 'rgba(249, 115, 22, 0.14)',
                                color: '#fdba74',
                                fontSize: '0.68rem',
                                fontWeight: 700,
                            }}
                        >
                            {sortedNoduleEntities.length}
                        </span>
                    </div>

                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 6,
                            overflowY: 'auto',
                            paddingRight: 2,
                        }}
                    >
                        {sortedNoduleEntities.map((nodule) => {
                            const isSelected = selectedNoduleId === nodule.id;
                            const isVisibleOnCurrentSlice =
                                currentSlice >= nodule.slice_range[0] &&
                                currentSlice <= nodule.slice_range[1];
                            const buttonBorderColor = isSelected
                                ? 'rgba(251, 146, 60, 0.85)'
                                : isVisibleOnCurrentSlice
                                    ? 'rgba(59, 130, 246, 0.42)'
                                    : 'rgba(255, 255, 255, 0.06)';
                            const buttonBackground = isSelected
                                ? 'linear-gradient(135deg, rgba(249, 115, 22, 0.34) 0%, rgba(124, 45, 18, 0.92) 100%)'
                                : isVisibleOnCurrentSlice
                                    ? 'rgba(59, 130, 246, 0.1)'
                                    : 'rgba(255, 255, 255, 0.03)';
                            const buttonBoxShadow = isSelected
                                ? '0 0 0 1px rgba(255, 237, 213, 0.14), 0 12px 24px rgba(249, 115, 22, 0.22)'
                                : isVisibleOnCurrentSlice
                                    ? '0 8px 18px rgba(37, 99, 235, 0.12)'
                                    : 'none';

                            return (
                                <button
                                    key={`slice-nodule:${nodule.id}`}
                                    type="button"
                                    onClick={() => handleNoduleJump(nodule.id, nodule.slice_range[0])}
                                    title={`Jump to slice ${nodule.slice_range[0] + 1}`}
                                    style={{
                                        width: '100%',
                                        display: 'grid',
                                        gridTemplateColumns: 'minmax(0, 1fr) auto auto',
                                        alignItems: 'center',
                                        columnGap: 8,
                                        padding: '8px 10px',
                                        borderRadius: 10,
                                        border: '1px solid',
                                        borderColor: buttonBorderColor,
                                        background: buttonBackground,
                                        boxShadow: buttonBoxShadow,
                                        color: 'var(--text-primary)',
                                        cursor: 'pointer',
                                        textAlign: 'left',
                                        opacity: isSelected ? 1 : 0.84,
                                        transition: 'background 140ms ease, border-color 140ms ease, box-shadow 140ms ease, opacity 140ms ease',
                                    }}
                                >
                                    <span
                                        style={{
                                            minWidth: 0,
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                            fontSize: '0.78rem',
                                            fontWeight: isSelected ? 700 : 600,
                                            color: isSelected ? '#fff7ed' : 'var(--text-primary)',
                                        }}
                                    >
                                        {nodule.display_name}
                                    </span>
                                    <span
                                        style={{
                                            whiteSpace: 'nowrap',
                                            fontSize: '0.7rem',
                                            color: isSelected ? '#fed7aa' : 'var(--text-secondary)',
                                        }}
                                    >
                                        Diameter {nodule.estimated_diameter_mm.toFixed(1)} mm
                                    </span>
                                    <span
                                        style={{
                                            whiteSpace: 'nowrap',
                                            fontSize: '0.7rem',
                                            fontWeight: 700,
                                            color: isSelected ? '#fdba74' : 'var(--text-muted)',
                                        }}
                                    >
                                        Z {nodule.slice_range[0] + 1} - {nodule.slice_range[1] + 1}
                                    </span>
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

            {showUiOverlays && <WindowPresetControl />}

            {showUiOverlays && showControls && (
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
                    <div
                        style={{
                            flex: 1,
                            position: 'relative',
                            paddingTop: 22,
                        }}
                    >
                        <div
                            style={{
                                position: 'absolute',
                                left: `${sliceProgressPercent}%`,
                                top: 0,
                                transform: 'translateX(-50%)',
                                pointerEvents: 'none',
                            }}
                        >
                            <div
                                style={{
                                    position: 'relative',
                                    minWidth: 52,
                                    padding: '4px 8px',
                                    borderRadius: 999,
                                    background: 'rgba(15, 23, 42, 0.92)',
                                    border: '1px solid rgba(96, 165, 250, 0.35)',
                                    color: '#dbeafe',
                                    fontSize: '0.68rem',
                                    fontWeight: 700,
                                    lineHeight: 1,
                                    textAlign: 'center',
                                    boxShadow: '0 10px 22px rgba(0, 0, 0, 0.32)',
                                    backdropFilter: 'blur(8px)',
                                }}
                            >
                                {currentSlice + 1}/{sliceCount}
                                <div
                                    style={{
                                        position: 'absolute',
                                        left: '50%',
                                        top: '100%',
                                        width: 2,
                                        height: 10,
                                        transform: 'translateX(-50%)',
                                        background: 'rgba(147, 197, 253, 0.6)',
                                        borderRadius: 999,
                                    }}
                                />
                            </div>
                        </div>

                        <input
                            type="range"
                            min={0}
                            max={sliceCount - 1}
                            value={currentSlice}
                            onChange={(event) => {
                                const nextSlice = Number.parseInt(event.target.value, 10);
                                updateCrosshair(viewType, nextSlice);
                                onIndexChange?.(nextSlice);
                            }}
                            style={{ width: '100%', height: 4 }}
                        />
                    </div>
                    <button
                        onClick={() => setZoom((currentZoom) => Math.min(currentZoom * 1.25, 20))}
                        style={btnStyle}
                        title="Zoom In"
                    >
                        <ZoomIn size={14} />
                    </button>
                    <button
                        onClick={() => setZoom((currentZoom) => Math.max(currentZoom / 1.25, 0.1))}
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
