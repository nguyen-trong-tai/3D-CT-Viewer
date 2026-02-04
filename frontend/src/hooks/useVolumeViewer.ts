
import { useState, useCallback, useRef, useEffect } from 'react';
import { ctApi, maskApi } from '../services/api';
import { WINDOW_PRESETS, type WindowPresetKey, type MPRView } from '../types';

interface VolumeData {
    data: Int16Array;
    shape: [number, number, number]; // [X, Y, Z]
    spacing: [number, number, number];
}

interface MaskData {
    data: Uint8Array;
    shape: [number, number, number];
}

// Global cache for volume data (shared across all hook instances)
const globalVolumeCache = new Map<string, VolumeData>();
const globalMaskCache = new Map<string, MaskData>();
const globalLoadingPromises = new Map<string, Promise<void>>();

/**
 * Hook for volume-based CT viewing
 * Loads entire volume into memory for instant slice access
 */
export function useVolumeViewer(caseId: string | null) {
    // Volume state
    const [volume, setVolume] = useState<VolumeData | null>(null);
    const [mask, setMask] = useState<MaskData | null>(null);
    const [loading, setLoading] = useState(false);
    const [loadProgress, setLoadProgress] = useState(0);
    const [error, setError] = useState<string | null>(null);

    // View state
    const [windowPreset, setWindowPreset] = useState<WindowPresetKey>('SOFT_TISSUE');
    const [showMask, setShowMask] = useState(false);
    const [maskOpacity, setMaskOpacity] = useState(0.5);

    // Crosshair position for MPR synchronization (voxel indices)
    const [crosshair, setCrosshair] = useState({ x: 0, y: 0, z: 0 });

    // ImageData cache for ultra-fast rendering
    const imageDataCache = useRef(new Map<string, ImageData>());

    // Loading guard to prevent duplicate loads
    const loadingRef = useRef(false);
    const loadedCaseRef = useRef<string | null>(null);

    // Progress throttling
    const lastProgressRef = useRef(0);

    /**
     * Load volume data from backend (with global deduplication)
     */
    const loadVolume = useCallback(async () => {
        if (!caseId) return;

        // Check if already loaded locally
        if (loadedCaseRef.current === caseId) {
            return;
        }

        // Check global cache first
        const cachedVolume = globalVolumeCache.get(caseId);
        if (cachedVolume) {
            console.log('[VolumeViewer] Using cached volume for:', caseId);
            setVolume(cachedVolume);
            setCrosshair({
                x: Math.floor(cachedVolume.shape[0] / 2),
                y: Math.floor(cachedVolume.shape[1] / 2),
                z: Math.floor(cachedVolume.shape[2] / 2),
            });

            const cachedMask = globalMaskCache.get(caseId);
            if (cachedMask) {
                setMask(cachedMask);
            }

            loadedCaseRef.current = caseId;
            setLoadProgress(100);
            return;
        }

        // Check if loading is already in progress
        const existingPromise = globalLoadingPromises.get(caseId);
        if (existingPromise) {
            console.log('[VolumeViewer] Waiting for existing load:', caseId);
            setLoading(true);
            await existingPromise;

            // After promise resolves, get from cache
            const vol = globalVolumeCache.get(caseId);
            if (vol) {
                setVolume(vol);
                setCrosshair({
                    x: Math.floor(vol.shape[0] / 2),
                    y: Math.floor(vol.shape[1] / 2),
                    z: Math.floor(vol.shape[2] / 2),
                });
            }
            const msk = globalMaskCache.get(caseId);
            if (msk) setMask(msk);

            loadedCaseRef.current = caseId;
            setLoadProgress(100);
            setLoading(false);
            return;
        }

        // Start new loading
        loadingRef.current = true;
        lastProgressRef.current = 0;
        setLoading(true);
        setLoadProgress(0);
        setError(null);
        imageDataCache.current.clear();

        // Create and store promise
        const loadPromise = (async () => {
            try {
                console.log('[VolumeViewer] Loading CT volume for case:', caseId);

                const volumeResult = await ctApi.getVolumeBinary(caseId, (loaded, total) => {
                    const progress = Math.round((loaded / total) * 80);
                    if (progress - lastProgressRef.current >= 5) {
                        lastProgressRef.current = progress;
                        setLoadProgress(progress);
                    }
                });

                console.log('[VolumeViewer] Volume loaded, shape:', volumeResult.shape);

                const volumeData: VolumeData = {
                    data: volumeResult.data,
                    shape: volumeResult.shape,
                    spacing: volumeResult.spacing,
                };

                // Store in global cache
                globalVolumeCache.set(caseId, volumeData);
                setVolume(volumeData);

                setCrosshair({
                    x: Math.floor(volumeResult.shape[0] / 2),
                    y: Math.floor(volumeResult.shape[1] / 2),
                    z: Math.floor(volumeResult.shape[2] / 2),
                });

                // Try to load mask
                try {
                    lastProgressRef.current = 80;
                    setLoadProgress(85);
                    const maskResult = await maskApi.getMaskVolumeBinary(caseId, (loaded, total) => {
                        const progress = 80 + Math.round((loaded / total) * 20);
                        if (progress - lastProgressRef.current >= 5) {
                            lastProgressRef.current = progress;
                            setLoadProgress(progress);
                        }
                    });

                    if (maskResult) {
                        const maskData: MaskData = {
                            data: maskResult.data,
                            shape: maskResult.shape,
                        };
                        globalMaskCache.set(caseId, maskData);
                        setMask(maskData);
                        console.log('[VolumeViewer] Mask loaded');
                    }
                } catch {
                    console.log('[VolumeViewer] No mask available');
                }

                setLoadProgress(100);
                loadedCaseRef.current = caseId;
            } catch (e) {
                console.error('[VolumeViewer] Failed to load volume:', e);
                setError(e instanceof Error ? e.message : 'Failed to load volume');
            } finally {
                loadingRef.current = false;
                setLoading(false);
                globalLoadingPromises.delete(caseId);
            }
        })();

        globalLoadingPromises.set(caseId, loadPromise);
        await loadPromise;
    }, [caseId]);

    // Auto-load on caseId change
    useEffect(() => {
        if (caseId) {
            loadVolume();
        }
    }, [caseId, loadVolume]);

    /**
     * Get dimensions for a specific view
     */
    const getViewDimensions = useCallback((view: MPRView): { width: number; height: number; maxSlice: number } | null => {
        if (!volume) return null;

        const [dimX, dimY, dimZ] = volume.shape;

        switch (view) {
            case 'AXIAL':
                return { width: dimX, height: dimY, maxSlice: dimZ };
            case 'CORONAL':
                return { width: dimX, height: dimZ, maxSlice: dimY };
            case 'SAGITTAL':
                return { width: dimY, height: dimZ, maxSlice: dimX };
            default:
                return null;
        }
    }, [volume]);

    /**
     * Render slice directly to ImageData (NO base64 encoding!)
     * This is the key performance optimization
     */
    const renderSliceToImageData = useCallback((
        view: MPRView,
        index: number,
        preset: WindowPresetKey = windowPreset
    ): ImageData | null => {
        if (!volume) return null;

        // Check cache
        const cacheKey = `${view}_${index}_${preset}`;
        const cached = imageDataCache.current.get(cacheKey);
        if (cached) return cached;

        const dims = getViewDimensions(view);
        if (!dims) return null;

        const { width, height } = dims;
        const [dimX, dimY, dimZ] = volume.shape;
        const data = volume.data;

        const { windowLevel, windowWidth } = WINDOW_PRESETS[preset];
        const minHU = windowLevel - windowWidth / 2;
        const invRange = 255 / windowWidth;

        // Create ImageData
        const imageData = new ImageData(width, height);
        const pixels = imageData.data;

        // Extract and render slice based on view
        // IMPORTANT: Numpy uses C order (row-major), so for shape (dimX, dimY, dimZ):
        // index[x,y,z] = x * dimY * dimZ + y * dimZ + z
        const strideX = dimY * dimZ;
        const strideY = dimZ;

        switch (view) {
            case 'AXIAL': {
                // Axial: slice at Z=index, showing X-Y plane
                if (index < 0 || index >= dimZ) return null;
                for (let y = 0; y < dimY; y++) {
                    for (let x = 0; x < dimX; x++) {
                        const srcIdx = x * strideX + y * strideY + index;
                        const hu = data[srcIdx];
                        let val = (hu - minHU) * invRange;
                        val = val < 0 ? 0 : val > 255 ? 255 : val;

                        const dstIdx = (x + y * width) << 2;
                        pixels[dstIdx] = val;
                        pixels[dstIdx + 1] = val;
                        pixels[dstIdx + 2] = val;
                        pixels[dstIdx + 3] = 255;
                    }
                }
                break;
            }

            case 'CORONAL': {
                // Coronal: slice at Y=index, showing X-Z plane
                if (index < 0 || index >= dimY) return null;
                for (let z = 0; z < dimZ; z++) {
                    for (let x = 0; x < dimX; x++) {
                        const srcIdx = x * strideX + index * strideY + z;
                        const hu = data[srcIdx];
                        let val = (hu - minHU) * invRange;
                        val = val < 0 ? 0 : val > 255 ? 255 : val;

                        // Flip Z for display (superior at top)
                        const dstIdx = (x + (dimZ - 1 - z) * width) << 2;
                        pixels[dstIdx] = val;
                        pixels[dstIdx + 1] = val;
                        pixels[dstIdx + 2] = val;
                        pixels[dstIdx + 3] = 255;
                    }
                }
                break;
            }

            case 'SAGITTAL': {
                // Sagittal: slice at X=index, showing Y-Z plane
                if (index < 0 || index >= dimX) return null;
                for (let z = 0; z < dimZ; z++) {
                    for (let y = 0; y < dimY; y++) {
                        const srcIdx = index * strideX + y * strideY + z;
                        const hu = data[srcIdx];
                        let val = (hu - minHU) * invRange;
                        val = val < 0 ? 0 : val > 255 ? 255 : val;

                        // Flip Z for display
                        const dstIdx = (y + (dimZ - 1 - z) * width) << 2;
                        pixels[dstIdx] = val;
                        pixels[dstIdx + 1] = val;
                        pixels[dstIdx + 2] = val;
                        pixels[dstIdx + 3] = 255;
                    }
                }
                break;
            }
        }

        // Cache result
        imageDataCache.current.set(cacheKey, imageData);

        // Limit cache size - each 512x512 ImageData is ~1MB
        // Keep max 300 items (~300MB) to prevent memory issues
        if (imageDataCache.current.size > 300) {
            // Remove oldest 50 items to free memory
            const keysToDelete = Array.from(imageDataCache.current.keys()).slice(0, 50);
            keysToDelete.forEach(key => imageDataCache.current.delete(key));
        }

        return imageData;
    }, [volume, getViewDimensions, windowPreset]);

    /**
     * Render slice with custom window level/width (for real-time manual adjustment)
     * Does NOT use caching to ensure immediate updates
     */
    const renderSliceWithCustomWindow = useCallback((
        view: MPRView,
        index: number,
        windowLevel: number,
        windowWidth: number
    ): ImageData | null => {
        if (!volume) return null;

        const dims = getViewDimensions(view);
        if (!dims) return null;

        const { width, height } = dims;
        const [dimX, dimY, dimZ] = volume.shape;
        const data = volume.data;

        const minHU = windowLevel - windowWidth / 2;
        const invRange = 255 / windowWidth;

        const imageData = new ImageData(width, height);
        const pixels = imageData.data;

        const strideX = dimY * dimZ;
        const strideY = dimZ;

        switch (view) {
            case 'AXIAL': {
                if (index < 0 || index >= dimZ) return null;
                for (let y = 0; y < dimY; y++) {
                    for (let x = 0; x < dimX; x++) {
                        const srcIdx = x * strideX + y * strideY + index;
                        const hu = data[srcIdx];
                        let val = (hu - minHU) * invRange;
                        val = val < 0 ? 0 : val > 255 ? 255 : val;

                        const dstIdx = (x + y * width) << 2;
                        pixels[dstIdx] = val;
                        pixels[dstIdx + 1] = val;
                        pixels[dstIdx + 2] = val;
                        pixels[dstIdx + 3] = 255;
                    }
                }
                break;
            }

            case 'CORONAL': {
                if (index < 0 || index >= dimY) return null;
                for (let z = 0; z < dimZ; z++) {
                    for (let x = 0; x < dimX; x++) {
                        const srcIdx = x * strideX + index * strideY + z;
                        const hu = data[srcIdx];
                        let val = (hu - minHU) * invRange;
                        val = val < 0 ? 0 : val > 255 ? 255 : val;

                        const dstIdx = (x + (dimZ - 1 - z) * width) << 2;
                        pixels[dstIdx] = val;
                        pixels[dstIdx + 1] = val;
                        pixels[dstIdx + 2] = val;
                        pixels[dstIdx + 3] = 255;
                    }
                }
                break;
            }

            case 'SAGITTAL': {
                if (index < 0 || index >= dimX) return null;
                for (let z = 0; z < dimZ; z++) {
                    for (let y = 0; y < dimY; y++) {
                        const srcIdx = index * strideX + y * strideY + z;
                        const hu = data[srcIdx];
                        let val = (hu - minHU) * invRange;
                        val = val < 0 ? 0 : val > 255 ? 255 : val;

                        const dstIdx = (y + (dimZ - 1 - z) * width) << 2;
                        pixels[dstIdx] = val;
                        pixels[dstIdx + 1] = val;
                        pixels[dstIdx + 2] = val;
                        pixels[dstIdx + 3] = 255;
                    }
                }
                break;
            }
        }

        return imageData;
    }, [volume, getViewDimensions]);

    /**
     * Render mask slice to ImageData
     */
    const renderMaskSliceToImageData = useCallback((
        view: MPRView,
        index: number
    ): ImageData | null => {
        if (!mask) return null;

        const dims = getViewDimensions(view);
        if (!dims) return null;

        const { width, height } = dims;
        const [dimX, dimY, dimZ] = mask.shape;
        const data = mask.data;

        const imageData = new ImageData(width, height);
        const pixels = imageData.data;

        switch (view) {
            case 'AXIAL': {
                if (index < 0 || index >= dimZ) return null;
                for (let y = 0; y < dimY; y++) {
                    for (let x = 0; x < dimX; x++) {
                        const srcIdx = x + y * dimX + index * dimX * dimY;
                        const dstIdx = (x + y * width) << 2;
                        if (data[srcIdx] > 0) {
                            pixels[dstIdx] = 239;     // R
                            pixels[dstIdx + 1] = 68;  // G
                            pixels[dstIdx + 2] = 68;  // B
                            pixels[dstIdx + 3] = 200;
                        }
                    }
                }
                break;
            }

            case 'CORONAL': {
                if (index < 0 || index >= dimY) return null;
                for (let z = 0; z < dimZ; z++) {
                    for (let x = 0; x < dimX; x++) {
                        const srcIdx = x + index * dimX + z * dimX * dimY;
                        const dstIdx = (x + (dimZ - 1 - z) * width) << 2;
                        if (data[srcIdx] > 0) {
                            pixels[dstIdx] = 239;
                            pixels[dstIdx + 1] = 68;
                            pixels[dstIdx + 2] = 68;
                            pixels[dstIdx + 3] = 200;
                        }
                    }
                }
                break;
            }

            case 'SAGITTAL': {
                if (index < 0 || index >= dimX) return null;
                for (let z = 0; z < dimZ; z++) {
                    for (let y = 0; y < dimY; y++) {
                        const srcIdx = index + y * dimX + z * dimX * dimY;
                        const dstIdx = (y + (dimZ - 1 - z) * width) << 2;
                        if (data[srcIdx] > 0) {
                            pixels[dstIdx] = 239;
                            pixels[dstIdx + 1] = 68;
                            pixels[dstIdx + 2] = 68;
                            pixels[dstIdx + 3] = 200;
                        }
                    }
                }
                break;
            }
        }

        return imageData;
    }, [mask, getViewDimensions]);

    /**
     * Get current slice index for a view based on crosshair
     */
    const getSliceIndex = useCallback((view: MPRView): number => {
        switch (view) {
            case 'AXIAL':
                return crosshair.z;
            case 'CORONAL':
                return crosshair.y;
            case 'SAGITTAL':
                return crosshair.x;
            default:
                return 0;
        }
    }, [crosshair]);

    /**
     * Update crosshair from a specific view
     */
    const updateCrosshair = useCallback((view: MPRView, sliceIndex: number) => {
        setCrosshair(prev => {
            switch (view) {
                case 'AXIAL':
                    return { ...prev, z: sliceIndex };
                case 'CORONAL':
                    return { ...prev, y: sliceIndex };
                case 'SAGITTAL':
                    return { ...prev, x: sliceIndex };
                default:
                    return prev;
            }
        });
    }, []);

    /**
     * Handle scroll in a specific view
     */
    const handleScroll = useCallback((view: MPRView, delta: number) => {
        const dims = getViewDimensions(view);
        if (!dims) return;

        setCrosshair(prev => {
            let newIndex: number;
            switch (view) {
                case 'AXIAL':
                    newIndex = Math.max(0, Math.min(dims.maxSlice - 1, prev.z - delta));
                    return { ...prev, z: newIndex };
                case 'CORONAL':
                    newIndex = Math.max(0, Math.min(dims.maxSlice - 1, prev.y - delta));
                    return { ...prev, y: newIndex };
                case 'SAGITTAL':
                    newIndex = Math.max(0, Math.min(dims.maxSlice - 1, prev.x - delta));
                    return { ...prev, x: newIndex };
                default:
                    return prev;
            }
        });
    }, [getViewDimensions]);

    /**
     * Pre-render adjacent slices for smoother scrolling
     * Reduced range to prevent performance issues
     */
    const prerenderAdjacent = useCallback((view: MPRView, currentIndex: number, preset: WindowPresetKey) => {
        const dims = getViewDimensions(view);
        if (!dims) return;

        // Only pre-render 3 slices ahead/behind (reduced from 10)
        const PRERENDER_RANGE = 3;

        const task = () => {
            for (let offset = 1; offset <= PRERENDER_RANGE; offset++) {
                const forwardIdx = currentIndex + offset;
                if (forwardIdx < dims.maxSlice) {
                    const cacheKey = `${view}_${forwardIdx}_${preset}`;
                    if (!imageDataCache.current.has(cacheKey)) {
                        renderSliceToImageData(view, forwardIdx, preset);
                    }
                }

                const backwardIdx = currentIndex - offset;
                if (backwardIdx >= 0) {
                    const cacheKey = `${view}_${backwardIdx}_${preset}`;
                    if (!imageDataCache.current.has(cacheKey)) {
                        renderSliceToImageData(view, backwardIdx, preset);
                    }
                }
            }
        };

        // Use requestIdleCallback with longer timeout to avoid blocking UI
        if ('requestIdleCallback' in window) {
            (window as Window).requestIdleCallback(task, { timeout: 100 });
        } else {
            setTimeout(task, 16); // ~1 frame
        }
    }, [getViewDimensions, renderSliceToImageData]);

    // Pre-render adjacent slices when crosshair changes
    useEffect(() => {
        if (!volume) return;

        prerenderAdjacent('AXIAL', crosshair.z, windowPreset);
        prerenderAdjacent('CORONAL', crosshair.y, windowPreset);
        prerenderAdjacent('SAGITTAL', crosshair.x, windowPreset);
    }, [crosshair, windowPreset, volume, prerenderAdjacent]);

    // Computed values
    const isLoaded = volume !== null;
    const hasMask = mask !== null;

    return {
        // State
        volume,
        mask,
        loading,
        loadProgress,
        error,
        isLoaded,
        hasMask,

        // View settings
        windowPreset,
        setWindowPreset,
        showMask,
        setShowMask,
        maskOpacity,
        setMaskOpacity,

        // Crosshair for MPR sync
        crosshair,
        setCrosshair,
        updateCrosshair,

        // Methods
        loadVolume,
        getViewDimensions,
        getSliceIndex,
        handleScroll,

        // Direct ImageData rendering (NO base64!)
        renderSliceToImageData,
        renderSliceWithCustomWindow,
        renderMaskSliceToImageData,
    };
}
