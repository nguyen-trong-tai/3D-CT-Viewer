import React, { useCallback, useMemo, useRef, useEffect } from 'react';
import { useVolumeViewer } from '../../hooks/useVolumeViewer';
import type { WindowPresetKey, MPRView } from '../../types';
import { Loader2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';

interface MPRLayoutProps {
    caseId: string;
    windowPreset: WindowPresetKey;
    showSegmentation: boolean;
    segmentationOpacity: number;
    onWindowPresetChange?: (preset: WindowPresetKey) => void;
}

const VIEW_LABELS: Record<MPRView, string> = {
    AXIAL: 'Axial',
    SAGITTAL: 'Sagittal',
    CORONAL: 'Coronal',
};

const VIEW_COLORS: Record<MPRView, string> = {
    AXIAL: '#6366f1',      // Primary blue
    SAGITTAL: '#22c55e',   // Green
    CORONAL: '#f59e0b',    // Orange
};

/**
 * Single MPR View Panel with Direct Canvas Rendering
 * NO base64 encoding - renders ImageData directly to canvas
 */
const MPRViewPanel: React.FC<{
    view: MPRView;
    imageData: ImageData | null;
    maskData: ImageData | null;
    showMask: boolean;
    maskOpacity: number;
    currentSlice: number;
    totalSlices: number;
    crosshairPosition?: { x: number; y: number };
    onSliceChange: (index: number) => void;
    onScroll: (delta: number) => void;
    onCrosshairClick?: (x: number, y: number) => void;
}> = ({
    view,
    imageData,
    maskData,
    showMask,
    maskOpacity,
    currentSlice,
    totalSlices,
    crosshairPosition,
    onSliceChange,
    onScroll,
    onCrosshairClick,
}) => {
        const canvasRef = useRef<HTMLCanvasElement>(null);
        const maskCanvasRef = useRef<HTMLCanvasElement>(null);
        const containerRef = useRef<HTMLDivElement>(null);
        const [zoom, setZoom] = React.useState(1);
        const [pan, setPan] = React.useState({ x: 0, y: 0 });
        const [isDragging, setIsDragging] = React.useState(false);
        const dragStartRef = useRef({ x: 0, y: 0 });

        // Render ImageData directly to canvas - ultra fast!
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

        // Render mask to canvas
        useEffect(() => {
            if (!maskData || !maskCanvasRef.current || !showMask) return;

            const canvas = maskCanvasRef.current;
            if (canvas.width !== maskData.width || canvas.height !== maskData.height) {
                canvas.width = maskData.width;
                canvas.height = maskData.height;
            }

            const ctx = canvas.getContext('2d');
            if (ctx) {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.putImageData(maskData, 0, 0);
            }
        }, [maskData, showMask]);

        const handleWheel = useCallback((e: React.WheelEvent) => {
            e.preventDefault();
            onScroll(Math.sign(e.deltaY));
        }, [onScroll]);

        const handleMouseDown = useCallback((e: React.MouseEvent) => {
            if (e.button === 2 || (e.button === 0 && e.ctrlKey)) {
                e.preventDefault();
                setIsDragging(true);
                dragStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
            } else if (e.button === 0 && onCrosshairClick && imageData) {
                const rect = e.currentTarget.getBoundingClientRect();
                const centerX = rect.width / 2;
                const centerY = rect.height / 2;
                const imgW = imageData.width * zoom;
                const imgH = imageData.height * zoom;

                const clickX = (e.clientX - rect.left - centerX - pan.x + imgW / 2) / imgW;
                const clickY = (e.clientY - rect.top - centerY - pan.y + imgH / 2) / imgH;

                if (clickX >= 0 && clickX <= 1 && clickY >= 0 && clickY <= 1) {
                    onCrosshairClick(clickX, clickY);
                }
            }
        }, [pan, zoom, imageData, onCrosshairClick]);

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

        const resetView = () => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
        };

        return (
            <div
                ref={containerRef}
                style={{
                    position: 'relative',
                    width: '100%',
                    height: '100%',
                    background: '#000',
                    overflow: 'hidden',
                    userSelect: 'none',
                }}
                onContextMenu={(e) => e.preventDefault()}
            >
                {/* View Label */}
                <div
                    style={{
                        position: 'absolute',
                        top: 6,
                        left: 6,
                        zIndex: 10,
                        background: 'rgba(0,0,0,0.7)',
                        backdropFilter: 'blur(4px)',
                        padding: '2px 8px',
                        borderRadius: 4,
                        border: `1px solid ${VIEW_COLORS[view]}50`,
                        fontSize: '0.7rem',
                        fontWeight: 600,
                        color: VIEW_COLORS[view],
                    }}
                >
                    {VIEW_LABELS[view]}
                </div>

                {/* Slice Counter */}
                <div
                    style={{
                        position: 'absolute',
                        top: 6,
                        right: 6,
                        zIndex: 10,
                        background: 'rgba(0,0,0,0.7)',
                        padding: '2px 6px',
                        borderRadius: 4,
                        fontSize: '0.65rem',
                        fontFamily: 'monospace',
                        color: '#aaa',
                    }}
                >
                    {currentSlice + 1}/{totalSlices}
                </div>

                {/* Canvas Container */}
                <div
                    style={{
                        width: '100%',
                        height: '100%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: isDragging ? 'grabbing' : 'crosshair',
                    }}
                    onWheel={handleWheel}
                    onMouseDown={handleMouseDown}
                    onMouseMove={handleMouseMove}
                    onMouseUp={handleMouseUp}
                    onMouseLeave={handleMouseUp}
                >
                    <div
                        style={{
                            position: 'relative',
                            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                            transition: isDragging ? 'none' : 'transform 0.05s ease-out',
                        }}
                    >
                        {/* CT Canvas */}
                        <canvas
                            ref={canvasRef}
                            style={{
                                display: 'block',
                                imageRendering: 'pixelated',
                            }}
                        />

                        {/* Mask Canvas */}
                        {showMask && (
                            <canvas
                                ref={maskCanvasRef}
                                style={{
                                    position: 'absolute',
                                    top: 0,
                                    left: 0,
                                    width: '100%',
                                    height: '100%',
                                    opacity: maskOpacity,
                                    pointerEvents: 'none',
                                    mixBlendMode: 'screen',
                                }}
                            />
                        )}

                        {/* Crosshair */}
                        {crosshairPosition && imageData && (
                            <>
                                <div
                                    style={{
                                        position: 'absolute',
                                        left: 0,
                                        right: 0,
                                        top: `${crosshairPosition.y * 100}%`,
                                        height: 1,
                                        background: VIEW_COLORS[view],
                                        opacity: 0.6,
                                        pointerEvents: 'none',
                                    }}
                                />
                                <div
                                    style={{
                                        position: 'absolute',
                                        top: 0,
                                        bottom: 0,
                                        left: `${crosshairPosition.x * 100}%`,
                                        width: 1,
                                        background: VIEW_COLORS[view],
                                        opacity: 0.6,
                                        pointerEvents: 'none',
                                    }}
                                />
                            </>
                        )}
                    </div>
                </div>

                {/* Controls */}
                <div
                    style={{
                        position: 'absolute',
                        bottom: 0,
                        left: 0,
                        right: 0,
                        background: 'linear-gradient(to top, rgba(0,0,0,0.8) 0%, transparent 100%)',
                        padding: '16px 8px 4px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                    }}
                >
                    <input
                        type="range"
                        min={0}
                        max={totalSlices - 1}
                        value={currentSlice}
                        onChange={(e) => onSliceChange(parseInt(e.target.value))}
                        onWheel={(e) => e.stopPropagation()}
                        style={{ flex: 1, height: 4 }}
                    />
                    <button
                        onClick={() => setZoom(z => Math.min(z * 1.3, 5))}
                        style={btnStyle}
                        title="Zoom In"
                    >
                        <ZoomIn size={10} />
                    </button>
                    <button
                        onClick={() => setZoom(z => Math.max(z / 1.3, 0.5))}
                        style={btnStyle}
                        title="Zoom Out"
                    >
                        <ZoomOut size={10} />
                    </button>
                    <button onClick={resetView} style={btnStyle} title="Reset">
                        <RotateCcw size={10} />
                    </button>
                </div>
            </div>
        );
    };

const btnStyle: React.CSSProperties = {
    width: 20,
    height: 20,
    padding: 0,
    background: 'rgba(255,255,255,0.1)',
    border: '1px solid rgba(255,255,255,0.2)',
    borderRadius: 3,
    color: '#aaa',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
};

/**
 * MPR Layout Component
 * 
 * Displays synchronized Axial, Sagittal, and Coronal views
 * with direct canvas rendering for near-zero latency
 */
export const MPRLayout: React.FC<MPRLayoutProps> = ({
    caseId,
    windowPreset,
    showSegmentation,
    segmentationOpacity,
}) => {
    const {
        volume,
        loading,
        loadProgress,
        error,
        isLoaded,
        crosshair,
        setCrosshair,
        handleScroll,
        renderSliceToImageData,
        renderMaskSliceToImageData,
        getViewDimensions,
        setWindowPreset,
        showMask,
        setShowMask,
        setMaskOpacity,
    } = useVolumeViewer(caseId);

    // Sync props
    useEffect(() => {
        setWindowPreset(windowPreset);
    }, [windowPreset, setWindowPreset]);

    useEffect(() => {
        setShowMask(showSegmentation);
        setMaskOpacity(segmentationOpacity);
    }, [showSegmentation, segmentationOpacity, setShowMask, setMaskOpacity]);

    // Render slices (memoized for performance)
    const axialImage = useMemo(() =>
        isLoaded ? renderSliceToImageData('AXIAL', crosshair.z, windowPreset) : null,
        [isLoaded, crosshair.z, windowPreset, renderSliceToImageData]
    );

    const sagittalImage = useMemo(() =>
        isLoaded ? renderSliceToImageData('SAGITTAL', crosshair.x, windowPreset) : null,
        [isLoaded, crosshair.x, windowPreset, renderSliceToImageData]
    );

    const coronalImage = useMemo(() =>
        isLoaded ? renderSliceToImageData('CORONAL', crosshair.y, windowPreset) : null,
        [isLoaded, crosshair.y, windowPreset, renderSliceToImageData]
    );

    // Mask slices
    const axialMask = useMemo(() =>
        isLoaded && showMask ? renderMaskSliceToImageData('AXIAL', crosshair.z) : null,
        [isLoaded, showMask, crosshair.z, renderMaskSliceToImageData]
    );

    const sagittalMask = useMemo(() =>
        isLoaded && showMask ? renderMaskSliceToImageData('SAGITTAL', crosshair.x) : null,
        [isLoaded, showMask, crosshair.x, renderMaskSliceToImageData]
    );

    const coronalMask = useMemo(() =>
        isLoaded && showMask ? renderMaskSliceToImageData('CORONAL', crosshair.y) : null,
        [isLoaded, showMask, crosshair.y, renderMaskSliceToImageData]
    );

    // Dimensions
    const axialDims = useMemo(() => getViewDimensions('AXIAL'), [getViewDimensions]);
    const sagittalDims = useMemo(() => getViewDimensions('SAGITTAL'), [getViewDimensions]);
    const coronalDims = useMemo(() => getViewDimensions('CORONAL'), [getViewDimensions]);

    // Crosshair positions (normalized)
    const axialCrosshair = useMemo(() => {
        if (!volume) return undefined;
        return {
            x: crosshair.x / (volume.shape[0] - 1),
            y: crosshair.y / (volume.shape[1] - 1),
        };
    }, [crosshair, volume]);

    const sagittalCrosshair = useMemo(() => {
        if (!volume) return undefined;
        return {
            x: crosshair.y / (volume.shape[1] - 1),
            y: 1 - crosshair.z / (volume.shape[2] - 1),
        };
    }, [crosshair, volume]);

    const coronalCrosshair = useMemo(() => {
        if (!volume) return undefined;
        return {
            x: crosshair.x / (volume.shape[0] - 1),
            y: 1 - crosshair.z / (volume.shape[2] - 1),
        };
    }, [crosshair, volume]);

    // Click handlers
    const handleAxialClick = useCallback((x: number, y: number) => {
        if (!volume) return;
        setCrosshair(prev => ({
            ...prev,
            x: Math.round(x * (volume.shape[0] - 1)),
            y: Math.round(y * (volume.shape[1] - 1)),
        }));
    }, [volume, setCrosshair]);

    const handleSagittalClick = useCallback((x: number, y: number) => {
        if (!volume) return;
        setCrosshair(prev => ({
            ...prev,
            y: Math.round(x * (volume.shape[1] - 1)),
            z: Math.round((1 - y) * (volume.shape[2] - 1)),
        }));
    }, [volume, setCrosshair]);

    const handleCoronalClick = useCallback((x: number, y: number) => {
        if (!volume) return;
        setCrosshair(prev => ({
            ...prev,
            x: Math.round(x * (volume.shape[0] - 1)),
            z: Math.round((1 - y) * (volume.shape[2] - 1)),
        }));
    }, [volume, setCrosshair]);

    // Slice change handlers
    const handleAxialSliceChange = useCallback((i: number) => setCrosshair(p => ({ ...p, z: i })), [setCrosshair]);
    const handleSagittalSliceChange = useCallback((i: number) => setCrosshair(p => ({ ...p, x: i })), [setCrosshair]);
    const handleCoronalSliceChange = useCallback((i: number) => setCrosshair(p => ({ ...p, y: i })), [setCrosshair]);

    // Loading
    if (loading) {
        return (
            <div style={centerStyle}>
                <Loader2 size={40} color="#6366f1" style={{ animation: 'spin 1s linear infinite' }} />
                <div style={{ marginTop: 12, fontSize: '0.9rem', color: '#888' }}>
                    Loading CT Volume... {loadProgress}%
                </div>
                <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
            </div>
        );
    }

    // Error
    if (error) {
        return (
            <div style={{ ...centerStyle, color: '#ef4444' }}>
                Error: {error}
            </div>
        );
    }

    // Not loaded
    if (!isLoaded || !volume) {
        return (
            <div style={{ ...centerStyle, color: '#666' }}>
                No volume data
            </div>
        );
    }

    return (
        <div
            style={{
                width: '100%',
                height: '100%',
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gridTemplateRows: '1fr 1fr',
                gap: 2,
                background: '#000',
            }}
        >
            {/* Axial (Top Left) */}
            <MPRViewPanel
                view="AXIAL"
                imageData={axialImage}
                maskData={axialMask}
                showMask={showMask}
                maskOpacity={segmentationOpacity}
                currentSlice={crosshair.z}
                totalSlices={axialDims?.maxSlice || 0}
                crosshairPosition={axialCrosshair}
                onSliceChange={handleAxialSliceChange}
                onScroll={(d) => handleScroll('AXIAL', d)}
                onCrosshairClick={handleAxialClick}
            />

            {/* Sagittal (Top Right) */}
            <MPRViewPanel
                view="SAGITTAL"
                imageData={sagittalImage}
                maskData={sagittalMask}
                showMask={showMask}
                maskOpacity={segmentationOpacity}
                currentSlice={crosshair.x}
                totalSlices={sagittalDims?.maxSlice || 0}
                crosshairPosition={sagittalCrosshair}
                onSliceChange={handleSagittalSliceChange}
                onScroll={(d) => handleScroll('SAGITTAL', d)}
                onCrosshairClick={handleSagittalClick}
            />

            {/* Coronal (Bottom Left) */}
            <MPRViewPanel
                view="CORONAL"
                imageData={coronalImage}
                maskData={coronalMask}
                showMask={showMask}
                maskOpacity={segmentationOpacity}
                currentSlice={crosshair.y}
                totalSlices={coronalDims?.maxSlice || 0}
                crosshairPosition={coronalCrosshair}
                onSliceChange={handleCoronalSliceChange}
                onScroll={(d) => handleScroll('CORONAL', d)}
                onCrosshairClick={handleCoronalClick}
            />

            {/* Info Panel (Bottom Right) */}
            <div
                style={{
                    background: '#111',
                    padding: 12,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                    overflow: 'auto',
                    fontSize: '0.75rem',
                    color: '#888',
                }}
            >
                <div style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>
                    Volume Info
                </div>
                <div>Dimensions: <span style={{ color: '#fff', fontFamily: 'monospace' }}>{volume.shape.join(' × ')}</span></div>
                <div>Spacing: <span style={{ color: '#fff', fontFamily: 'monospace' }}>{volume.spacing.map(s => s.toFixed(2)).join(' × ')} mm</span></div>

                <div style={{ marginTop: 8, padding: 8, background: '#1a1a1a', borderRadius: 4 }}>
                    <div style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4, fontSize: '0.65rem' }}>
                        Crosshair
                    </div>
                    <div style={{ fontFamily: 'monospace', color: '#fff' }}>
                        X: {crosshair.x} | Y: {crosshair.y} | Z: {crosshair.z}
                    </div>
                </div>

                <div style={{ flex: 1 }} />

                <div style={{ fontSize: '0.65rem', lineHeight: 1.5 }}>
                    <div>• Scroll: Navigate slices</div>
                    <div>• Click: Move crosshair</div>
                    <div>• Right-drag: Pan</div>
                </div>
            </div>
        </div>
    );
};

const centerStyle: React.CSSProperties = {
    width: '100%',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#000',
};

export default MPRLayout;
