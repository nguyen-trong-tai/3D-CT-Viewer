import axios from 'axios';

const API_BASE = 'http://localhost:8000';

export interface MaskSliceData {
    slice_index: number;
    mask: number[][]; // 0 or 1
    sparse: boolean;
}

export const maskApi = {
    /**
     * Fetch Segmentation Mask Slice
     * GET /cases/{case_id}/mask/slices/{slice_index}
     */
    getMaskSlice: async (caseId: string, sliceIndex: number): Promise<MaskSliceData | null> => {
        try {
            const response = await axios.get(`${API_BASE}/cases/${caseId}/mask/slices/${sliceIndex}`);
            return response.data;
        } catch (error) {
            // 404 is valid for sparse/missing masks or unprocessed cases
            if (axios.isAxiosError(error) && error.response?.status === 404) {
                return null;
            }
            throw error;
        }
    },
};
