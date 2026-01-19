import axios from 'axios';

const API_BASE = 'http://localhost:8000';

export interface CTMetadata {
    volume_shape: { x: number; y: number; z: number };
    voxel_spacing_mm: { x: number; y: number; z: number };
    num_slices: number;
}

export interface SliceData {
    slice_index: number;
    hu_values: number[][]; // Raw HU values (preserved)
    spacing_mm: { x: number; y: number };
}

export const ctApi = {
    /**
     * Get CT Metadata
     * GET /cases/{case_id}/metadata
     */
    getMetadata: async (caseId: string): Promise<CTMetadata> => {
        const response = await axios.get(`${API_BASE}/cases/${caseId}/metadata`);
        return response.data;
    },

    /**
     * Fetch CT Slice (HU)
     * GET /cases/{case_id}/ct/slices/{slice_index}
     */
    getSlice: async (caseId: string, sliceIndex: number): Promise<SliceData> => {
        const response = await axios.get(`${API_BASE}/cases/${caseId}/ct/slices/${sliceIndex}`);
        return response.data;
    },

    /**
     * Get extra metadata (patient info, study details, etc.) if uploaded
     * GET /cases/{case_id}/extra-metadata
     * Returns null if no extra metadata was provided during upload
     */
    getExtraMetadata: async (caseId: string): Promise<Record<string, unknown> | null> => {
        try {
            const response = await axios.get(`${API_BASE}/cases/${caseId}/extra-metadata`);
            return response.data;
        } catch {
            return null; // No extra metadata available
        }
    },
};
