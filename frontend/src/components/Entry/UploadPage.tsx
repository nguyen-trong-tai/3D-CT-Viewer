import React, { useState, useRef } from 'react';
import { Upload, FileUp, CheckCircle, AlertCircle, Loader2, FolderUp } from 'lucide-react';
import type { CaseMetadata } from '../../types';
import { casesApi } from '../../services/api/cases';
import { ctApi } from '../../services/api/ct';

interface UploadPageProps {
    onUploadComplete: (metadata: CaseMetadata) => void;
    isProcessing?: boolean;
}

export const UploadPage: React.FC<UploadPageProps> = ({ onUploadComplete }) => {
    const [dragActive, setDragActive] = useState(false);
    const [uploadState, setUploadState] = useState<'idle' | 'zipping' | 'uploading' | 'processing' | 'ready' | 'error'>('idle');
    const [errorMsg, setErrorMsg] = useState<string | null>(null);
    const [metadata, setMetadata] = useState<CaseMetadata | null>(null);
    const [progress, setProgress] = useState(0); // 0-100
    const [progressLabel, setProgressLabel] = useState('');
    const fileInputRef = useRef<HTMLInputElement>(null);
    const folderInputRef = useRef<HTMLInputElement>(null);

    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === "dragenter" || e.type === "dragover") {
            setDragActive(true);
        } else if (e.type === "dragleave") {
            setDragActive(false);
        }
    };

    /**
     * Read all files from a directory entry recursively using the File System Access API.
     * This is MUCH faster than reading file contents upfront.
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
                    readBatch(); // Continue reading (entries come in batches)
                });
            };
            readBatch();
        });
    };

    /**
     * Process files for upload - optimized for speed
     * - Uses webkitGetAsEntry for instant folder detection
     * - Extracts metadata.json if present
     * - Only .dcm files are uploaded
     */
    const processFiles = async (items: DataTransferItemList | FileList | null) => {
        if (!items || items.length === 0) return;

        setErrorMsg(null);
        setProgress(0);

        try {
            const startTime = performance.now();
            let fileArray: File[] = [];
            let metadataFile: File | null = null;

            // Handle DataTransferItemList (from drag-drop) - FASTEST for folders
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
                // Handle regular FileList (from input element)
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
            let metadata: Record<string, unknown> | undefined;
            if (metadataFile) {
                try {
                    const text = await metadataFile.text();
                    metadata = JSON.parse(text);
                    console.log('Found metadata.json:', metadata);
                } catch {
                    console.warn('Failed to parse metadata.json');
                }
            }

            const loadTime = performance.now() - startTime;
            console.log(`File loading took ${loadTime.toFixed(0)}ms for ${dcmFiles.length} DICOM files`);

            // Check if this is a DICOM folder (multiple .dcm files)
            const isDicomFolder = dcmFiles.length > 1;

            let caseId: string;

            if (isDicomFolder) {
                // Use fast DICOM upload
                setUploadState('uploading');
                setProgressLabel(`Uploading ${dcmFiles.length} DICOM files...`);

                const uploadRes = await casesApi.uploadDicomFolder(
                    dcmFiles,
                    (percent, label) => {
                        setProgress(percent);
                        setProgressLabel(label);
                    },
                    metadata
                );
                caseId = uploadRes.case_id;

            } else if (dcmFiles.length === 1) {
                // Single DICOM file - still use folder API for consistency
                setUploadState('uploading');
                setProgressLabel('Uploading DICOM file...');

                const uploadRes = await casesApi.uploadDicomFolder(
                    dcmFiles,
                    (percent, label) => {
                        setProgress(percent);
                        setProgressLabel(label);
                    },
                    metadata
                );
                caseId = uploadRes.case_id;

            } else {
                // Non-DICOM file (NIfTI, etc.)
                const file = fileArray[0];
                if (!file) {
                    throw new Error('No valid files found');
                }

                setUploadState('uploading');
                setProgress(0);
                setProgressLabel(`Uploading ${(file.size / 1024 / 1024).toFixed(1)} MB...`);

                const uploadRes = await casesApi.uploadCaseWithProgress(
                    file,
                    (percent) => setProgress(percent)
                );
                caseId = uploadRes.case_id;
            }

            // Processing
            setUploadState('processing');
            setProgress(0);
            setProgressLabel('Analyzing volume...');
            await casesApi.processCase(caseId);

            // Poll Status
            const pollInterval = setInterval(async () => {
                try {
                    const statusRes = await casesApi.getStatus(caseId);

                    if (statusRes.status === 'ready') {
                        clearInterval(pollInterval);

                        const metaRes = await ctApi.getMetadata(caseId);

                        const newMeta: CaseMetadata = {
                            id: caseId,
                            totalSlices: metaRes.num_slices,
                            dimensions: [metaRes.volume_shape.x, metaRes.volume_shape.y, metaRes.volume_shape.z],
                            voxelSpacing: [metaRes.voxel_spacing_mm.x, metaRes.voxel_spacing_mm.y, metaRes.voxel_spacing_mm.z],
                            status: 'ready'
                        };

                        setMetadata(newMeta);
                        setUploadState('ready');

                        // Auto-navigate to viewer after a short delay
                        setTimeout(() => {
                            onUploadComplete(newMeta);
                        }, 1000);

                    } else if (statusRes.status === 'error') {
                        clearInterval(pollInterval);
                        setUploadState('error');
                        setErrorMsg("Processing failed on server.");
                    }
                } catch (e) {
                    clearInterval(pollInterval);
                    console.error("Polling error", e);
                    setUploadState('error');
                    setErrorMsg("Lost connection to server.");
                }
            }, 1000);

        } catch (err) {
            console.error(err);
            setUploadState('error');
            setErrorMsg("Failed to upload or trigger processing.");
        }
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);

        // Use items for better folder drag-drop support (webkitGetAsEntry)
        if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
            processFiles(e.dataTransfer.items);
        } else if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
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

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100vh',
            background: 'var(--bg-main)',
            color: 'var(--text-main)',
            padding: '2rem'
        }}>
            <div style={{
                maxWidth: '600px',
                width: '100%',
                textAlign: 'center'
            }}>
                <h1 style={{ marginBottom: '0.5rem', fontSize: '2rem', color: 'white' }}>
                    CT VIEWER
                </h1>
                <p style={{ color: 'var(--text-scnd)', marginBottom: '3rem' }}>
                    Upload medical imaging data to reconstruct 3D models.
                </p>

                {uploadState === 'idle' && (
                    <div
                        className={`upload-zone ${dragActive ? 'drag-active' : ''}`}
                        onDragEnter={handleDrag}
                        onDragLeave={handleDrag}
                        onDragOver={handleDrag}
                        onDrop={handleDrop}
                        style={{
                            border: `2px dashed ${dragActive ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
                            borderRadius: '16px',
                            padding: '3rem',
                            background: dragActive ? 'rgba(59, 130, 246, 0.05)' : 'var(--bg-element)',
                            cursor: 'default',
                            transition: 'all 0.2s ease'
                        }}
                    >
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
                            <div style={{
                                background: 'var(--bg-main)',
                                padding: '16px',
                                borderRadius: '50%',
                                boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                            }}>
                                <Upload size={32} color="var(--accent-primary)" />
                            </div>

                            <h3 style={{ marginTop: '1rem' }}>Drag & drop DICOM folder or NIfTI file</h3>
                            <p style={{ color: 'var(--text-scnd)', fontSize: '0.9rem' }}>
                                Supported formats: .dcm, .nii, .nii.gz
                            </p>

                            <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
                                <button className="secondary" onClick={() => fileInputRef.current?.click()}>
                                    <FileUp size={16} style={{ marginRight: '8px' }} />
                                    Select File
                                </button>
                                <button className="secondary" onClick={() => folderInputRef.current?.click()}>
                                    <FolderUp size={16} style={{ marginRight: '8px' }} />
                                    Select Folder
                                </button>
                            </div>

                            {/* Hidden Inputs */}
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept=".nii,.nii.gz,.dcm"
                                style={{ display: 'none' }}
                                onChange={handleFileSelect}
                            />
                            <input
                                ref={folderInputRef}
                                type="file"
                                // @ts-expect-error - webkitdirectory is non-standard but supported in most browsers
                                webkitdirectory=""
                                directory=""
                                style={{ display: 'none' }}
                                onChange={handleFileSelect}
                            />
                        </div>
                    </div>
                )}

                {(uploadState === 'uploading' || uploadState === 'processing' || uploadState === 'zipping') && (
                    <div className="card" style={{ padding: '3rem', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                        <Loader2 size={48} className="spin" style={{ color: 'var(--accent-primary)', marginBottom: '1.5rem' }} />
                        <h3>
                            {uploadState === 'zipping' ? 'Preparing Files...' :
                                uploadState === 'uploading' ? 'Uploading Data...' :
                                    'Processing Volume...'}
                        </h3>
                        <p style={{ color: 'var(--text-scnd)', marginTop: '8px', marginBottom: '1.5rem' }}>
                            {progressLabel || (uploadState === 'processing' ? 'Analyzing slices and generating 3D mesh.' : 'Please wait...')}
                        </p>

                        {/* Progress Bar */}
                        <div style={{
                            width: '100%',
                            maxWidth: '400px',
                            height: '8px',
                            background: 'var(--bg-element)',
                            borderRadius: '4px',
                            overflow: 'hidden',
                            marginBottom: '0.5rem'
                        }}>
                            <div style={{
                                width: `${progress}%`,
                                height: '100%',
                                background: 'linear-gradient(90deg, var(--accent-primary), #60a5fa)',
                                borderRadius: '4px',
                                transition: 'width 0.3s ease'
                            }} />
                        </div>
                        <span style={{ color: 'var(--text-scnd)', fontSize: '0.9rem' }}>
                            {progress}%
                        </span>
                    </div>
                )}

                {uploadState === 'error' && (
                    <div className="card" style={{ padding: '3rem', display: 'flex', flexDirection: 'column', alignItems: 'center', borderColor: 'var(--accent-error)' }}>
                        <AlertCircle size={48} color="var(--accent-error)" style={{ marginBottom: '1.5rem' }} />
                        <h3 style={{ color: 'var(--accent-error)' }}>Upload Failed</h3>
                        <p style={{ color: 'var(--text-scnd)', marginTop: '8px', marginBottom: '1.5rem' }}>{errorMsg}</p>
                        <button onClick={() => setUploadState('idle')}>Try Again</button>
                    </div>
                )}

                {uploadState === 'ready' && metadata && (
                    <div className="card" style={{ textAlign: 'left', animation: 'fadeIn 0.5s' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '1.5rem', paddingBottom: '1rem', borderBottom: '1px solid var(--border-subtle)' }}>
                            <CheckCircle size={24} color="var(--accent-success)" />
                            <h3 style={{ margin: 0 }}>Ready for Visualization</h3>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '2rem' }}>
                            <div>
                                <label style={{ display: 'block', color: 'var(--text-scnd)', fontSize: '0.85rem' }}>Total Slices</label>
                                <div style={{ fontSize: '1.1rem', fontWeight: 500 }}>{metadata.totalSlices}</div>
                            </div>
                            <div>
                                <label style={{ display: 'block', color: 'var(--text-scnd)', fontSize: '0.85rem' }}>Dimensions</label>
                                <div style={{ fontSize: '1.1rem', fontWeight: 500 }}>{metadata.dimensions.join(' × ')}</div>
                            </div>
                            <div style={{ gridColumn: '1 / -1' }}>
                                <label style={{ display: 'block', color: 'var(--text-scnd)', fontSize: '0.85rem' }}>Voxel Spacing (mm)</label>
                                <div style={{ fontSize: '1.1rem', fontWeight: 500 }}>
                                    X: {metadata.voxelSpacing[0]} | Y: {metadata.voxelSpacing[1]} | Z: {metadata.voxelSpacing[2]}
                                </div>
                            </div>
                        </div>

                        <button className="primary" style={{ width: '100%', justifyContent: 'center' }} onClick={handleConfirm}>
                            Launch Viewer
                        </button>
                        <button className="text-btn" style={{ width: '100%', marginTop: '12px', color: 'var(--text-scnd)' }} onClick={() => setUploadState('idle')}>
                            Upload Different File
                        </button>
                    </div>
                )}
            </div>
        </div >
    );
};
