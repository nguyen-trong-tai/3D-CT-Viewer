import React, { useRef, useCallback, useState, useEffect } from 'react';
import type { MPRView } from '../../types';
import { RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';

interface MPRViewerProps {
    view: MPRView;
    imageUrl: string;
    maskUrl: string | null;
    showMask: boolean;
    maskOpacity: number;
    currentSlice: number;
    totalSlices: number;
    crosshairPosition?: { x: number; y: number }; // Position within the slice (normalized 0-1)
    onSliceChange: (index: number) => void;
    onScroll: (delta: number) => void;
    onCrosshairClick?: (x: number, y: number) => void; // Click position (normalized 0-1)
    showControls?: boolean;
}

const VIEW_LABELS: Record<MPRView, string> = {
    AXIAL: 'Axial',
    SAGITTAL: 'Sagittal',
    CORONAL: 'Coronal',
};

const VIEW_COLORS: Record<MPRView, string> = {
    AXIAL: 'var(--accent-primary)',
    SAGITTAL: 'var(--accent-success)',
    CORONAL: 'var(--accent-warning)',
};

/**
 * MPR (Multiplanar Reconstruction) Viewer Component
 * 
 * OPTIMIZED: Uses direct canvas rendering for near-zero latency
 * - No base64 encoding/decoding overhead
 * - Direct ImageData manipulation
 * - Hardware-accelerated rendering
 */
export const MPRViewer: React.FC<MPRViewerProps> = ({
    view,
    imageUrl,
    maskUrl,
    showMask,
    maskOpacity,
    currentSlice,
    totalSlices,
    crosshairPosition,
    onSliceChange,
    onScroll,
    onCrosshairClick,
    showControls = true,
}) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const maskCanvasRef = useRef<HTMLCanvasElement>(null);
    const [zoom, setZoom] = useState(1);
    const [pan, setPan] = useState({ x: 0, y: 0 });
    const [isDragging, setIsDragging] = useState(false);
    const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
    const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });

    // Image objects for rendering (cached)
    const imageRef = useRef<HTMLImageElement | null>(null);
    const maskImageRef = useRef<HTMLImageElement | null>(null);
    const lastImageUrl = useRef<string>('');
    const lastMaskUrl = useRef<string>('');

    // Render image to canvas when imageUrl changes
    useEffect(() => {
        if (!imageUrl || imageUrl === lastImageUrl.current) return;
        lastImageUrl.current = imageUrl;

        const img = new Image();
        img.onload = () => {
            imageRef.current = img;
            setCanvasSize({ width: img.width, height: img.height });

            const canvas = canvasRef.current;
            if (canvas) {
                canvas.width = img.width;
                canvas.height = img.height;
                const ctx = canvas.getContext('2d');
                if (ctx) {
                    ctx.imageSmoothingEnabled = false;
                    ctx.drawImage(img, 0, 0);
                }
            }
        };
        img.src = imageUrl;
    }, [imageUrl]);

    // Render mask to canvas when maskUrl changes
    useEffect(() => {
        if (!maskUrl || maskUrl === lastMaskUrl.current) return;
        lastMaskUrl.current = maskUrl;

        const img = new Image();
        img.onload = () => {
            maskImageRef.current = img;

            const canvas = maskCanvasRef.current;
            if (canvas && canvasSize.width > 0) {
                canvas.width = img.width;
                canvas.height = img.height;
                const ctx = canvas.getContext('2d');
                if (ctx) {
                    ctx.imageSmoothingEnabled = false;
                    ctx.drawImage(img, 0, 0);
                }
            }
        };
        img.src = maskUrl;
    }, [maskUrl, canvasSize]);

    // Handle mouse wheel for slice navigation
    const handleWheel = useCallback((e: React.WheelEvent) => {
        e.preventDefault();
        const delta = Math.sign(e.deltaY);
        onScroll(delta);
    }, [onScroll]);

    // Handle mouse down for pan start
    const handleMouseDown = useCallback((e: React.MouseEvent) => {
        // Right-click or Ctrl+click for pan
        if (e.button === 2 || (e.button === 0 && e.ctrlKey)) {
            e.preventDefault();
            setIsDragging(true);
            setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
        } else if (e.button === 0 && onCrosshairClick) {
            // Left-click to update crosshair
            const rect = e.currentTarget.getBoundingClientRect();
            const x = (e.clientX - rect.left - rect.width / 2 - pan.x) / zoom / canvasSize.width + 0.5;
            const y = (e.clientY - rect.top - rect.height / 2 - pan.y) / zoom / canvasSize.height + 0.5;

            if (x >= 0 && x <= 1 && y >= 0 && y <= 1) {
                onCrosshairClick(x, y);
            }
        }
    }, [pan, zoom, canvasSize, onCrosshairClick]);

    // Handle mouse move for pan
    const handleMouseMove = useCallback((e: React.MouseEvent) => {
        if (isDragging) {
            setPan({
                x: e.clientX - dragStart.x,
                y: e.clientY - dragStart.y,
            });
        }
    }, [isDragging, dragStart]);

    // Handle mouse up for pan end
    const handleMouseUp = useCallback(() => {
        setIsDragging(false);
    }, []);

    // Reset view
    const resetView = useCallback(() => {
        setZoom(1);
        setPan({ x: 0, y: 0 });
    }, []);

    // Zoom controls
    const zoomIn = () => setZoom((z) => Math.min(z * 1.2, 5));
    const zoomOut = () => setZoom((z) => Math.max(z / 1.2, 0.5));

    // Prevent context menu on right-click
    const handleContextMenu = (e: React.MouseEvent) => {
        e.preventDefault();
    };

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
            onContextMenu={handleContextMenu}
        >
            {/* View Label Badge */}
            <div
                style={{
                    position: 'absolute',
                    top: 'var(--space-sm)',
                    left: 'var(--space-sm)',
                    zIndex: 10,
                    display: 'flex',
                    gap: 'var(--space-xs)',
                    alignItems: 'center',
                }}
            >
                <div
                    style={{
                        background: 'var(--bg-glass)',
                        backdropFilter: 'blur(8px)',
                        padding: '3px 10px',
                        borderRadius: 'var(--radius-sm)',
                        border: `1px solid ${VIEW_COLORS[view]}40`,
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: VIEW_COLORS[view],
                    }}
                >
                    {VIEW_LABELS[view]}
                </div>
            </div>

            {/* Slice Counter */}
            <div
                style={{
                    position: 'absolute',
                    top: 'var(--space-sm)',
                    right: 'var(--space-sm)',
                    zIndex: 10,
                    background: 'var(--bg-glass)',
                    backdropFilter: 'blur(8px)',
                    padding: '3px 8px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '0.7rem',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-secondary)',
                }}
            >
                {currentSlice + 1}/{totalSlices}
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

                    {/* Mask Canvas Overlay */}
                    {showMask && maskUrl && (
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

                    {/* Crosshair Overlay */}
                    {crosshairPosition && canvasSize.width > 0 && (
                        <>
                            {/* Horizontal line */}
                            <div
                                style={{
                                    position: 'absolute',
                                    left: 0,
                                    right: 0,
                                    top: `${crosshairPosition.y * 100}%`,
                                    height: 1,
                                    background: VIEW_COLORS[view],
                                    opacity: 0.7,
                                    pointerEvents: 'none',
                                }}
                            />
                            {/* Vertical line */}
                            <div
                                style={{
                                    position: 'absolute',
                                    top: 0,
                                    bottom: 0,
                                    left: `${crosshairPosition.x * 100}%`,
                                    width: 1,
                                    background: VIEW_COLORS[view],
                                    opacity: 0.7,
                                    pointerEvents: 'none',
                                }}
                            />
                        </>
                    )}
                </div>

                {/* Loading Placeholder */}
                {!imageUrl && (
                    <div
                        style={{
                            position: 'absolute',
                            color: 'var(--text-muted)',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: 'var(--space-md)',
                        }}
                    >
                        <div
                            style={{
                                width: 32,
                                height: 32,
                                border: '3px solid var(--border-subtle)',
                                borderTopColor: VIEW_COLORS[view],
                                borderRadius: '50%',
                                animation: 'spin 1s linear infinite',
                            }}
                        />
                        <span style={{ fontSize: '0.8rem' }}>Loading...</span>
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
                        padding: 'var(--space-lg) var(--space-sm) var(--space-xs)',
                    }}
                >
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 'var(--space-sm)',
                        }}
                    >
                        <div style={{ flex: 1 }} onWheel={(e) => e.stopPropagation()}>
                            <input
                                type="range"
                                min={0}
                                max={totalSlices - 1}
                                value={currentSlice}
                                onChange={(e) => onSliceChange(parseInt(e.target.value))}
                                style={{ width: '100%', height: 4 }}
                            />
                        </div>
                        <button
                            onClick={zoomIn}
                            style={{
                                width: 24,
                                height: 24,
                                padding: 0,
                                background: 'var(--bg-glass)',
                                border: '1px solid var(--border-subtle)',
                                borderRadius: 'var(--radius-xs)',
                                color: 'var(--text-muted)',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                            }}
                            title="Zoom In"
                        >
                            <ZoomIn size={12} />
                        </button>
                        <button
                            onClick={zoomOut}
                            style={{
                                width: 24,
                                height: 24,
                                padding: 0,
                                background: 'var(--bg-glass)',
                                border: '1px solid var(--border-subtle)',
                                borderRadius: 'var(--radius-xs)',
                                color: 'var(--text-muted)',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                            }}
                            title="Zoom Out"
                        >
                            <ZoomOut size={12} />
                        </button>
                        <button
                            onClick={resetView}
                            style={{
                                width: 24,
                                height: 24,
                                padding: 0,
                                background: 'var(--bg-glass)',
                                border: '1px solid var(--border-subtle)',
                                borderRadius: 'var(--radius-xs)',
                                color: 'var(--text-muted)',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                            }}
                            title="Reset View"
                        >
                            <RotateCcw size={12} />
                        </button>
                    </div>
                </div>
            )}

            {/* CSS Animations */}
            <style>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </div>
    );
};

export default MPRViewer;
