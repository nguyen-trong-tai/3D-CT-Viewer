const API_BASE = 'http://localhost:8000';

export const meshApi = {
    /**
     * Fetch Reconstructed Mesh URL
     * GET /cases/{case_id}/mesh
     * Returns a direct URL to be used by the 3D viewer loader.
     */
    getMeshUrl: (caseId: string): string => {
        return `${API_BASE}/cases/${caseId}/mesh`;
    },
};
