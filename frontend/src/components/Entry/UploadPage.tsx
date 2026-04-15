import React, { useCallback, useRef, useState } from 'react';
import {
    Activity,
    AlertCircle,
    FileUp,
    FolderUp,
    Loader2,
    Upload,
} from 'lucide-react';
import type { CaseMetadata } from '../../types';
import { casesApi, ctApi, isLikelyDicomFile } from '../../services/api';
import type { StatusResponse } from '../../services/api';
import { Button, ProgressBar } from '../UI';

interface UploadPageProps {
    onUploadComplete: (metadata: CaseMetadata) => void;
}

type UploadState = 'idle' | 'uploading' | 'error';

const TRANSFER_PROGRESS_MAX = 88;
const ACQUISITION_PROGRESS_MAX = 99;
const VIEWER_ARTIFACT_PROBE_INTERVAL_MS = 3000;

const normalizeCaseStatus = (status?: StatusResponse['status']): CaseMetadata['status'] => {
    switch (status) {
        case 'uploading':
        case 'uploaded':
        case 'processing':
        case 'ready':
        case 'error':
            return status;
        default:
            return 'uploaded';
    }
};

const readFileEntry = async (fileEntry: FileSystemFileEntry): Promise<File | null> => {
    return new Promise((resolve) => {
        fileEntry.file(
            (value) => resolve(value),
            () => resolve(null)
        );
    });
};

const readDirectoryEntries = async (dirEntry: FileSystemDirectoryEntry): Promise<File[]> => {
    return new Promise((resolve) => {
        const reader = dirEntry.createReader();
        const files: File[] = [];

        const readBatch = () => {
            reader.readEntries(async (entries) => {
                if (entries.length === 0) {
                    resolve(files);
                    return;
                }

                const batchFiles = await Promise.all(
                    entries.map(async (entry): Promise<File[]> => {
                        if (entry.isFile) {
                            const file = await readFileEntry(entry as FileSystemFileEntry);
                            return file ? [file] : [];
                        }
                        if (entry.isDirectory) {
                            return readDirectoryEntries(entry as FileSystemDirectoryEntry);
                        }
                        return [];
                    })
                );
                files.push(...batchFiles.flat());

                readBatch();
            });
        };

        readBatch();
    });
};

export const UploadPage: React.FC<UploadPageProps> = ({ onUploadComplete }) => {
    const [dragActive, setDragActive] = useState(false);
    const [uploadState, setUploadState] = useState<UploadState>('idle');
    const [errorMsg, setErrorMsg] = useState<string | null>(null);
    const [progress, setProgress] = useState(0);
    const [progressLabel, setProgressLabel] = useState('');

    const fileInputRef = useRef<HTMLInputElement>(null);
    const folderInputRef = useRef<HTMLInputElement>(null);

    const buildCaseMetadata = useCallback(async (caseId: string): Promise<CaseMetadata> => {
        ctApi.invalidateMetadata(caseId);
        const [metaRes, statusRes] = await Promise.all([
            ctApi.getMetadata(caseId),
            casesApi.getStatus(caseId),
        ]);

        return {
            id: caseId,
            totalSlices: metaRes.num_slices,
            dimensions: [
                metaRes.volume_shape.x,
                metaRes.volume_shape.y,
                metaRes.volume_shape.z,
            ],
            voxelSpacing: [
                metaRes.voxel_spacing_mm.x,
                metaRes.voxel_spacing_mm.y,
                metaRes.voxel_spacing_mm.z,
            ],
            status: normalizeCaseStatus(statusRes.status),
            huRange: metaRes.hu_range,
        };
    }, []);

    const setTransferProgress = useCallback((percent: number) => {
        const clampedPercent = Math.max(0, Math.min(100, percent));
        setProgress(Math.round((clampedPercent / 100) * TRANSFER_PROGRESS_MAX));
    }, []);

    const updateAcquisitionProgress = useCallback((progressPercent?: number, currentStage?: string) => {
        if (typeof progressPercent === 'number') {
            const clampedBackendProgress = Math.max(0, Math.min(100, progressPercent));
            const mappedProgress =
                TRANSFER_PROGRESS_MAX +
                (clampedBackendProgress / 100) * (ACQUISITION_PROGRESS_MAX - TRANSFER_PROGRESS_MAX);
            setProgress((current) => Math.max(current, Math.round(mappedProgress)));
        } else {
            setProgress((current) => Math.max(current, TRANSFER_PROGRESS_MAX));
        }

        switch (currentStage) {
            case 'receiving_upload':
                setProgressLabel('CT Acquisition: receiving DICOM files...');
                return;
            case 'reading_volume':
                setProgressLabel('CT Acquisition: reading uploaded volume...');
                return;
            case 'reading_dicom_headers':
                setProgressLabel('CT Acquisition: reading DICOM headers...');
                return;
            case 'expanding_archives':
                setProgressLabel('CT Acquisition: expanding uploaded archive shards...');
                return;
            case 'decoding_dicom_slices':
                setProgressLabel('CT Acquisition: decoding DICOM slices...');
                return;
            case 'saving_volume':
                setProgressLabel('CT Acquisition: converting upload into volume...');
                return;
            case 'generating_preview':
                setProgressLabel('CT Acquisition: generating preview for faster 2D viewing...');
                return;
            case 'uploaded':
                setProgressLabel('CT Acquisition: volume ready for 2D viewer...');
                return;
            default:
                setProgressLabel('CT Acquisition: preparing volume for 2D view...');
        }
    }, []);

    const waitForCaseUploadReady = useCallback(
        async (caseId: string): Promise<StatusResponse> => {
            const isReady = (status: StatusResponse) =>
                Boolean(status.viewer_ready) || status.status === 'uploaded' || status.status === 'ready';
            const applyStatus = (status: Pick<StatusResponse, 'progress_percent' | 'current_stage'>) => {
                updateAcquisitionProgress(status.progress_percent, status.current_stage);
            };
            let lastArtifactProbeAt = 0;
            const hasViewerArtifact = async (force = false) => {
                const now = Date.now();
                if (!force && now - lastArtifactProbeAt < VIEWER_ARTIFACT_PROBE_INTERVAL_MS) {
                    return false;
                }
                lastArtifactProbeAt = now;

                try {
                    const artifacts = await casesApi.getArtifacts(caseId);
                    return Boolean(
                        artifacts.artifacts.ct_volume || artifacts.artifacts.ct_volume_preview
                    );
                } catch {
                    return false;
                }
            };
            const evaluateStatus = async (status: StatusResponse, forceArtifactProbe = false) => {
                applyStatus(status);

                if (status.status === 'error') {
                    throw new Error(status.message || 'Error processing raw data into volume.');
                }

                if (isReady(status) || await hasViewerArtifact(forceArtifactProbe)) {
                    return status;
                }

                return null;
            };

            const initialStatus = await casesApi.getStatus(caseId);
            const initialReadyStatus = await evaluateStatus(initialStatus, true);
            if (initialReadyStatus) {
                return initialReadyStatus;
            }

            return new Promise<StatusResponse>((resolve, reject) => {
                let settled = false;
                let unsubscribe = () => {};

                const cleanup = () => {
                    window.clearInterval(pollInterval);
                    unsubscribe();
                };

                const settleSuccess = (status: StatusResponse) => {
                    if (settled) {
                        return;
                    }
                    settled = true;
                    cleanup();
                    resolve(status);
                };

                const settleError = (message: string) => {
                    if (settled) {
                        return;
                    }
                    settled = true;
                    cleanup();
                    reject(new Error(message));
                };

                const handleStatus = async (status: StatusResponse) => {
                    try {
                        const readyStatus = await evaluateStatus(status);
                        if (readyStatus) {
                            settleSuccess(readyStatus);
                        }
                    } catch (error) {
                        settleError(
                            error instanceof Error
                                ? error.message
                                : 'Error processing raw data into volume.'
                        );
                    }
                };

                const pollInterval = window.setInterval(() => {
                    void casesApi
                        .getStatus(caseId)
                        .then((status) => handleStatus(status))
                        .catch((error) => {
                            if (!settled) {
                                console.warn('[UploadPage] Failed to poll upload status:', error);
                            }
                        });
                }, 1000);

                unsubscribe = casesApi.subscribeToCaseEvents(caseId, {
                    onEvent: (payload) => {
                        if (payload.case_id !== caseId) {
                            return;
                        }

                        applyStatus({
                            progress_percent: payload.progress_percent,
                            current_stage: payload.current_stage,
                        });
                        const viewerReady =
                            payload.viewer_ready ||
                            payload.snapshot?.viewer_ready ||
                            payload.artifact === 'ct_volume' ||
                            payload.artifact === 'ct_volume_preview' ||
                            Boolean(payload.snapshot?.artifacts?.ct_volume) ||
                            Boolean(payload.snapshot?.artifacts?.ct_volume_preview);

                        if (payload.status === 'error') {
                            settleError(payload.message || 'Error processing raw data into volume.');
                            return;
                        }

                        if (payload.status === 'uploaded' || payload.status === 'ready' || viewerReady) {
                            settleSuccess({
                                case_id: caseId,
                                status: payload.status ?? 'uploading',
                                viewer_ready: viewerReady,
                                volume_ready:
                                    payload.volume_ready ??
                                    payload.snapshot?.volume_ready ??
                                    Boolean(payload.snapshot?.artifacts?.ct_volume),
                                message: payload.message,
                                current_stage: payload.current_stage,
                                progress_percent: payload.progress_percent,
                            });
                        }
                    },
                    onError: () => {
                        // Keep the polling fallback alive if SSE disconnects.
                    },
                });
            });
        },
        [updateAcquisitionProgress]
    );

    const processFiles = useCallback(
        async (items: DataTransferItemList | FileList | null) => {
            if (!items || items.length === 0) {
                return;
            }

            setErrorMsg(null);
            setProgress(0);
            setProgressLabel('');
            setUploadState('uploading');

            try {
                let fileArray: File[] = [];
                let metadataFile: File | null = null;

                if ('length' in items && items[0] && 'webkitGetAsEntry' in items[0]) {
                    setProgressLabel('Reading folder structure...');

                    const topLevelFiles = await Promise.all(
                        Array.from({ length: items.length }, async (_, index): Promise<File[]> => {
                            const item = items[index] as DataTransferItem;
                            const entry = item.webkitGetAsEntry?.();

                            if (entry?.isDirectory) {
                                return readDirectoryEntries(entry as FileSystemDirectoryEntry);
                            }
                            if (entry?.isFile) {
                                const file = item.getAsFile();
                                return file ? [file] : [];
                            }
                            return [];
                        })
                    );
                    fileArray = topLevelFiles.flat();
                } else {
                    fileArray = Array.from(items as FileList);
                }

                const dcmFiles: File[] = [];
                for (const file of fileArray) {
                    const lowerName = file.name.toLowerCase();
                    if (lowerName === 'metadata.json') {
                        metadataFile = file;
                    } else if (isLikelyDicomFile(file)) {
                        dcmFiles.push(file);
                    }
                }

                let extraMetadata: Record<string, unknown> | undefined;
                if (metadataFile) {
                    try {
                        extraMetadata = JSON.parse(await metadataFile.text()) as Record<string, unknown>;
                    } catch {
                        console.warn('Failed to parse metadata.json');
                    }
                }

                let caseId: string;
                if (dcmFiles.length > 0) {
                    const uploadRes = await casesApi.uploadDicomFolder(
                        dcmFiles,
                        (percent, label) => {
                            setTransferProgress(percent);
                            setProgressLabel(label);
                        },
                        extraMetadata
                    );
                    caseId = uploadRes.case_id;
                } else {
                    const file = fileArray[0];
                    if (!file) {
                        throw new Error('No valid files found');
                    }

                    setProgressLabel(`Uploading ${(file.size / 1024 / 1024).toFixed(1)} MB...`);
                    const uploadRes = await casesApi.uploadCaseWithProgress(file, (percent) => {
                        setTransferProgress(percent);
                    });
                    caseId = uploadRes.case_id;
                }

                setProgressLabel('CT Acquisition: preparing volume for 2D view...');
                await waitForCaseUploadReady(caseId);

                setProgress(100);
                setProgressLabel('Opening 2D viewer...');

                onUploadComplete(await buildCaseMetadata(caseId));
            } catch (err) {
                console.error(err);
                setUploadState('error');
                setErrorMsg(err instanceof Error ? err.message : 'Upload failed');
            }
        },
        [buildCaseMetadata, onUploadComplete, setTransferProgress, waitForCaseUploadReady]
    );

    const handleDrag = (event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();

        if (event.type === 'dragenter' || event.type === 'dragover') {
            setDragActive(true);
        } else if (event.type === 'dragleave') {
            setDragActive(false);
        }
    };

    const handleDrop = (event: React.DragEvent) => {
        event.preventDefault();
        event.stopPropagation();
        setDragActive(false);

        if (event.dataTransfer.items?.length > 0) {
            processFiles(event.dataTransfer.items);
        } else if (event.dataTransfer.files?.length > 0) {
            processFiles(event.dataTransfer.files);
        }
    };

    const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
        if (event.target.files && event.target.files.length > 0) {
            processFiles(event.target.files);
        }
    };

    const handleRetry = () => {
        setUploadState('idle');
        setErrorMsg(null);
        setProgress(0);
        setProgressLabel('');
    };

    return (
        <div
            style={{
                minHeight: '100vh',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'var(--gradient-dark)',
                padding: 'var(--space-xl)',
                position: 'relative',
                overflow: 'hidden',
            }}
        >
            <div
                style={{
                    position: 'absolute',
                    top: '20%',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: 600,
                    height: 600,
                    background: 'var(--gradient-glow)',
                    borderRadius: '50%',
                    pointerEvents: 'none',
                }}
            />

            <div
                style={{
                    maxWidth: 520,
                    width: '100%',
                    zIndex: 1,
                }}
            >
                <div style={{ textAlign: 'center', marginBottom: 'var(--space-2xl)' }}>
                    <div
                        style={{
                            width: 64,
                            height: 64,
                            margin: '0 auto var(--space-lg)',
                            borderRadius: 'var(--radius-xl)',
                            background: 'var(--gradient-primary)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            boxShadow: 'var(--shadow-glow)',
                        }}
                    >
                        <Activity size={32} color="white" />
                    </div>
                    <h1 style={{ fontSize: '2rem', marginBottom: 'var(--space-sm)' }}>ViewR CT</h1>
                    <p style={{ color: 'var(--text-secondary)' }}>
                        CT-based Medical Imaging & AI Research Platform
                    </p>
                </div>

                {uploadState === 'idle' && (
                    <div
                        className="animate-fade-in"
                        onDragEnter={handleDrag}
                        onDragLeave={handleDrag}
                        onDragOver={handleDrag}
                        onDrop={handleDrop}
                        style={{
                            border: `2px dashed ${dragActive ? 'var(--accent-primary)' : 'var(--border-default)'}`,
                            borderRadius: 'var(--radius-xl)',
                            padding: 'var(--space-2xl)',
                            background: dragActive ? 'rgba(59, 130, 246, 0.05)' : 'var(--bg-panel)',
                            textAlign: 'center',
                            transition: 'all var(--transition-base)',
                            cursor: 'default',
                        }}
                    >
                        <div
                            style={{
                                width: 56,
                                height: 56,
                                margin: '0 auto var(--space-lg)',
                                borderRadius: '50%',
                                background: 'var(--bg-element)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                border: '1px solid var(--border-subtle)',
                            }}
                        >
                            <Upload size={24} color="var(--accent-primary)" />
                        </div>

                        <h3 style={{ marginBottom: 'var(--space-sm)' }}>
                            Drag & drop DICOM folder or NIfTI file
                        </h3>
                        <p
                            style={{
                                fontSize: '0.9rem',
                                color: 'var(--text-muted)',
                                marginBottom: 'var(--space-lg)',
                            }}
                        >
                            Supported formats: DICOM (.dcm, .ima, extensionless), .nii, .nii.gz
                        </p>

                        <div style={{ display: 'flex', gap: 'var(--space-md)', justifyContent: 'center' }}>
                            <Button
                                variant="default"
                                icon={<FileUp size={16} />}
                                onClick={() => fileInputRef.current?.click()}
                            >
                                Select File
                            </Button>
                            <Button
                                variant="default"
                                icon={<FolderUp size={16} />}
                                onClick={() => folderInputRef.current?.click()}
                            >
                                Select Folder
                            </Button>
                        </div>

                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".nii,.nii.gz,.dcm,.dicom,.ima,.zip"
                            style={{ display: 'none' }}
                            onChange={handleFileSelect}
                        />
                        <input
                            ref={folderInputRef}
                            type="file"
                            // @ts-expect-error - webkitdirectory is not in types
                            webkitdirectory=""
                            directory=""
                            style={{ display: 'none' }}
                            onChange={handleFileSelect}
                        />
                    </div>
                )}

                {uploadState === 'uploading' && (
                    <div
                        className="card animate-scale-in"
                        style={{
                            padding: 'var(--space-2xl)',
                            textAlign: 'center',
                        }}
                    >
                        <div
                            style={{
                                width: 64,
                                height: 64,
                                margin: '0 auto var(--space-lg)',
                                position: 'relative',
                            }}
                        >
                            <Loader2
                                size={64}
                                color="var(--accent-primary)"
                                style={{ animation: 'spin 1s linear infinite' }}
                            />
                        </div>

                        <h3 style={{ marginBottom: 'var(--space-sm)' }}>
                            Preparing Case...
                        </h3>
                        <p
                            style={{
                                fontSize: '0.9rem',
                                color: 'var(--text-muted)',
                                marginBottom: 'var(--space-lg)',
                            }}
                        >
                            {progressLabel || 'Please wait...'}
                        </p>

                        <ProgressBar value={progress} showLabel size="md" />
                    </div>
                )}

                {uploadState === 'error' && (
                    <div
                        className="card animate-scale-in"
                        style={{
                            padding: 'var(--space-2xl)',
                            textAlign: 'center',
                            borderColor: 'var(--accent-error)',
                        }}
                    >
                        <div
                            style={{
                                width: 64,
                                height: 64,
                                margin: '0 auto var(--space-lg)',
                                borderRadius: '50%',
                                background: 'var(--accent-error-glow)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                            }}
                        >
                            <AlertCircle size={32} color="var(--accent-error)" />
                        </div>

                        <h3 style={{ color: 'var(--accent-error)', marginBottom: 'var(--space-sm)' }}>
                            Upload Failed
                        </h3>
                        <p
                            style={{
                                fontSize: '0.9rem',
                                color: 'var(--text-muted)',
                                marginBottom: 'var(--space-lg)',
                            }}
                        >
                            {errorMsg}
                        </p>

                        <Button variant="primary" onClick={handleRetry}>
                            Try Again
                        </Button>
                    </div>
                )}
            </div>

            <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
        </div>
    );
};
