export interface CaseMetadata {
    id: string; // matches case_id from backend
    totalSlices: number;
    dimensions: [number, number, number]; // [x, y, z] in pixels/voxels
    voxelSpacing: [number, number, number]; // [x, y, z] in mm
    status: 'idle' | 'uploading' | 'processing' | 'ready' | 'error';
}

export interface PipelineStep {
    id: string;
    label: string;
    description?: string;
    status: 'pending' | 'processing' | 'completed' | 'error';
}

// However, the viewers will now use direct data or dedicated hooks.

export const PIPELINE_STEPS: PipelineStep[] = [
    { id: '1', label: 'CT Acquisition', status: 'completed' },
    { id: '2', label: 'Preprocessing', status: 'completed' },
    { id: '3', label: 'Segmentation (U-Net)', status: 'completed' },
    { id: '4', label: 'Implicit Field (SDF)', status: 'processing' },
    { id: '5', label: 'Marching Cubes', status: 'pending' },
];
