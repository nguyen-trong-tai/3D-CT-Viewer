import axios from 'axios';

const API_BASE = 'http://localhost:8000'; // Assuming default FastAPI port

export const casesApi = {
    /**
     * Upload CT data (DICOM zip or NIfTI)
     * POST /cases
     */
    uploadCase: async (file: File): Promise<{ case_id: string; status: string }> => {
        const formData = new FormData();
        formData.append('file', file);
        const response = await axios.post(`${API_BASE}/cases`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
        return response.data;
    },

    /**
     * Upload with XMLHttpRequest for progress tracking
     */
    uploadCaseWithProgress: async (
        file: File,
        onProgress: (percent: number) => void
    ): Promise<{ case_id: string; status: string }> => {
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
            xhr.open('POST', `${API_BASE}/cases`);
            xhr.send(formData);
        });
    },

    /**
     * Upload multiple DICOM files in a SINGLE request - FASTEST approach!
     * Only 1 API call, with progress tracking via XMLHttpRequest.
     * 
     * Performance optimizations:
     * - Direct FormData streaming (no extra memory copies)
     * - Parallel file processing on server using ThreadPoolExecutor
     * - Optional metadata attachment
     * 
     * @param files - Array of DICOM files to upload
     * @param onProgress - Progress callback (percent, label)
     * @param metadata - Optional metadata object to attach (patient info, etc.)
     */
    uploadDicomFolder: async (
        files: File[],
        onProgress: (percent: number, label: string) => void,
        metadata?: Record<string, unknown>
    ): Promise<{ case_id: string; status: string }> => {
        return new Promise((resolve, reject) => {
            const startTime = performance.now();
            onProgress(0, `Preparing ${files.length} DICOM files...`);

            const xhr = new XMLHttpRequest();
            const formData = new FormData();

            // Filter only .dcm files and add to FormData (fast operation)
            const dcmFiles = files.filter(f => f.name.toLowerCase().endsWith('.dcm'));

            // Batch append for better performance
            for (let i = 0; i < dcmFiles.length; i++) {
                formData.append('files', dcmFiles[i], dcmFiles[i].name);
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
                    onProgress(percent, `Uploading ${dcmFiles.length} files (${sizeMB}MB)... ${percent}%`);
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

            xhr.addEventListener('error', () => reject(new Error('Upload failed - network error')));
            xhr.open('POST', `${API_BASE}/cases/dicom`);
            xhr.send(formData);
        });
    },

    /**
     * Trigger processing pipeline
     * POST /cases/{case_id}/process
     */
    processCase: async (caseId: string): Promise<{ case_id: string; status: string }> => {
        const response = await axios.post(`${API_BASE}/cases/${caseId}/process`);
        return response.data;
    },

    /**
     * Query processing status
     * GET /cases/{case_id}/status
     */
    getStatus: async (caseId: string): Promise<{ case_id: string; status: 'uploaded' | 'processing' | 'ready' | 'error' }> => {
        const response = await axios.get(`${API_BASE}/cases/${caseId}/status`);
        return response.data;
    },
};
