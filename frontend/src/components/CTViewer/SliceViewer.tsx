import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Loader2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';
import { useVolumeViewer } from '../../hooks/useVolumeViewer';
import { useViewerInteractions } from '../../hooks/useViewerInteractions';
import { useViewerStore } from '../../stores/viewerStore';
import { type MPRView, type NoduleEntity, type WindowPresetKey } from '../../types';
import { createExportCanvas, canvasToBlob, getSupportedVideoMimeType, wait } from '../../utils/export';
import { registerSliceExporter } from '../../utils/exportRegistry';
import { getSegmentationPaletteTokens } from '../../utils/segmentationPalette';
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

const drawRoundedRect = (
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    radius: number
) => {
    const safeRadius = Math.max(0, Math.min(radius, width / 2, height / 2));
    ctx.beginPath();
    ctx.moveTo(x + safeRadius, y);
    ctx.lineTo(x + width - safeRadius, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + safeRadius);
    ctx.lineTo(x + width, y + height - safeRadius);
    ctx.quadraticCurveTo(x + width, y + height, x + width - safeRadius, y + height);
    ctx.lineTo(x + safeRadius, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - safeRadius);
    ctx.lineTo(x, y + safeRadius);
    ctx.quadraticCurveTo(x, y, x + safeRadius, y);
    ctx.closePath();
};

const imageDataToCanvas = (imageData: ImageData) => {
    const canvas = createExportCanvas(imageData.width, imageData.height);
    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) {
        throw new Error('Unable to create export surface.');
    }

    ctx.putImageData(imageData, 0, 0);
    return canvas;
};

const drawBadge = (
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    text: string,
    colors: {
        background: string;
        border: string;
        text: string;
    },
    font = '600 14px sans-serif',
    paddingX = 12,
    paddingY = 8
) => {
    ctx.save();
    ctx.font = font;
    const metrics = ctx.measureText(text);
    const width = Math.ceil(metrics.width + paddingX * 2);
    const height = Math.ceil(14 + paddingY * 2);

    drawRoundedRect(ctx, x, y, width, height, 6);
    ctx.fillStyle = colors.background;
    ctx.fill();
    ctx.strokeStyle = colors.border;
    ctx.lineWidth = 1;
    ctx.stroke();

    ctx.fillStyle = colors.text;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, x + paddingX, y + height / 2);
    ctx.restore();

    return { width, height };
};

const normalizeSliceRange = (start: number, end: number): [number, number] => {
    const min = Math.min(start, end);
    const max = Math.max(start, end);
    return [min, max];
};

const getNoduleSliceRange = (nodule: NoduleEntity, viewType: MPRView): [number, number] => {
    switch (viewType) {
        case 'AXIAL':
            return normalizeSliceRange(nodule.slice_range[0], nodule.slice_range[1]);
        case 'CORONAL':
            return normalizeSliceRange(
                Math.round(nodule.bbox_xyz[1][0]),
                Math.round(nodule.bbox_xyz[1][1]),
            );
        case 'SAGITTAL':
            return normalizeSliceRange(
                Math.round(nodule.bbox_xyz[0][0]),
                Math.round(nodule.bbox_xyz[0][1]),
            );
        default:
            return [0, 0];
    }
};

const getNoduleTargetSlice = (nodule: NoduleEntity, viewType: MPRView): number => {
    switch (viewType) {
        case 'AXIAL':
            return Math.round(nodule.centroid_xyz[2]);
        case 'CORONAL':
            return Math.round(nodule.centroid_xyz[1]);
        case 'SAGITTAL':
            return Math.round(nodule.centroid_xyz[0]);
        default:
            return 0;
    }
};

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
    const segmentationPaletteMode = useViewerStore((state) => state.segmentationPaletteMode);
    const noduleEntities = useViewerStore((state) => state.noduleEntities);
    const selectedNoduleId = useViewerStore((state) => state.selectedNoduleId);
    const activateNodule = useViewerStore((state) => state.activateNodule);

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
    const paletteTokens = useMemo(
        () => getSegmentationPaletteTokens(segmentationPaletteMode),
        [segmentationPaletteMode],
    );
    const selectedNoduleIndex = useMemo(
        () => sortedNoduleEntities.findIndex((nodule) => nodule.id === selectedNoduleId),
        [selectedNoduleId, sortedNoduleEntities],
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

    const renderImageForSlice = useCallback((sliceIndex: number) => {
        if (!isLoaded) {
            return null;
        }

        return useCustomWindow
            ? renderSliceWithCustomWindow(viewType, sliceIndex, customWindowLevel, customWindowWidth)
            : renderSliceToImageData(viewType, sliceIndex, windowPreset);
    }, [
        customWindowLevel,
        customWindowWidth,
        isLoaded,
        renderSliceToImageData,
        renderSliceWithCustomWindow,
        useCustomWindow,
        viewType,
        windowPreset,
    ]);

    const renderMaskForSlice = useCallback((sliceIndex: number) => {
        if (!showSegmentation || !hasMask) {
            return null;
        }

        return renderMaskSliceToImageData(viewType, sliceIndex);
    }, [hasMask, renderMaskSliceToImageData, showSegmentation, viewType]);

    const renderExportFrame = useCallback(async (options?: { includeBadges?: boolean; sliceIndex?: number }) => {
        const requestedSlice = options?.sliceIndex ?? currentSlice;
        const clampedSlice = Math.max(0, Math.min(sliceCount - 1, requestedSlice));
        const nextImageData = renderImageForSlice(clampedSlice);

        if (!nextImageData) {
            throw new Error('2D slice is not ready yet.');
        }

        const nextMaskImageData = renderMaskForSlice(clampedSlice);
        const viewportWidth = Math.max(
            containerSize.width || fittedCanvasSize?.width || nextImageData.width,
            1
        );
        const viewportHeight = Math.max(
            containerSize.height || fittedCanvasSize?.height || nextImageData.height,
            1
        );
        const exportCanvas = createExportCanvas(viewportWidth, viewportHeight);
        const ctx = exportCanvas.getContext('2d', { alpha: false });

        if (!ctx) {
            throw new Error('Unable to initialize export canvas.');
        }

        const sliceCanvas = imageDataToCanvas(nextImageData);
        const maskCanvas = nextMaskImageData ? imageDataToCanvas(nextMaskImageData) : null;
        const baseWidth = fittedCanvasSize?.width ?? nextImageData.width;
        const baseHeight = fittedCanvasSize?.height ?? nextImageData.height;
        const displayWidth = Math.max(1, baseWidth * zoom);
        const displayHeight = Math.max(1, baseHeight * zoom);
        const offsetX = (viewportWidth - displayWidth) / 2 + pan.x;
        const offsetY = (viewportHeight - displayHeight) / 2 + pan.y;
        const shouldDrawBadges = options?.includeBadges ?? true;

        ctx.fillStyle = '#000000';
        ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(sliceCanvas, offsetX, offsetY, displayWidth, displayHeight);

        if (maskCanvas && showSegmentation) {
            ctx.save();
            ctx.globalAlpha = segmentationOpacity;
            ctx.drawImage(maskCanvas, offsetX, offsetY, displayWidth, displayHeight);
            ctx.restore();
        }

        if (isMprCrosshairView && crosshairPos) {
            const crosshairX = offsetX + displayWidth * (crosshairPos.cx / 100);
            const crosshairY = offsetY + displayHeight * (crosshairPos.cy / 100);
            const lineThickness = Math.max(1, 1 / Math.max(zoom, 0.1));

            ctx.save();
            ctx.strokeStyle = `${paletteTokens.crosshair}cc`;
            ctx.lineWidth = lineThickness;
            ctx.beginPath();
            ctx.moveTo(offsetX, crosshairY);
            ctx.lineTo(offsetX + displayWidth, crosshairY);
            ctx.moveTo(crosshairX, offsetY);
            ctx.lineTo(crosshairX, offsetY + displayHeight);
            ctx.stroke();
            ctx.restore();
        }

        if (shouldDrawBadges) {
            drawBadge(
                ctx,
                16,
                8,
                viewLabel,
                {
                    background: 'rgba(0, 0, 0, 0.74)',
                    border: 'rgba(99, 102, 241, 0.42)',
                    text: '#818cf8',
                }
            );

            ctx.save();
            ctx.font = '600 13px monospace';
            const counterText = `${clampedSlice + 1}/${sliceCount}`;
            const counterMetrics = ctx.measureText(counterText);
            const counterWidth = Math.ceil(counterMetrics.width + 16);
            const counterHeight = 30;
            const counterX = exportCanvas.width - counterWidth - 8;

            drawRoundedRect(ctx, counterX, 8, counterWidth, counterHeight, 6);
            ctx.fillStyle = 'rgba(0, 0, 0, 0.74)';
            ctx.fill();
            ctx.fillStyle = '#b3b3b3';
            ctx.textAlign = 'left';
            ctx.textBaseline = 'middle';
            ctx.fillText(counterText, counterX + 8, 8 + counterHeight / 2);
            ctx.restore();
        }

        return exportCanvas;
    }, [
        containerSize.height,
        containerSize.width,
        crosshairPos,
        currentSlice,
        fittedCanvasSize?.height,
        fittedCanvasSize?.width,
        isMprCrosshairView,
        pan.x,
        pan.y,
        renderImageForSlice,
        renderMaskForSlice,
        paletteTokens.crosshair,
        segmentationOpacity,
        showSegmentation,
        sliceCount,
        viewLabel,
        zoom,
    ]);

    const captureSlicePng = useCallback(async (options?: { includeBadges?: boolean; sliceIndex?: number }) => {
        const exportCanvas = await renderExportFrame(options);
        return canvasToBlob(exportCanvas, 'image/png');
    }, [renderExportFrame]);

    const captureSliceVideo = useCallback(async ({
        fps,
        startSlice,
        endSlice,
        includeBadges = true,
    }: {
        fps: number;
        startSlice: number;
        endSlice: number;
        includeBadges?: boolean;
    }) => {
        if (typeof MediaRecorder === 'undefined') {
            throw new Error('This browser does not support WebM export.');
        }

        const safeFps = Math.max(1, Math.min(30, Math.round(fps)));
        const normalizedStart = Math.max(0, Math.min(sliceCount - 1, startSlice));
        const normalizedEnd = Math.max(0, Math.min(sliceCount - 1, endSlice));
        const sliceStep = normalizedStart <= normalizedEnd ? 1 : -1;
        const firstFrame = await renderExportFrame({
            includeBadges,
            sliceIndex: normalizedStart,
        });
        const recordingCanvas = createExportCanvas(firstFrame.width, firstFrame.height);
        const recordingContext = recordingCanvas.getContext('2d', { alpha: false });

        if (!recordingContext) {
            throw new Error('Unable to initialize video encoder surface.');
        }

        if (typeof recordingCanvas.captureStream !== 'function') {
            throw new Error('This browser does not support canvas video capture.');
        }

        const mimeType = getSupportedVideoMimeType();
        const stream = recordingCanvas.captureStream(safeFps);
        const chunks: BlobPart[] = [];

        const resultPromise = new Promise<Blob>((resolve, reject) => {
            const recorder = new MediaRecorder(
                stream,
                mimeType ? { mimeType } : undefined,
            );

            recorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    chunks.push(event.data);
                }
            };
            recorder.onerror = () => {
                reject(new Error('Unable to encode 2D slice video.'));
            };
            recorder.onstop = () => {
                resolve(new Blob(chunks, { type: mimeType || 'video/webm' }));
            };

            recorder.start();

            const renderFrames = async () => {
                try {
                    recordingContext.imageSmoothingEnabled = false;

                    for (
                        let sliceIndex = normalizedStart;
                        sliceStep > 0 ? sliceIndex <= normalizedEnd : sliceIndex >= normalizedEnd;
                        sliceIndex += sliceStep
                    ) {
                        const frameCanvas = sliceIndex === normalizedStart
                            ? firstFrame
                            : await renderExportFrame({ includeBadges, sliceIndex });

                        recordingContext.clearRect(0, 0, recordingCanvas.width, recordingCanvas.height);
                        recordingContext.drawImage(frameCanvas, 0, 0);
                        await wait(1000 / safeFps);
                    }

                    await wait(Math.max(200, 1000 / safeFps));
                    recorder.stop();
                } catch (error) {
                    reject(error instanceof Error ? error : new Error('Unable to render 2D slice video.'));
                    recorder.stop();
                }
            };

            void renderFrames();
        });

        try {
            return await resultPromise;
        } finally {
            stream.getTracks().forEach((track) => track.stop());
        }
    }, [renderExportFrame, sliceCount]);

    const renderExportFrameRef = useRef(renderExportFrame);
    const captureSlicePngRef = useRef(captureSlicePng);
    const captureSliceVideoRef = useRef(captureSliceVideo);
    const sliceRangeRef = useRef({
        min: 0,
        max: Math.max(sliceCount - 1, 0),
        current: currentSlice,
    });

    useEffect(() => {
        renderExportFrameRef.current = renderExportFrame;
        captureSlicePngRef.current = captureSlicePng;
        captureSliceVideoRef.current = captureSliceVideo;
        sliceRangeRef.current = {
            min: 0,
            max: Math.max(sliceCount - 1, 0),
            current: currentSlice,
        };
    }, [captureSlicePng, captureSliceVideo, currentSlice, renderExportFrame, sliceCount]);

    useEffect(() => registerSliceExporter(viewType, {
        renderFrame: (options) => renderExportFrameRef.current(options),
        capturePng: (options) => captureSlicePngRef.current(options),
        captureVideo: (options) => captureSliceVideoRef.current(options),
        getSliceRange: () => sliceRangeRef.current,
    }), [viewType]);

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

    const handleNoduleJump = useCallback((noduleId: string, targetSlice: number) => {
        const isSameNodule = selectedNoduleId === noduleId;

        const nextSlice = Math.max(0, Math.min(sliceCount - 1, targetSlice));
        activateNodule(noduleId);
        if (isSameNodule) {
            return;
        }
        updateCrosshair(viewType, nextSlice);
        onIndexChange?.(nextSlice);
    }, [activateNodule, onIndexChange, selectedNoduleId, sliceCount, updateCrosshair, viewType]);

    const navigateNodule = useCallback((direction: -1 | 1) => {
        if (sortedNoduleEntities.length === 0) {
            return;
        }

        const fallbackIndex = direction > 0 ? 0 : sortedNoduleEntities.length - 1;
        const currentIndex = selectedNoduleIndex === -1 ? fallbackIndex : selectedNoduleIndex;
        const nextIndex = (currentIndex + direction + sortedNoduleEntities.length) % sortedNoduleEntities.length;
        const nextNodule = sortedNoduleEntities[nextIndex];
        handleNoduleJump(nextNodule.id, getNoduleTargetSlice(nextNodule, viewType));
    }, [handleNoduleJump, selectedNoduleIndex, sortedNoduleEntities, viewType]);

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
                                    background: `${paletteTokens.crosshair}b3`,
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
                                    background: `${paletteTokens.crosshair}b3`,
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
                                    color: paletteTokens.noduleChipText,
                                }}
                            >
                                Nodule Slice List
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                Highlighted nodules can be navigated slice by slice
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <button
                                type="button"
                                onClick={() => navigateNodule(-1)}
                                disabled={sortedNoduleEntities.length <= 1}
                                style={navigatorButtonStyle}
                            >
                                <ChevronLeft size={14} />
                            </button>
                            <span
                                style={{
                                    padding: '2px 7px',
                                    borderRadius: '999px',
                                    background: paletteTokens.noduleChipBackground,
                                    color: paletteTokens.noduleChipText,
                                    fontSize: '0.68rem',
                                    fontWeight: 700,
                                    minWidth: 34,
                                    textAlign: 'center',
                                }}
                            >
                                {selectedNoduleIndex === -1
                                    ? `${sortedNoduleEntities.length}`
                                    : `${selectedNoduleIndex + 1}/${sortedNoduleEntities.length}`}
                            </span>
                            <button
                                type="button"
                                onClick={() => navigateNodule(1)}
                                disabled={sortedNoduleEntities.length <= 1}
                                style={navigatorButtonStyle}
                            >
                                <ChevronRight size={14} />
                            </button>
                        </div>
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
                            const sliceRange = getNoduleSliceRange(nodule, viewType);
                            const isVisibleOnCurrentSlice =
                                currentSlice >= sliceRange[0] &&
                                currentSlice <= sliceRange[1];
                            const buttonBorderColor = isSelected
                                ? `${paletteTokens.noduleOutline}cc`
                                : isVisibleOnCurrentSlice
                                    ? `${paletteTokens.crosshair}66`
                                    : 'rgba(255, 255, 255, 0.06)';
                            const buttonBackground = isSelected
                                ? `linear-gradient(135deg, ${paletteTokens.nodule}55 0%, rgba(66, 32, 6, 0.92) 100%)`
                                : isVisibleOnCurrentSlice
                                    ? `${paletteTokens.crosshair}14`
                                    : 'rgba(255, 255, 255, 0.03)';
                            const buttonBoxShadow = isSelected
                                ? `0 0 0 1px ${paletteTokens.noduleOutline}24, 0 12px 24px ${paletteTokens.nodule}22`
                                : isVisibleOnCurrentSlice
                                    ? `0 8px 18px ${paletteTokens.crosshair}22`
                                    : 'none';

                            return (
                                <button
                                    key={`slice-nodule:${nodule.id}`}
                                    type="button"
                                    onClick={() => handleNoduleJump(nodule.id, getNoduleTargetSlice(nodule, viewType))}
                                    title={isSelected
                                        ? `Clear focus for ${nodule.display_name}`
                                        : `Jump to slice ${getNoduleTargetSlice(nodule, viewType) + 1}`}
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
                                            color: isSelected ? paletteTokens.noduleSelectedText : 'var(--text-primary)',
                                        }}
                                    >
                                        {nodule.display_name}
                                    </span>
                                    <span
                                            style={{
                                                whiteSpace: 'nowrap',
                                                fontSize: '0.7rem',
                                                color: isSelected ? paletteTokens.noduleChipText : 'var(--text-secondary)',
                                            }}
                                    >
                                        Diameter {nodule.estimated_diameter_mm.toFixed(1)} mm
                                    </span>
                                    <span
                                            style={{
                                                whiteSpace: 'nowrap',
                                                fontSize: '0.7rem',
                                                fontWeight: 700,
                                                color: isSelected ? paletteTokens.noduleChipText : 'var(--text-muted)',
                                            }}
                                    >
                                        Z {sliceRange[0] + 1} - {sliceRange[1] + 1}
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
                                    border: `1px solid ${paletteTokens.crosshair}55`,
                                    color: paletteTokens.crosshair,
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
                                        background: `${paletteTokens.crosshair}99`,
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

const navigatorButtonStyle: React.CSSProperties = {
    width: 28,
    height: 28,
    padding: 0,
    borderRadius: 999,
    border: '1px solid rgba(255,255,255,0.12)',
    background: 'rgba(255,255,255,0.06)',
    color: 'var(--text-secondary)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
};

export default SliceViewer;
