import React, { useState, useRef, useCallback } from 'react';
import {
    Upload,
    FileUp,
    FolderUp,
    CheckCircle,
    AlertCircle,
    ArrowRight,
    Activity,
    Loader2,
} from 'lucide-react';
import type { CaseMetadata, PipelineStep, PipelineStepStatus } from '../../types';
import { PIPELINE_STEPS } from '../../types';
import { casesApi, ctApi } from '../../services/api';
import { Button, ProgressBar, InfoRow } from '../UI';

interface UploadPageProps {
    onUploadComplete: (metadata: CaseMetadata) => void;
}

type UploadState = 'idle' | 'uploading' | 'processing' | 'ready' | 'error';

/**
 * Upload Page Component
 * Entry point for loading CT data (DICOM folders or NIfTI files)
 */
export const UploadPage: React.FC<UploadPageProps> = ({ onUploadComplete }) => {
    const [dragActive, setDragActive] = useState(false);
    const [uploadState, setUploadState] = useState<UploadState>('idle');
    const [errorMsg, setErrorMsg] = useState<string | null>(null);
    const [metadata, setMetadata] = useState<CaseMetadata | null>(null);
    const [progress, setProgress] = useState(0);
    const [progressLabel, setProgressLabel] = useState('');
    const [pipelineSteps, setPipelineSteps] = useState<PipelineStep[]>(PIPELINE_STEPS);

    const fileInputRef = useRef<HTMLInputElement>(null);
    const folderInputRef = useRef<HTMLInputElement>(null);

    /**
     * Update pipeline step status
     */
    const updateStepStatus = useCallback((stepId: string, status: PipelineStepStatus) => {
        setPipelineSteps(prev =>
            prev.map(step =>
                step.id === stepId ? { ...step, status } : step
            )
        );
    }, []);

    /**
     * Read directory entries recursively (for drag-drop folders)
     */
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

                    for (const entry of entries) {
                        if (entry.isFile) {
                            const fileEntry = entry as FileSystemFileEntry;
                            const file = await new Promise<File>((res) => {
                                fileEntry.file((f) => res(f));
                            });
                            files.push(file);
                        } else if (entry.isDirectory) {
                            const subFiles = await readDirectoryEntries(entry as FileSystemDirectoryEntry);
                            files.push(...subFiles);
                        }
                    }
                    readBatch();
                });
            };
            readBatch();
        });
    };

    /**
     * Process uploaded files
     */
    const processFiles = useCallback(
        async (items: DataTransferItemList | FileList | null) => {
            if (!items || items.length === 0) return;

            setErrorMsg(null);
            setProgress(0);
            setUploadState('uploading');
            setPipelineSteps(PIPELINE_STEPS); // Reset pipeline

            try {
                let fileArray: File[] = [];
                let metadataFile: File | null = null;

                // Handle drag-drop with folder support
                if ('length' in items && items[0] && 'webkitGetAsEntry' in items[0]) {
                    setProgressLabel('Reading folder structure...');

                    for (let i = 0; i < items.length; i++) {
                        const item = items[i] as DataTransferItem;
                        const entry = item.webkitGetAsEntry?.();

                        if (entry?.isDirectory) {
                            const dirFiles = await readDirectoryEntries(entry as FileSystemDirectoryEntry);
                            fileArray.push(...dirFiles);
                        } else if (entry?.isFile) {
                            const file = item.getAsFile();
                            if (file) fileArray.push(file);
                        }
                    }
                } else {
                    fileArray = Array.from(items as FileList);
                }

                // Separate metadata and DICOM files
                const dcmFiles: File[] = [];
                for (const file of fileArray) {
                    const lowerName = file.name.toLowerCase();
                    if (lowerName === 'metadata.json') {
                        metadataFile = file;
                    } else if (lowerName.endsWith('.dcm')) {
                        dcmFiles.push(file);
                    }
                }

                // Parse metadata if found
                let extraMetadata: Record<string, unknown> | undefined;
                if (metadataFile) {
                    try {
                        const text = await metadataFile.text();
                        extraMetadata = JSON.parse(text);
                    } catch {
                        console.warn('Failed to parse metadata.json');
                    }
                }

                let caseId: string;

                // Upload DICOM folder
                if (dcmFiles.length > 0) {
                    const uploadRes = await casesApi.uploadDicomFolder(
                        dcmFiles,
                        (percent, label) => {
                            setProgress(percent);
                            setProgressLabel(label);
                        },
                        extraMetadata
                    );
                    caseId = uploadRes.case_id;
                } else {
                    // Single file (NIfTI)
                    const file = fileArray[0];
                    if (!file) throw new Error('No valid files found');

                    setProgressLabel(`Uploading ${(file.size / 1024 / 1024).toFixed(1)} MB...`);
                    const uploadRes = await casesApi.uploadCaseWithProgress(file, (percent) => {
                        setProgress(percent);
                    });
                    caseId = uploadRes.case_id;
                }

                // Mark upload complete
                updateStepStatus('load_volume', 'completed');

                // Processing phase
                setUploadState('processing');
                setProgress(0);
                setProgressLabel('Starting AI pipeline...');
                await casesApi.processCase(caseId);

                // Poll for completion with pipeline status updates
                let pollCount = 0;
                const maxPolls = 120; // 2 minutes max

                const pollInterval = setInterval(async () => {
                    try {
                        pollCount++;

                        // Get detailed pipeline status
                        const pipelineStatus = await casesApi.getPipelineStatus(caseId);

                        // Update pipeline steps based on response
                        if (pipelineStatus.stages) {
                            for (const stage of pipelineStatus.stages) {
                                let status: PipelineStepStatus = 'pending';
                                if (stage.status === 'completed') status = 'completed';
                                else if (stage.status === 'running') status = 'running';
                                else if (stage.status === 'failed') status = 'failed';
                                else if (stage.status === 'skipped') status = 'completed';

                                updateStepStatus(stage.name, status);
                            }
                        }

                        // Update progress label based on current stage
                        const runningStage = pipelineStatus.stages?.find(s => s.status === 'running');
                        if (runningStage) {
                            const stageLabels: Record<string, string> = {
                                'segmentation': 'Running segmentation...',
                                'sdf': 'Computing implicit field...',
                                'mesh': 'Generating 3D mesh...',
                            };
                            setProgressLabel(stageLabels[runningStage.name] || 'Processing...');
                        }

                        if (pipelineStatus.overall_status === 'ready') {
                            clearInterval(pollInterval);

                            // Mark all steps completed
                            setPipelineSteps(prev =>
                                prev.map(step => ({ ...step, status: 'completed' as const }))
                            );

                            const metaRes = await ctApi.getMetadata(caseId);
                            const newMeta: CaseMetadata = {
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
                                status: 'ready',
                                huRange: metaRes.hu_range,
                            };

                            setMetadata(newMeta);
                            setUploadState('ready');
                            setProgressLabel('Complete!');

                            // // Auto-navigate after delay
                            // setTimeout(() => {
                            //     onUploadComplete(newMeta);
                            // }, 2000);

                        } else if (pipelineStatus.overall_status === 'error') {
                            clearInterval(pollInterval);
                            setUploadState('error');
                            setErrorMsg('Processing failed on the server.');
                        } else if (pollCount >= maxPolls) {
                            clearInterval(pollInterval);
                            setUploadState('error');
                            setErrorMsg('Processing timeout. Please try again.');
                        }
                    } catch (e) {
                        // Fallback to simple status check
                        try {
                            const statusRes = await casesApi.getStatus(caseId);

                            if (statusRes.status === 'ready') {
                                clearInterval(pollInterval);

                                const metaRes = await ctApi.getMetadata(caseId);
                                const newMeta: CaseMetadata = {
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
                                    status: 'ready',
                                };

                                setMetadata(newMeta);
                                setUploadState('ready');

                                setTimeout(() => {
                                    onUploadComplete(newMeta);
                                }, 1500);

                            } else if (statusRes.status === 'error') {
                                clearInterval(pollInterval);
                                setUploadState('error');
                                setErrorMsg(statusRes.message || 'Processing failed.');
                            }
                        } catch {
                            clearInterval(pollInterval);
                            setUploadState('error');
                            setErrorMsg('Lost connection to the server.');
                        }
                    }
                }, 1000);
            } catch (err) {
                console.error(err);
                setUploadState('error');
                setErrorMsg(err instanceof Error ? err.message : 'Upload failed');
            }
        },
        [onUploadComplete, updateStepStatus]
    );

    // Drag handlers
    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setDragActive(true);
        } else if (e.type === 'dragleave') {
            setDragActive(false);
        }
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);

        if (e.dataTransfer.items?.length > 0) {
            processFiles(e.dataTransfer.items);
        } else if (e.dataTransfer.files?.length > 0) {
            processFiles(e.dataTransfer.files);
        }
    };

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
            processFiles(e.target.files);
        }
    };

    const handleConfirm = () => {
        if (metadata) {
            onUploadComplete(metadata);
        }
    };

    const handleRetry = () => {
        setUploadState('idle');
        setErrorMsg(null);
        setMetadata(null);
        setProgress(0);
        setPipelineSteps(PIPELINE_STEPS);
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
            {/* Background Glow */}
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
                {/* Header */}
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

                {/* Idle State - Upload Zone */}
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
                            background: dragActive
                                ? 'rgba(59, 130, 246, 0.05)'
                                : 'var(--bg-panel)',
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
                        <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: 'var(--space-lg)' }}>
                            Supported formats: .dcm, .nii, .nii.gz
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

                        {/* Hidden inputs */}
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept=".nii,.nii.gz,.dcm,.zip"
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

                {/* Uploading / Processing State */}
                {(uploadState === 'uploading' || uploadState === 'processing') && (
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
                            {uploadState === 'uploading' ? 'Uploading Data...' : 'Processing Volume...'}
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

                        {uploadState === 'uploading' && (
                            <ProgressBar value={progress} showLabel size="md" />
                        )}

                        {/* Pipeline Steps */}
                        {uploadState === 'processing' && (
                            <div style={{ marginTop: 'var(--space-lg)', textAlign: 'left' }}>
                                {pipelineSteps.map((step) => (
                                    <div
                                        key={step.id}
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 'var(--space-sm)',
                                            padding: 'var(--space-sm) 0',
                                            opacity: step.status === 'pending' ? 0.5 : 1,
                                        }}
                                    >
                                        {step.status === 'completed' && (
                                            <CheckCircle size={16} color="var(--accent-success)" />
                                        )}
                                        {step.status === 'running' && (
                                            <Loader2
                                                size={16}
                                                color="var(--accent-primary)"
                                                style={{ animation: 'spin 1s linear infinite' }}
                                            />
                                        )}
                                        {step.status === 'pending' && (
                                            <div
                                                style={{
                                                    width: 16,
                                                    height: 16,
                                                    borderRadius: '50%',
                                                    border: '2px solid var(--border-subtle)',
                                                }}
                                            />
                                        )}
                                        {step.status === 'failed' && (
                                            <AlertCircle size={16} color="var(--accent-error)" />
                                        )}
                                        <span style={{
                                            color: step.status === 'completed'
                                                ? 'var(--text-primary)'
                                                : 'var(--text-muted)',
                                            fontSize: '0.85rem',
                                        }}>
                                            {step.label}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Error State */}
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

                {/* Ready State */}
                {uploadState === 'ready' && metadata && (
                    <div className="card animate-scale-in" style={{ padding: 'var(--space-xl)' }}>
                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 'var(--space-md)',
                                marginBottom: 'var(--space-lg)',
                                paddingBottom: 'var(--space-md)',
                                borderBottom: '1px solid var(--border-subtle)',
                            }}
                        >
                            <div
                                style={{
                                    width: 40,
                                    height: 40,
                                    borderRadius: '50%',
                                    background: 'var(--accent-success-glow)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                }}
                            >
                                <CheckCircle size={24} color="var(--accent-success)" />
                            </div>
                            <div>
                                <h3 style={{ marginBottom: 2 }}>Ready for Visualization</h3>
                                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                                    Case ID: {metadata.id.slice(0, 8)}...
                                </span>
                            </div>
                        </div>

                        <div style={{ marginBottom: 'var(--space-lg)' }}>
                            <InfoRow label="Total Slices" value={metadata.totalSlices} mono />
                            <InfoRow
                                label="Volume Dimensions"
                                value={metadata.dimensions.join(' × ')}
                                mono
                            />
                            <InfoRow
                                label="Voxel Spacing (mm)"
                                value={metadata.voxelSpacing.map((v) => v.toFixed(2)).join(' × ')}
                                mono
                            />
                            {metadata.huRange && (
                                <InfoRow
                                    label="HU Range"
                                    value={`${metadata.huRange.min.toFixed(0)} to ${metadata.huRange.max.toFixed(0)}`}
                                    mono
                                />
                            )}
                        </div>

                        <Button
                            variant="primary"
                            fullWidth
                            icon={<ArrowRight size={16} />}
                            iconPosition="right"
                            onClick={handleConfirm}
                        >
                            Launch Viewer
                        </Button>

                        <button
                            onClick={handleRetry}
                            style={{
                                width: '100%',
                                marginTop: 'var(--space-md)',
                                background: 'transparent',
                                border: 'none',
                                color: 'var(--text-muted)',
                                cursor: 'pointer',
                                fontSize: '0.85rem',
                            }}
                        >
                            Upload Different File
                        </button>
                    </div>
                )}

                {/* Research Disclaimer */}
                <div
                    style={{
                        marginTop: 'var(--space-xl)',
                        padding: 'var(--space-md)',
                        background: 'rgba(239, 68, 68, 0.05)',
                        border: '1px solid rgba(239, 68, 68, 0.2)',
                        borderRadius: 'var(--radius-md)',
                        textAlign: 'center',
                    }}
                >
                    <p
                        style={{
                            fontSize: '0.75rem',
                            color: 'var(--accent-error)',
                            lineHeight: 1.5,
                            margin: 0,
                        }}
                    >
                        This software is intended for research and educational purposes only.
                        <br />
                        It is not certified for clinical diagnosis or treatment.
                    </p>
                </div>
            </div>

            {/* Animation keyframes */}
            <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
        </div>
    );
};
