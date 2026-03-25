/**
 * API Service
 * 
 * Client-side API for the CT-based Medical Imaging & AI Research Platform.
 * Aligned with backend API v1 endpoints.
 */

import axios from 'axios';

// API base — empty string uses Vite proxy in dev, override with VITE_API_URL for production
const API_BASE = import.meta.env.VITE_API_URL || '';
const API_V1 = `${API_BASE}/api/v1`;
const DIRECT_DICOM_FILE_THRESHOLD = 96;
const DIRECT_DICOM_SIZE_THRESHOLD_BYTES = 32 * 1024 * 1024;
const DICOM_BATCH_FILE_LIMIT = 128;
const DICOM_BATCH_TARGET_BYTES = 48 * 1024 * 1024;
const DEFAULT_DIRECT_UPLOAD_CONCURRENCY = 4;

// Type Definitions (matching backend schemas)

export interface CaseResponse {
    case_id: string;
    status: string;
}

export interface StatusResponse {
    case_id: string;
    status: 'pending' | 'uploading' | 'uploaded' | 'processing' | 'ready' | 'error';
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
    preview_available?: boolean;
    preview_volume_shape?: VolumeShape;
    preview_voxel_spacing_mm?: VoxelSpacing;
    preview_mask_available?: boolean;
}

export interface ArtifactUrlResponse {
    case_id: string;
    artifact: string;
    url: string;
    expires_in_seconds: number;
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

interface BatchUploadProgress {
    case_id: string;
    files_saved: number;
    total_received: number;
}

interface BatchInitResponse extends CaseResponse {
    storage_kind: 'object_store' | 'local_dir';
    direct_upload_enabled?: boolean;
    upload_url_ttl_seconds?: number | null;
    recommended_upload_concurrency?: number | null;
}

interface BatchUploadFileDescriptor {
    client_id: string;
    filename: string;
    size_bytes: number;
    content_type?: string;
}

interface BatchUploadTarget {
    client_id: string;
    filename: string;
    object_key: string;
    upload_url: string;
    method: string;
}

interface BatchUploadPresignResponse {
    case_id: string;
    expires_in_seconds: number;
    targets: BatchUploadTarget[];
}

interface BatchUploadCompleteItem {
    client_id: string;
    filename: string;
    object_key: string;
}

interface UploadChunk {
    files: File[];
    totalBytes: number;
}

type BinaryVolumePayload = {
    data: Int16Array;
    shape: [number, number, number];
    spacing: [number, number, number];
};

type BinaryMaskPayload = {
    data: Uint8Array;
    shape: [number, number, number];
};

const metadataCache = new Map<string, CTMetadata>();

const createUploadChunks = (files: File[]): UploadChunk[] => {
    const chunks: UploadChunk[] = [];
    let currentFiles: File[] = [];
    let currentBytes = 0;

    for (const file of files) {
        const nextWouldOverflowCount = currentFiles.length >= DICOM_BATCH_FILE_LIMIT;
        const nextWouldOverflowBytes =
            currentFiles.length > 0 && currentBytes + file.size > DICOM_BATCH_TARGET_BYTES;

        if (nextWouldOverflowCount || nextWouldOverflowBytes) {
            chunks.push({ files: currentFiles, totalBytes: currentBytes });
            currentFiles = [];
            currentBytes = 0;
        }

        currentFiles.push(file);
        currentBytes += file.size;
    }

    if (currentFiles.length > 0) {
        chunks.push({ files: currentFiles, totalBytes: currentBytes });
    }

    return chunks;
};

const postFormDataWithProgress = <T>(
    url: string,
    formData: FormData,
    onProgress?: (loaded: number, total: number) => void
): Promise<T> => {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();

        if (onProgress) {
            xhr.upload.addEventListener('progress', (event) => {
                if (event.lengthComputable) {
                    onProgress(event.loaded, event.total);
                }
            });
        }

        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                resolve(JSON.parse(xhr.responseText) as T);
            } else {
                reject(new Error(`Upload failed: ${xhr.status} - ${xhr.responseText}`));
            }
        });

        xhr.addEventListener('error', () => reject(new Error('Network error')));
        xhr.open('POST', url);
        xhr.send(formData);
    });
};

const uploadFileToPresignedUrl = (
    url: string,
    file: File,
    method = 'PUT',
    onProgress?: (loaded: number, total: number) => void
): Promise<void> => {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();

        if (onProgress) {
            xhr.upload.addEventListener('progress', (event) => {
                if (event.lengthComputable) {
                    onProgress(event.loaded, event.total);
                }
            });
        }

        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                resolve();
            } else {
                reject(new Error(`Direct upload failed: ${xhr.status} - ${xhr.responseText}`));
            }
        });

        xhr.addEventListener('error', () => {
            reject(new Error('Direct upload failed. Verify object-store CORS settings.'));
        });

        xhr.open(method, url);
        xhr.send(file);
    });
};

const runWithConcurrency = async <T>(
    tasks: Array<() => Promise<T>>,
    concurrency: number
): Promise<T[]> => {
    if (tasks.length === 0) {
        return [];
    }

    const results = new Array<T>(tasks.length);
    let nextIndex = 0;
    const workerCount = Math.max(1, Math.min(concurrency, tasks.length));

    const worker = async () => {
        while (nextIndex < tasks.length) {
            const currentIndex = nextIndex;
            nextIndex += 1;
            results[currentIndex] = await tasks[currentIndex]();
        }
    };

    await Promise.all(Array.from({ length: workerCount }, () => worker()));
    return results;
};

const spacingToTuple = (spacing: VoxelSpacing): [number, number, number] => [
    spacing.x,
    spacing.y,
    spacing.z,
];

const fetchArtifactUrl = async (url: string): Promise<string | null> => {
    try {
        const response = await axios.get<ArtifactUrlResponse>(url);
        return response.data.url;
    } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 404) {
            return null;
        }
        throw error;
    }
};

const fetchArrayBuffer = async (
    url: string,
    onProgress?: (loaded: number, total: number) => void
): Promise<ArrayBuffer> => {
    const response = await axios.get<ArrayBuffer>(url, {
        responseType: 'arraybuffer',
        onDownloadProgress: (event) => {
            if (onProgress && event.total) {
                onProgress(event.loaded, event.total);
            }
        },
    });
    return response.data;
};

const parseNpyHeaderShape = (headerText: string): [number, number, number] => {
    const shapeMatch = headerText.match(/'shape':\s*\(([^)]*)\)/);
    if (!shapeMatch) {
        throw new Error('NPY header is missing shape');
    }

    const dims = shapeMatch[1]
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
        .map((value) => Number.parseInt(value, 10));

    if (dims.length !== 3 || dims.some((value) => Number.isNaN(value))) {
        throw new Error(`Unsupported NPY shape: ${shapeMatch[1]}`);
    }

    return dims as [number, number, number];
};

const parseNpyArrayBuffer = (buffer: ArrayBuffer): { data: Int16Array | Uint8Array; shape: [number, number, number] } => {
    const view = new DataView(buffer);
    const magic = new Uint8Array(buffer, 0, 6);
    const expectedMagic = [0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59];
    if (!expectedMagic.every((value, index) => magic[index] === value)) {
        throw new Error('Unsupported file format: expected NPY');
    }

    const major = view.getUint8(6);
    const headerLength = major <= 1 ? view.getUint16(8, true) : view.getUint32(8, true);
    const headerOffset = major <= 1 ? 10 : 12;
    const headerText = new TextDecoder().decode(
        new Uint8Array(buffer, headerOffset, headerLength)
    );

    const descrMatch = headerText.match(/'descr':\s*'([^']+)'/);
    if (!descrMatch) {
        throw new Error('NPY header is missing dtype');
    }

    const shape = parseNpyHeaderShape(headerText);
    const dataOffset = headerOffset + headerLength;
    const rawData = buffer.slice(dataOffset);

    switch (descrMatch[1]) {
        case '<i2':
        case '|i2':
            return { data: new Int16Array(rawData), shape };
        case '|u1':
        case '<u1':
            return { data: new Uint8Array(rawData), shape };
        default:
            throw new Error(`Unsupported NPY dtype: ${descrMatch[1]}`);
    }
};

const fetchNpyVolume = async (
    url: string,
    spacing: [number, number, number],
    onProgress?: (loaded: number, total: number) => void
): Promise<BinaryVolumePayload> => {
    const parsed = parseNpyArrayBuffer(await fetchArrayBuffer(url, onProgress));
    if (!(parsed.data instanceof Int16Array)) {
        throw new Error('Expected int16 CT volume data');
    }

    return {
        data: parsed.data,
        shape: parsed.shape,
        spacing,
    };
};

const fetchNpyMask = async (
    url: string,
    onProgress?: (loaded: number, total: number) => void
): Promise<BinaryMaskPayload> => {
    const parsed = parseNpyArrayBuffer(await fetchArrayBuffer(url, onProgress));
    if (!(parsed.data instanceof Uint8Array)) {
        throw new Error('Expected uint8 mask data');
    }

    return {
        data: parsed.data,
        shape: parsed.shape,
    };
};

const fetchRawVolumeFromApi = async (
    url: string,
    onProgress?: (loaded: number, total: number) => void
): Promise<BinaryVolumePayload> => {
    const response = await axios.get(url, {
        responseType: 'arraybuffer',
        onDownloadProgress: (event) => {
            if (onProgress && event.total) {
                onProgress(event.loaded, event.total);
            }
        },
    });

    const shapeHeader = response.headers['x-volume-shape'];
    const spacingHeader = response.headers['x-volume-spacing'];

    return {
        data: new Int16Array(response.data),
        shape: (shapeHeader ? JSON.parse(shapeHeader) : [0, 0, 0]) as [number, number, number],
        spacing: (spacingHeader ? JSON.parse(spacingHeader) : [1, 1, 1]) as [number, number, number],
    };
};

const fetchRawMaskFromApi = async (
    url: string,
    onProgress?: (loaded: number, total: number) => void
): Promise<BinaryMaskPayload | null> => {
    try {
        const response = await axios.get(url, {
            responseType: 'arraybuffer',
            onDownloadProgress: (event) => {
                if (onProgress && event.total) {
                    onProgress(event.loaded, event.total);
                }
            },
        });

        const shapeHeader = response.headers['x-volume-shape'];
        return {
            data: new Uint8Array(response.data),
            shape: (shapeHeader ? JSON.parse(shapeHeader) : [0, 0, 0]) as [number, number, number],
        };
    } catch (error) {
        if (axios.isAxiosError(error) && error.response?.status === 404) {
            return null;
        }
        throw error;
    }
};

const uploadBatchChunkDirect = async (
    caseId: string,
    chunk: UploadChunk,
    chunkIndex: number,
    chunkCount: number,
    totalFileCount: number,
    totalBytes: number,
    uploadedBytes: number,
    onProgress: (percent: number, label: string) => void,
    concurrency: number
): Promise<void> => {
    const descriptors: BatchUploadFileDescriptor[] = chunk.files.map((file, fileIndex) => ({
        client_id: `${chunkIndex}-${fileIndex}-${file.name}-${file.size}-${file.lastModified}`,
        filename: file.name,
        size_bytes: file.size,
        content_type: file.type || undefined,
    }));

    const presignResponse = await axios.post<BatchUploadPresignResponse>(
        `${API_V1}/cases/batch/${caseId}/files/presign`,
        { files: descriptors }
    );

    const targetsByClientId = new Map(
        presignResponse.data.targets.map((target) => [target.client_id, target])
    );
    const progressByClientId = new Map<string, number>();
    const totalSizeMB = (totalBytes / 1024 / 1024).toFixed(1);

    const completedUploads = await runWithConcurrency(
        descriptors.map((descriptor, descriptorIndex) => async (): Promise<BatchUploadCompleteItem> => {
            const file = chunk.files[descriptorIndex];
            const target = targetsByClientId.get(descriptor.client_id);
            if (!target) {
                throw new Error(`Missing upload target for ${descriptor.filename}`);
            }

            await uploadFileToPresignedUrl(target.upload_url, file, target.method, (loaded) => {
                progressByClientId.set(descriptor.client_id, loaded);
                let chunkLoaded = 0;
                for (const value of progressByClientId.values()) {
                    chunkLoaded += value;
                }
                const overallLoaded = uploadedBytes + chunkLoaded;
                const percent = totalBytes > 0 ? Math.round((overallLoaded / totalBytes) * 100) : 100;
                onProgress(
                    percent,
                    `Uploading directly to cloud ${chunkIndex + 1}/${chunkCount} (${totalFileCount} files, ${totalSizeMB}MB)...`
                );
            });

            progressByClientId.set(descriptor.client_id, file.size);
            return {
                client_id: descriptor.client_id,
                filename: descriptor.filename,
                object_key: target.object_key,
            };
        }),
        concurrency
    );

    await axios.post<BatchUploadProgress>(
        `${API_V1}/cases/batch/${caseId}/files/complete`,
        { uploads: completedUploads }
    );
};

const uploadBatchChunkViaApi = async (
    caseId: string,
    chunk: UploadChunk,
    chunkIndex: number,
    chunkCount: number,
    totalFileCount: number,
    totalBytes: number,
    uploadedBytes: number,
    onProgress: (percent: number, label: string) => void
): Promise<void> => {
    const chunkFormData = new FormData();
    for (const file of chunk.files) {
        chunkFormData.append('files', file, file.name);
    }

    await postFormDataWithProgress<BatchUploadProgress>(
        `${API_V1}/cases/batch/${caseId}/files`,
        chunkFormData,
        (loaded, total) => {
            const chunkProgress = total > 0 ? loaded / total : 0;
            const overallLoaded = uploadedBytes + chunk.totalBytes * chunkProgress;
            const percent = totalBytes > 0 ? Math.round((overallLoaded / totalBytes) * 100) : 100;
            const totalSizeMB = (totalBytes / 1024 / 1024).toFixed(1);
            onProgress(
                percent,
                `Uploading chunk ${chunkIndex + 1}/${chunkCount} (${totalFileCount} files, ${totalSizeMB}MB)...`
            );
        }
    );
};

// Cases API - Upload and Processing

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
        const formData = new FormData();
        formData.append('file', file);
        return postFormDataWithProgress<CaseResponse>(`${API_V1}/cases`, formData, (loaded, total) => {
            if (total > 0) {
                onProgress(Math.round((loaded / total) * 100));
            }
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
        const startTime = performance.now();
        const dcmFiles = files.filter((f) => f.name.toLowerCase().endsWith('.dcm'));
        const totalBytes = dcmFiles.reduce((sum, file) => sum + file.size, 0);

        onProgress(0, `Preparing ${dcmFiles.length} files...`);

        if (
            dcmFiles.length <= DIRECT_DICOM_FILE_THRESHOLD &&
            totalBytes <= DIRECT_DICOM_SIZE_THRESHOLD_BYTES
        ) {
            const formData = new FormData();
            for (const file of dcmFiles) {
                formData.append('files', file, file.name);
            }
            if (metadata && Object.keys(metadata).length > 0) {
                formData.append('metadata', JSON.stringify(metadata));
            }

            const response = await postFormDataWithProgress<CaseResponse>(
                `${API_V1}/cases/dicom`,
                formData,
                (loaded, total) => {
                    if (total > 0) {
                        const percent = Math.round((loaded / total) * 100);
                        const sizeMB = (total / 1024 / 1024).toFixed(1);
                        onProgress(percent, `Uploading ${dcmFiles.length} files (${sizeMB}MB)...`);
                    }
                }
            );

            const totalTime = performance.now() - startTime;
            console.log(`Direct DICOM upload time: ${(totalTime / 1000).toFixed(2)}s`);
            onProgress(100, 'Upload complete!');
            return response;
        }

        const initResponse = await axios.post<BatchInitResponse>(`${API_V1}/cases/batch/init`);
        const chunks = createUploadChunks(dcmFiles);
        let uploadedBytes = 0;
        let useDirectUpload =
            initResponse.data.storage_kind === 'object_store' &&
            Boolean(initResponse.data.direct_upload_enabled);
        const uploadConcurrency = Math.max(
            1,
            initResponse.data.recommended_upload_concurrency ?? DEFAULT_DIRECT_UPLOAD_CONCURRENCY
        );

        for (let index = 0; index < chunks.length; index++) {
            const chunk = chunks[index];
            if (useDirectUpload) {
                try {
                    await uploadBatchChunkDirect(
                        initResponse.data.case_id,
                        chunk,
                        index,
                        chunks.length,
                        dcmFiles.length,
                        totalBytes,
                        uploadedBytes,
                        onProgress,
                        uploadConcurrency
                    );
                } catch (error) {
                    console.warn('[casesApi] Direct upload failed, falling back to API relay upload:', error);
                    useDirectUpload = false;
                    onProgress(
                        totalBytes > 0 ? Math.round((uploadedBytes / totalBytes) * 100) : 0,
                        'Direct cloud upload unavailable. Falling back to server relay...'
                    );
                    await uploadBatchChunkViaApi(
                        initResponse.data.case_id,
                        chunk,
                        index,
                        chunks.length,
                        dcmFiles.length,
                        totalBytes,
                        uploadedBytes,
                        onProgress
                    );
                }
            } else {
                await uploadBatchChunkViaApi(
                    initResponse.data.case_id,
                    chunk,
                    index,
                    chunks.length,
                    dcmFiles.length,
                    totalBytes,
                    uploadedBytes,
                    onProgress
                );
            }

            uploadedBytes += chunk.totalBytes;
        }

        const finalizeFormData = new FormData();
        if (metadata && Object.keys(metadata).length > 0) {
            finalizeFormData.append('metadata', JSON.stringify(metadata));
        }

        const response = await postFormDataWithProgress<CaseResponse>(
            `${API_V1}/cases/batch/${initResponse.data.case_id}/finalize`,
            finalizeFormData
        );

        const totalTime = performance.now() - startTime;
        console.log(
            `Chunked DICOM upload time: ${(totalTime / 1000).toFixed(2)}s across ${chunks.length} chunks`
        );
        onProgress(100, 'Upload complete!');
        return response;
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
        metadataCache.delete(caseId);
    },

    /**
     * List available artifacts
     */
    getArtifacts: async (caseId: string): Promise<ArtifactList> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/artifacts`);
        return response.data;
    },
};

// CT API - Volume and Slice Data

export const ctApi = {
    /**
     * Get CT metadata
     */
    getMetadata: async (caseId: string): Promise<CTMetadata> => {
        const response = await axios.get(`${API_V1}/cases/${caseId}/metadata`);
        metadataCache.set(caseId, response.data);
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
    ): Promise<BinaryVolumePayload> => {
        const metadata = await ctApi.getMetadata(caseId);
        const spacing = spacingToTuple(metadata.voxel_spacing_mm);
        const directUrl = await fetchArtifactUrl(`${API_V1}/cases/${caseId}/ct/volume-url`);

        if (directUrl) {
            try {
                return await fetchNpyVolume(directUrl, spacing, onProgress);
            } catch (error) {
                console.warn('[ctApi] Falling back to backend volume endpoint:', error);
            }
        }

        return fetchRawVolumeFromApi(`${API_V1}/cases/${caseId}/ct/volume`, onProgress);
    },

    /**
     * Fetch downsampled preview volume for fast remote 2D viewing.
     */
    getPreviewVolumeBinary: async (
        caseId: string,
        onProgress?: (loaded: number, total: number) => void
    ): Promise<BinaryVolumePayload | null> => {
        const metadata = await ctApi.getMetadata(caseId);
        if (!metadata.preview_available || !metadata.preview_voxel_spacing_mm) {
            return null;
        }

        const previewSpacing = spacingToTuple(metadata.preview_voxel_spacing_mm);
        const directUrl = await fetchArtifactUrl(`${API_V1}/cases/${caseId}/ct/preview-volume-url`);

        if (directUrl) {
            try {
                return await fetchNpyVolume(directUrl, previewSpacing, onProgress);
            } catch (error) {
                console.warn('[ctApi] Falling back to backend preview volume endpoint:', error);
            }
        }

        try {
            return await fetchRawVolumeFromApi(`${API_V1}/cases/${caseId}/ct/preview-volume`, onProgress);
        } catch (error) {
            if (axios.isAxiosError(error) && error.response?.status === 404) {
                return null;
            }
            throw error;
        }
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

// Mask API - Segmentation Data

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
    ): Promise<BinaryMaskPayload | null> => {
        const directUrl = await fetchArtifactUrl(`${API_V1}/cases/${caseId}/mask/volume-url`);

        if (directUrl) {
            try {
                return await fetchNpyMask(directUrl, onProgress);
            } catch (error) {
                console.warn('[maskApi] Falling back to backend mask endpoint:', error);
            }
        }

        return fetchRawMaskFromApi(`${API_V1}/cases/${caseId}/mask/volume`, onProgress);
    },

    /**
     * Fetch downsampled preview mask for fast remote 2D viewing.
     */
    getPreviewMaskVolumeBinary: async (
        caseId: string,
        onProgress?: (loaded: number, total: number) => void
    ): Promise<BinaryMaskPayload | null> => {
        const metadata = await ctApi.getMetadata(caseId);
        if (!metadata.preview_mask_available) {
            return null;
        }

        const directUrl = await fetchArtifactUrl(`${API_V1}/cases/${caseId}/mask/preview-volume-url`);

        if (directUrl) {
            try {
                return await fetchNpyMask(directUrl, onProgress);
            } catch (error) {
                console.warn('[maskApi] Falling back to backend preview mask endpoint:', error);
            }
        }

        return fetchRawMaskFromApi(`${API_V1}/cases/${caseId}/mask/preview-volume`, onProgress);
    },
};

// Mesh API - 3D Reconstruction

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

// Implicit Representation API (SDF)

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

// Health Check

export const healthApi = {
    /**
     * Check if backend is healthy
     */
    check: async (): Promise<{ status: string; version: string }> => {
        const response = await axios.get(`${API_V1}/health`);
        return response.data;
    },
};
