import React, { useEffect, useRef, useState, useCallback } from 'react';
import { ctApi, type SliceData } from '../../services/api/ct';
import { maskApi, type MaskSliceData } from '../../services/api/mask';
import { RangeSlider } from '../UI/Controls';

interface SliceViewerProps {
    caseId: string;
    totalSlices: number;
    currentIndex: number;
    onIndexChange: (index: number) => void;
    showSegmentation: boolean;
    segmentationOpacity: number;
    windowPreset: 'LUNG' | 'SOFT_TISSUE';
}

// Simple LRU Cache for slices
class SliceCache<T> {
    private cache = new Map<string, T>();
    private maxSize: number;

    constructor(maxSize: number = 50) {
        this.maxSize = maxSize;
    }

    get(key: string): T | undefined {
        const value = this.cache.get(key);
        if (value) {
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
            // Delete oldest (first) entry
            const firstKey = this.cache.keys().next().value;
            if (firstKey) this.cache.delete(firstKey);
        }
        this.cache.set(key, value);
    }

    clear(): void {
        this.cache.clear();
    }
}

// Global caches (persist across re-renders)
const ctSliceCache = new SliceCache<SliceData>(50);
const maskSliceCache = new SliceCache<MaskSliceData | null>(50);

export const SliceViewer: React.FC<SliceViewerProps> = ({
    caseId,
    totalSlices,
    currentIndex,
    onIndexChange,
    showSegmentation,
    segmentationOpacity,
    windowPreset
}) => {
    const [imageUrl, setImageUrl] = useState<string>('');
    const [maskUrl, setMaskUrl] = useState<string>('');
    const [loading, setLoading] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);
    const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const lastFetchedIndexRef = useRef<number>(-1);

    // Helper to Convert Raw HU 2D Array to Image URL
    const huToImageUrl = useCallback((huMatrix: number[][], preset: 'LUNG' | 'SOFT_TISSUE'): string => {
        const height = huMatrix.length;
        const width = huMatrix[0].length;

        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (!ctx) return '';

        const imageData = ctx.createImageData(width, height);
        const data = imageData.data;

        // Windowing Parameters
        let wl = 40;
        let ww = 400;

        if (preset === 'LUNG') {
            wl = -600;
            ww = 1500;
        }

        const minHu = wl - ww / 2;
        const maxHu = wl + ww / 2;

        let p = 0;
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const hu = huMatrix[y][x];
                let val = ((hu - minHu) / (maxHu - minHu)) * 255;
                val = Math.max(0, Math.min(255, val));

                data[p] = val;
                data[p + 1] = val;
                data[p + 2] = val;
                data[p + 3] = 255;
                p += 4;
            }
        }

        ctx.putImageData(imageData, 0, 0);
        return canvas.toDataURL();
    }, []);

    // Helper to Convert Mask 2D Array to Image URL
    const maskToImageUrl = useCallback((maskMatrix: number[][]): string => {
        const height = maskMatrix.length;
        const width = maskMatrix[0].length;

        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d');
        if (!ctx) return '';

        const imageData = ctx.createImageData(width, height);
        const data = imageData.data;

        let p = 0;
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const val = maskMatrix[y][x];
                if (val > 0) {
                    data[p] = 255;
                    data[p + 1] = 0;
                    data[p + 2] = 0;
                    data[p + 3] = 255;
                } else {
                    data[p + 3] = 0;
                }
                p += 4;
            }
        }

        ctx.putImageData(imageData, 0, 0);
        return canvas.toDataURL();
    }, []);

    // Fetch and cache a single slice
    const fetchSliceData = useCallback(async (index: number): Promise<SliceData | null> => {
        const cacheKey = `${caseId}_${index}`;
        const cached = ctSliceCache.get(cacheKey);
        if (cached) return cached;

        try {
            const data = await ctApi.getSlice(caseId, index);
            ctSliceCache.set(cacheKey, data);
            return data;
        } catch {
            return null;
        }
    }, [caseId]);

    // Fetch and cache mask slice
    const fetchMaskData = useCallback(async (index: number): Promise<MaskSliceData | null> => {
        const cacheKey = `${caseId}_mask_${index}`;
        const cached = maskSliceCache.get(cacheKey);
        if (cached !== undefined) return cached;

        try {
            const data = await maskApi.getMaskSlice(caseId, index);
            maskSliceCache.set(cacheKey, data);
            return data;
        } catch {
            maskSliceCache.set(cacheKey, null);
            return null;
        }
    }, [caseId]);

    // Prefetch adjacent slices
    const prefetchAdjacent = useCallback((centerIndex: number) => {
        const prefetchRange = 3; // Prefetch 3 slices in each direction
        for (let i = 1; i <= prefetchRange; i++) {
            if (centerIndex - i >= 0) fetchSliceData(centerIndex - i);
            if (centerIndex + i < totalSlices) fetchSliceData(centerIndex + i);
            if (showSegmentation) {
                if (centerIndex - i >= 0) fetchMaskData(centerIndex - i);
                if (centerIndex + i < totalSlices) fetchMaskData(centerIndex + i);
            }
        }
    }, [fetchSliceData, fetchMaskData, totalSlices, showSegmentation]);

    useEffect(() => {
        // Clear timer on new index change
        if (debounceTimerRef.current) {
            clearTimeout(debounceTimerRef.current);
        }

        // Debounce: Wait 100ms before fetching (allows rapid scrolling without flood)
        debounceTimerRef.current = setTimeout(async () => {
            // Skip if already fetched this index
            if (lastFetchedIndexRef.current === currentIndex) return;

            setLoading(true);

            try {
                // Fetch current slice
                const sliceData = await fetchSliceData(currentIndex);

                if (sliceData) {
                    const img = huToImageUrl(sliceData.hu_values, windowPreset);
                    setImageUrl(img);
                    lastFetchedIndexRef.current = currentIndex;
                }

                // Fetch mask if enabled
                if (showSegmentation) {
                    const maskData = await fetchMaskData(currentIndex);
                    if (maskData) {
                        const maskImg = maskToImageUrl(maskData.mask);
                        setMaskUrl(maskImg);
                    } else {
                        setMaskUrl('');
                    }
                } else {
                    setMaskUrl('');
                }

                // Prefetch adjacent slices in background
                prefetchAdjacent(currentIndex);

            } catch (err) {
                console.error("Failed to load slice", err);
            } finally {
                setLoading(false);
            }
        }, 100); // 100ms debounce

        return () => {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current);
            }
        };
    }, [caseId, currentIndex, showSegmentation, windowPreset, fetchSliceData, fetchMaskData, huToImageUrl, maskToImageUrl, prefetchAdjacent]);

    const handleWheel = (e: React.WheelEvent) => {
        const delta = Math.sign(e.deltaY) * -1; // Up is positive index
        const newIndex = Math.min(Math.max(0, currentIndex + delta), totalSlices - 1);
        onIndexChange(newIndex);
    };

    return (
        <div
            ref={containerRef}
            className="flex-center full-size"
            style={{ position: 'relative', overflow: 'hidden', backgroundColor: '#000' }}
            onWheel={handleWheel}
        >
            {/* Main CT Image */}
            {imageUrl && (
                <img
                    src={imageUrl}
                    alt={`Slice ${currentIndex}`}
                    style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'contain',
                        // Filter moved to canvas generation for raw data correcntess
                        transition: 'none' // remove transition for snappy scroll
                    }}
                />
            )}

            {/* Segmentation Overlay */}
            {imageUrl && showSegmentation && maskUrl && (
                <img
                    src={maskUrl}
                    alt="Segmentation"
                    style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: '100%',
                        objectFit: 'contain',
                        opacity: segmentationOpacity,
                        pointerEvents: 'none',
                        // Mix blend mode handled by color + alpha
                    }}
                />
            )}

            {/* Slice Indicator Overlay */}
            <div style={{ position: 'absolute', bottom: 20, left: '50%', transform: 'translateX(-50%)', width: '80%', maxWidth: '400px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div style={{ background: 'rgba(0,0,0,0.7)', padding: '8px 16px', borderRadius: '16px', backdropFilter: 'blur(4px)', marginBottom: '8px' }}>
                    <span style={{ fontSize: '0.9rem', fontFamily: 'monospace', color: 'var(--text-main)' }}>
                        Slice: {currentIndex + 1} / {totalSlices}
                    </span>
                </div>

                {/* We put a slider here too for direct access */}
                <div style={{ width: '100%' }} onWheel={(e) => e.stopPropagation()}>
                    <RangeSlider
                        min={0}
                        max={totalSlices - 1}
                        value={currentIndex}
                        onChange={(e) => onIndexChange(parseInt(e.target.value))}
                        step={1}
                    />
                </div>
            </div>

            {/* Loading State */}
            {loading && !imageUrl && (
                <div style={{ position: 'absolute', color: 'white' }}>Loading...</div>
            )}
        </div>
    );
};
