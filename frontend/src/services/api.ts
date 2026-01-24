/**
 * API Service
 * 
 * Client-side API for the CT-based Medical Imaging & AI Research Platform.
 * Aligned with backend API v1 endpoints.
 */

import axios from 'axios';

// API base with versioned prefix
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_V1 = `${API_BASE}/api/v1`;

// =============================================================================
// Type Definitions (matching backend schemas)
// =============================================================================

export interface CaseResponse {
    case_id: string;
    status: string;
}

export interface StatusResponse {
    case_id: string;
    status: 'pending' | 'uploaded' | 'processing' | 'ready' | 'error';
    message?: string;
}

export interface ProcessingResponse {
    case_id: string;
    status: string;
    estimated_time_seconds?: number;
}

export interface VolumeShape {
    x: number;
    y: number;
    z: number;
}

export interface VoxelSpacing {
    x: number;
    y: number;
    z: number;
}

export interface CTMetadata {
    volume_shape: VolumeShape;
    voxel_spacing_mm: VoxelSpacing;
    num_slices: number;
    hu_range?: { min: number; max: number };
    orientation?: string;
}

export interface SliceData {
    slice_index: number;
    hu_values: number[][];
    spacing_mm: { x: number; y: number };
}

export interface MaskSliceData {
    slice_index: number;
    mask: number[][];
    sparse: boolean;
}

export interface ArtifactList {
    case_id: string;
    artifacts: Record<string, boolean>;
}

export interface PipelineStatus {
    case_id: string;
    overall_status: string;
    is_running: boolean;
    stages: Array<{
        name: string;
        status: string;
    }>;
    artifacts: Record<string, boolean>;
}

// =============================================================================
// Cases API - Upload and Processing
// =============================================================================

export const casesApi = {
    /**
     * Upload a single file (NIfTI or ZIP containing DICOM)
     */
    uploadCase: async (file: File): Promise<CaseResponse> => {
        const formData = new FormData();
        formData.append('file', file);
        const response = await axios.post(`${API_V1}/cases`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    },

    /**
     * Upload with progress tracking using XMLHttpRequest
     */
    uploadCaseWithProgress: async (
        file: File,
        onProgress: (percent: number) => void
    ): Promise<CaseResponse> => {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            const formData = new FormData();
            formData.append('file', file);

            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    onProgress(Math.round((e.loaded / e.total) * 100));
                }
            });

            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(JSON.parse(xhr.responseText));
                } else {
                    reject(new Error(`Upload failed: ${xhr.status}`));
                }
            });

            xhr.addEventListener('error', () => reject(new Error('Upload failed')));
            xhr.open('POST', `${API_V1}/cases`);
            xhr.send(formData);
        });
    },

    /**
     * Upload DICOM folder - optimized for multiple files
     * Single API request with progress tracking
     */
    uploadDicomFolder: async (
        files: File[],
        onProgress: (percent: number, label: string) => void,
        metadata?: Record<string, unknown>
    ): Promise<CaseResponse> => {
        return new Promise((resolve, reject) => {
            const startTime = performance.now();
            onProgress(0, `Preparing ${files.length} files...`);

            const xhr = new XMLHttpRequest();
            const formData = new FormData();

            // Filter and add DICOM files
            const dcmFiles = files.filter((f) => f.name.toLowerCase().endsWith('.dcm'));

            for (const file of dcmFiles) {
                formData.append('files', file, file.name);
            }

            // Add metadata if provided
            if (metadata && Object.keys(metadata).length > 0) {
                formData.append('metadata', JSON.stringify(metadata));
            }

            const prepTime = performance.now() - startTime;
            console.log(`FormData prepared in ${prepTime.toFixed(0)}ms for ${dcmFiles.length} files`);

            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    const sizeMB = (e.total / 1024 / 1024).toFixed(1);
                    onProgress(percent, `Uploading ${dcmFiles.length} files (${sizeMB}MB)...`);
                }
            });

            xhr.addEventListener('load', () => {
                const totalTime = performance.now() - startTime;
                console.log(`Total upload time: ${(totalTime / 1000).toFixed(2)}s`);

                if (xhr.status >= 200 && xhr.status < 300) {
                    onProgress(100, 'Upload complete!');
                    resolve(JSON.parse(xhr.responseText));
                } else {
                    reject(new Error(`Upload failed: ${xhr.status} - ${xhr.responseText}`));
                }
            });

            xhr.addEventListener('error', () => reject(new Error('Network error')));
            xhr.open('POST', `${API_V1}/cases/dicom`);
            xhr.send(formData);
        });
    },

    /**
     * Trigger processing pipeline
     */
    processCase: async (caseId: string): Promise<ProcessingResponse> => {
        const response = await axios.post(`${API_V1}/cases/${caseId}/process`);
        return response.data;
    },

    /**
     * Query processing status
     */
    getStatus: async (caseId: string): Promise<StatusResponse> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/status`);
        return response.data;
    },

    /**
     * Get detailed pipeline status
     */
    getPipelineStatus: async (caseId: string): Promise<PipelineStatus> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/pipeline`);
        return response.data;
    },

    /**
     * Delete a case
     */
    deleteCase: async (caseId: string): Promise<void> => {
        await axios.delete(`${API_V1}/cases/${caseId}`);
    },

    /**
     * List available artifacts
     */
    getArtifacts: async (caseId: string): Promise<ArtifactList> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/artifacts`);
        return response.data;
    },
};

// =============================================================================
// CT API - Volume and Slice Data
// =============================================================================

export const ctApi = {
    /**
     * Get CT metadata
     */
    getMetadata: async (caseId: string): Promise<CTMetadata> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/metadata`);
        return response.data;
    },

    /**
     * Fetch single slice (HU values as JSON)
     */
    getSlice: async (caseId: string, sliceIndex: number): Promise<SliceData> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/ct/slices/${sliceIndex}`);
        return response.data;
    },

    /**
     * Fetch entire volume as binary data for local caching
     * Returns Int16Array for GPU-ready performance
     * 
     * @param caseId - Case identifier
     * @param onProgress - Progress callback (loaded bytes, total bytes)
     * @returns Volume data with shape and dimensions
     */
    getVolumeBinary: async (
        caseId: string,
        onProgress?: (loaded: number, total: number) => void
    ): Promise<{
        data: Int16Array;
        shape: [number, number, number];
        spacing: [number, number, number];
    }> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/ct/volume`, {
            responseType: 'arraybuffer',
            onDownloadProgress: (event) => {
                if (onProgress && event.total) {
                    onProgress(event.loaded, event.total);
                }
            },
        });

        // Parse headers for metadata
        const shapeHeader = response.headers['x-volume-shape'];
        const spacingHeader = response.headers['x-volume-spacing'];

        const shape = shapeHeader ? JSON.parse(shapeHeader) : [0, 0, 0];
        const spacing = spacingHeader ? JSON.parse(spacingHeader) : [1, 1, 1];

        // Convert ArrayBuffer to Int16Array
        const data = new Int16Array(response.data);

        return {
            data,
            shape: shape as [number, number, number],
            spacing: spacing as [number, number, number],
        };
    },

    /**
     * Get optional extra metadata (patient info, study details, etc.)
     */
    getExtraMetadata: async (caseId: string): Promise<Record<string, unknown> | null> => {
        try {
            const response = await axios.get(`${API_V1}/cases/${caseId}/extra-metadata`);
            return response.data;
        } catch {
            return null;
        }
    },
};

// =============================================================================
// Mask API - Segmentation Data
// =============================================================================

export const maskApi = {
    /**
     * Fetch single segmentation mask slice
     */
    getMaskSlice: async (caseId: string, sliceIndex: number): Promise<MaskSliceData | null> => {
        try {
            const response = await axios.get(`${API_V1}/cases/${caseId}/mask/slices/${sliceIndex}`);
            return response.data;
        } catch (error) {
            if (axios.isAxiosError(error) && error.response?.status === 404) {
                return null;
            }
            throw error;
        }
    },

    /**
     * Fetch entire mask volume as binary data
     * Returns Uint8Array (0 or 1 per voxel)
     */
    getMaskVolumeBinary: async (
        caseId: string,
        onProgress?: (loaded: number, total: number) => void
    ): Promise<{
        data: Uint8Array;
        shape: [number, number, number];
    } | null> => {
        try {
            const response = await axios.get(`${API_V1}/cases/${caseId}/mask/volume`, {
                responseType: 'arraybuffer',
                onDownloadProgress: (event) => {
                    if (onProgress && event.total) {
                        onProgress(event.loaded, event.total);
                    }
                },
            });

            const shapeHeader = response.headers['x-volume-shape'];
            const shape = shapeHeader ? JSON.parse(shapeHeader) : [0, 0, 0];

            return {
                data: new Uint8Array(response.data),
                shape: shape as [number, number, number],
            };
        } catch (error) {
            if (axios.isAxiosError(error) && error.response?.status === 404) {
                return null;
            }
            throw error;
        }
    },
};

// =============================================================================
// Mesh API - 3D Reconstruction
// =============================================================================

export const meshApi = {
    /**
     * Get mesh URL for 3D viewer
     */
    getMeshUrl: (caseId: string): string => {
        return `${API_V1}/cases/${caseId}/mesh`;
    },

    /**
     * Check if mesh is available
     */
    checkMeshAvailable: async (caseId: string): Promise<boolean> => {
        try {
            await axios.head(`${API_V1}/cases/${caseId}/mesh`);
            return true;
        } catch {
            return false;
        }
    },
};

// =============================================================================
// Implicit Representation API (SDF)
// =============================================================================

export const implicitApi = {
    /**
     * Get implicit representation metadata
     */
    getImplicitInfo: async (caseId: string): Promise<{
        type: string;
        grid_aligned: boolean;
        level_set: number;
    }> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/implicit`);
        return response.data;
    },
};

// =============================================================================
// Health Check
// =============================================================================

export const healthApi = {
    /**
     * Check if backend is healthy
     */
    check: async (): Promise<{ status: string; version: string }> => {
        const response = await axios.get(`${API_V1}/health`);
        return response.data;
    },
};
