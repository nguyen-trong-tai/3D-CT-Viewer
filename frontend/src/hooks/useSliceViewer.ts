import { useState, useCallback, useRef, useEffect } from 'react';
import { ctApi, maskApi } from '../services/api';
import type { SliceData, MaskSliceData } from '../services/api';
import { WINDOW_PRESETS, type WindowPresetKey } from '../types';

/**
 * LRU Cache for slice data
 * Prevents redundant API calls while managing memory
 */
class LRUCache<T> {
    private cache = new Map<string, T>();
    private maxSize: number;

    constructor(maxSize = 100) {
        this.maxSize = maxSize;
    }

    get(key: string): T | undefined {
        const value = this.cache.get(key);
        if (value !== undefined) {
            // Move to end (most recently used)
            this.cache.delete(key);
            this.cache.set(key, value);
        }
        return value;
    }

    set(key: string, value: T): void {
        if (this.cache.has(key)) {
            this.cache.delete(key);
        } else if (this.cache.size >= this.maxSize) {
            // Delete oldest entry
            const firstKey = this.cache.keys().next().value;
            if (firstKey) this.cache.delete(firstKey);
        }
        this.cache.set(key, value);
    }

    has(key: string): boolean {
        return this.cache.has(key);
    }

    clear(): void {
        this.cache.clear();
    }
}

// Global caches (persist across component remounts)
const ctCache = new LRUCache<SliceData>(150);
const maskCache = new LRUCache<MaskSliceData | null>(150);

// Reusable canvas for image generation
const offscreenCanvas = document.createElement('canvas');
const offscreenCtx = offscreenCanvas.getContext('2d', { willReadFrequently: true });

/**
 * Hook for managing CT slice viewing with optimized caching and rendering
 */
export function useSliceViewer(caseId: string, totalSlices: number) {
    const [currentSlice, setCurrentSlice] = useState(0);
    const [loading, setLoading] = useState(false);
    const [imageUrl, setImageUrl] = useState<string>('');
    const [maskUrl, setMaskUrl] = useState<string>('');
    const [windowPreset, setWindowPreset] = useState<WindowPresetKey>('SOFT_TISSUE');
    const [showMask, setShowMask] = useState(false);
    const [maskOpacity, setMaskOpacity] = useState(0.5);

    const imageCache = useRef(new Map<string, string>()); // Cache rendered images

    /**
     * Convert HU values to grayscale image using window/level
     * Uses canvas API for fast rendering
     */
    const huToImageUrl = useCallback((huMatrix: number[][], preset: WindowPresetKey): string => {
        const height = huMatrix.length;
        const width = huMatrix[0]?.length || 0;
        if (width === 0 || height === 0) return '';

        const { windowLevel, windowWidth } = WINDOW_PRESETS[preset];
        const minHU = windowLevel - windowWidth / 2;
        const maxHU = windowLevel + windowWidth / 2;
        const range = maxHU - minHU;

        // Resize canvas if needed
        if (offscreenCanvas.width !== width || offscreenCanvas.height !== height) {
            offscreenCanvas.width = width;
            offscreenCanvas.height = height;
        }

        if (!offscreenCtx) return '';

        const imageData = offscreenCtx.createImageData(width, height);
        const data = imageData.data;

        let idx = 0;
        for (let y = 0; y < height; y++) {
            const row = huMatrix[y];
            for (let x = 0; x < width; x++) {
                const hu = row[x];
                // Clamp and normalize to 0-255
                let val = ((hu - minHU) / range) * 255;
                val = val < 0 ? 0 : val > 255 ? 255 : val;

                data[idx] = val;     // R
                data[idx + 1] = val; // G
                data[idx + 2] = val; // B
                data[idx + 3] = 255; // A
                idx += 4;
            }
        }

        offscreenCtx.putImageData(imageData, 0, 0);
        return offscreenCanvas.toDataURL('image/png');
    }, []);

    /**
     * Convert mask to colored overlay image
     */
    const maskToImageUrl = useCallback((maskMatrix: number[][]): string => {
        const height = maskMatrix.length;
        const width = maskMatrix[0]?.length || 0;
        if (width === 0 || height === 0) return '';

        if (offscreenCanvas.width !== width || offscreenCanvas.height !== height) {
            offscreenCanvas.width = width;
            offscreenCanvas.height = height;
        }

        if (!offscreenCtx) return '';

        const imageData = offscreenCtx.createImageData(width, height);
        const data = imageData.data;

        let idx = 0;
        for (let y = 0; y < height; y++) {
            const row = maskMatrix[y];
            for (let x = 0; x < width; x++) {
                const val = row[x];
                if (val > 0) {
                    // Tumor color (red)
                    data[idx] = 239;     // R
                    data[idx + 1] = 68;  // G
                    data[idx + 2] = 68;  // B
                    data[idx + 3] = 200; // A
                } else {
                    data[idx + 3] = 0; // Transparent
                }
                idx += 4;
            }
        }

        offscreenCtx.putImageData(imageData, 0, 0);
        return offscreenCanvas.toDataURL('image/png');
    }, []);

    /**
     * Fetch and cache slice data
     */
    const fetchSlice = useCallback(async (index: number): Promise<SliceData | null> => {
        const cacheKey = `${caseId}_${index}`;
        const cached = ctCache.get(cacheKey);
        if (cached) return cached;

        try {
            const data = await ctApi.getSlice(caseId, index);
            ctCache.set(cacheKey, data);
            return data;
        } catch (error) {
            console.error(`Failed to fetch slice ${index}:`, error);
            return null;
        }
    }, [caseId]);

    /**
     * Fetch and cache mask data
     */
    const fetchMask = useCallback(async (index: number): Promise<MaskSliceData | null> => {
        const cacheKey = `${caseId}_mask_${index}`;
        if (maskCache.has(cacheKey)) {
            return maskCache.get(cacheKey) || null;
        }

        try {
            const data = await maskApi.getMaskSlice(caseId, index);
            maskCache.set(cacheKey, data);
            return data;
        } catch {
            maskCache.set(cacheKey, null);
            return null;
        }
    }, [caseId]);

    /**
     * Prefetch adjacent slices for smooth scrolling
     */
    const prefetchAdjacent = useCallback((centerIndex: number, range = 5) => {
        for (let i = 1; i <= range; i++) {
            const prevIdx = centerIndex - i;
            const nextIdx = centerIndex + i;

            if (prevIdx >= 0 && !ctCache.has(`${caseId}_${prevIdx}`)) {
                fetchSlice(prevIdx);
            }
            if (nextIdx < totalSlices && !ctCache.has(`${caseId}_${nextIdx}`)) {
                fetchSlice(nextIdx);
            }

            if (showMask) {
                if (prevIdx >= 0) fetchMask(prevIdx);
                if (nextIdx < totalSlices) fetchMask(nextIdx);
            }
        }
    }, [caseId, totalSlices, fetchSlice, fetchMask, showMask]);

    /**
     * Load and render the current slice
     */
    const loadSlice = useCallback(async (index: number) => {
        setLoading(true);

        // Check image cache first (includes window preset)
        const imageCacheKey = `${caseId}_${index}_${windowPreset}`;
        const cachedImage = imageCache.current.get(imageCacheKey);
        if (cachedImage) {
            setImageUrl(cachedImage);
        }

        try {
            const sliceData = await fetchSlice(index);
            if (sliceData) {
                const url = huToImageUrl(sliceData.hu_values, windowPreset);
                setImageUrl(url);
                imageCache.current.set(imageCacheKey, url);
            }

            if (showMask) {
                const maskData = await fetchMask(index);
                if (maskData) {
                    setMaskUrl(maskToImageUrl(maskData.mask));
                } else {
                    setMaskUrl('');
                }
            } else {
                setMaskUrl('');
            }

            prefetchAdjacent(index);
        } finally {
            setLoading(false);
        }
    }, [caseId, windowPreset, showMask, fetchSlice, fetchMask, huToImageUrl, maskToImageUrl, prefetchAdjacent]);

    // Load slice when index or settings change
    useEffect(() => {
        loadSlice(currentSlice);
    }, [currentSlice, loadSlice]);

    // Regenerate image when window preset changes (use cached HU data)
    useEffect(() => {
        const cacheKey = `${caseId}_${currentSlice}`;
        const sliceData = ctCache.get(cacheKey);
        if (sliceData) {
            const url = huToImageUrl(sliceData.hu_values, windowPreset);
            setImageUrl(url);
        }
    }, [windowPreset, caseId, currentSlice, huToImageUrl]);

    /**
     * Navigate to specific slice
     */
    const goToSlice = useCallback((index: number) => {
        const clampedIndex = Math.max(0, Math.min(totalSlices - 1, index));
        setCurrentSlice(clampedIndex);
    }, [totalSlices]);

    /**
     * Handle scroll navigation
     */
    const handleScroll = useCallback((delta: number) => {
        setCurrentSlice((prev) => {
            const next = prev - delta; // Negative delta = scroll down = next slice
            return Math.max(0, Math.min(totalSlices - 1, next));
        });
    }, [totalSlices]);

    return {
        // State
        currentSlice,
        loading,
        imageUrl,
        maskUrl,
        windowPreset,
        showMask,
        maskOpacity,

        // Setters
        setWindowPreset,
        setShowMask,
        setMaskOpacity,
        goToSlice,
        handleScroll,

        // Computed
        totalSlices,
        progress: totalSlices > 0 ? ((currentSlice + 1) / totalSlices) * 100 : 0,
    };
}

/**
 * Hook for loading entire volume as binary data for GPU-ready performance
 * This is the recommended approach for near-zero latency slice navigation
 */
export function useVolumeBinaryLoader(caseId: string | null) {
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState(0);
    const [volume, setVolume] = useState<Int16Array | null>(null);
    const [shape, setShape] = useState<[number, number, number] | null>(null);
    const [spacing, setSpacing] = useState<[number, number, number] | null>(null);
    const [error, setError] = useState<string | null>(null);

    const loadVolume = useCallback(async () => {
        if (!caseId) return;

        setLoading(true);
        setProgress(0);
        setError(null);

        try {
            const result = await ctApi.getVolumeBinary(caseId, (loaded, total) => {
                setProgress(Math.round((loaded / total) * 100));
            });
            setVolume(result.data);
            setShape(result.shape);
            setSpacing(result.spacing);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load volume');
        } finally {
            setLoading(false);
        }
    }, [caseId]);

    /**
     * Extract a slice from the loaded volume
     * Volume is stored as (X, Y, Z) in row-major order
     */
    const getSlice = useCallback((sliceIndex: number): number[][] | null => {
        if (!volume || !shape) return null;

        const [dimX, dimY, dimZ] = shape;
        if (sliceIndex < 0 || sliceIndex >= dimZ) return null;

        const slice: number[][] = [];
        for (let y = 0; y < dimY; y++) {
            const row: number[] = [];
            for (let x = 0; x < dimX; x++) {
                // Index in flat array: x + y * dimX + z * dimX * dimY
                const idx = x + y * dimX + sliceIndex * dimX * dimY;
                row.push(volume[idx]);
            }
            slice.push(row);
        }

        return slice;
    }, [volume, shape]);

    return {
        loading,
        progress,
        volume,
        shape,
        spacing,
        error,
        loadVolume,
        getSlice,
        isLoaded: volume !== null,
    };
}

/**
 * Hook for loading mask volume as binary data
 */
export function useMaskBinaryLoader(caseId: string | null) {
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState(0);
    const [mask, setMask] = useState<Uint8Array | null>(null);
    const [shape, setShape] = useState<[number, number, number] | null>(null);
    const [error, setError] = useState<string | null>(null);

    const loadMask = useCallback(async () => {
        if (!caseId) return;

        setLoading(true);
        setProgress(0);
        setError(null);

        try {
            const result = await maskApi.getMaskVolumeBinary(caseId, (loaded, total) => {
                setProgress(Math.round((loaded / total) * 100));
            });

            if (result) {
                setMask(result.data);
                setShape(result.shape);
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load mask');
        } finally {
            setLoading(false);
        }
    }, [caseId]);

    /**
     * Extract a mask slice from the loaded volume
     */
    const getMaskSlice = useCallback((sliceIndex: number): number[][] | null => {
        if (!mask || !shape) return null;

        const [dimX, dimY, dimZ] = shape;
        if (sliceIndex < 0 || sliceIndex >= dimZ) return null;

        const slice: number[][] = [];
        for (let y = 0; y < dimY; y++) {
            const row: number[] = [];
            for (let x = 0; x < dimX; x++) {
                const idx = x + y * dimX + sliceIndex * dimX * dimY;
                row.push(mask[idx]);
            }
            slice.push(row);
        }

        return slice;
    }, [mask, shape]);

    return {
        loading,
        progress,
        mask,
        shape,
        error,
        loadMask,
        getMaskSlice,
        isLoaded: mask !== null,
    };
}
