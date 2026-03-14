// ============================================
// VIEWR CT - TYPE DEFINITIONS
// ============================================

/**
 * Case Metadata from backend
 * Contains volume dimensions and spatial information
 */
export interface CaseMetadata {
    id: string;
    totalSlices: number;
    dimensions: [number, number, number]; // [x, y, z] voxel dimensions
    voxelSpacing: [number, number, number]; // [x, y, z] in millimeters
    status: CaseStatus;
    huRange?: { min: number; max: number };
}

export type CaseStatus = 'pending' | 'uploading' | 'uploaded' | 'processing' | 'ready' | 'error';

/**
 * Pipeline Step for processing visualization
 */
export interface PipelineStep {
    id: string;
    label: string;
    description?: string;
    status: PipelineStepStatus;
    duration?: number; // in milliseconds
}

export type PipelineStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

/**
 * Default pipeline steps matching the PRD specification
 * CT → Segmentation → SDF → Marching Cubes → Mesh
 */
export const PIPELINE_STEPS: PipelineStep[] = [
    {
        id: 'load_volume',
        label: 'CT Acquisition',
        description: 'Loading and validating DICOM/NIfTI data',
        status: 'pending'
    },
    {
        id: 'segmentation',
        label: 'Segmentation',
        description: 'Tissue region detection (threshold-based)',
        status: 'pending'
    },
    {
        id: 'sdf',
        label: 'Implicit Field (SDF)',
        description: 'Signed distance function computation',
        status: 'pending'
    },
    {
        id: 'mesh',
        label: 'Surface Extraction',
        description: 'Marching cubes mesh generation',
        status: 'pending'
    },
];

/**
 * Map backend stage names to frontend pipeline step IDs
 */
export const STAGE_ID_MAP: Record<string, string> = {
    'load_volume': 'load_volume',
    'segmentation': 'segmentation',
    'sdf': 'sdf',
    'mesh': 'mesh',
};

/**
 * Window/Level presets for CT visualization
 * Values in Hounsfield Units (HU)
 */
export interface WindowPreset {
    name: string;
    windowLevel: number; // Center
    windowWidth: number; // Range
}

export const WINDOW_PRESETS: Record<string, WindowPreset> = {
    LUNG: {
        name: 'Lung',
        windowLevel: -600,
        windowWidth: 1500,
    },
    SOFT_TISSUE: {
        name: 'Soft Tissue',
        windowLevel: 40,
        windowWidth: 400,
    },
    BONE: {
        name: 'Bone',
        windowLevel: 400,
        windowWidth: 1800,
    },
    BRAIN: {
        name: 'Brain',
        windowLevel: 40,
        windowWidth: 80,
    },
    LIVER: {
        name: 'Liver',
        windowLevel: 60,
        windowWidth: 150,
    },
};

export type WindowPresetKey = keyof typeof WINDOW_PRESETS;

/**
 * View modes for the main layout
 */
export type ViewMode = '2D' | '3D' | 'MPR' | 'MPR_3D';

/**
 * MPR (Multiplanar Reconstruction) view types
 */
export type MPRView = 'AXIAL' | 'SAGITTAL' | 'CORONAL';

/**
 * Crosshair position for synchronized MPR views
 * Represents the intersection point in 3D space (voxel indices)
 */
export interface CrosshairPosition {
    x: number; // Sagittal slice index
    y: number; // Coronal slice index  
    z: number; // Axial slice index
}

/**
 * Segmentation overlay configuration
 */
export interface SegmentationConfig {
    visible: boolean;
    opacity: number;
    lungColor: string;
    tumorColor: string;
}

export const DEFAULT_SEGMENTATION_CONFIG: SegmentationConfig = {
    visible: false,
    opacity: 0.5,
    lungColor: '#22c55e',
    tumorColor: '#ef4444',
};

/**
 * Volume data stored in GPU-ready format
 * For near-zero latency slice navigation
 */
export interface VolumeData {
    data: Int16Array; // Raw HU values
    dimensions: [number, number, number];
    spacing: [number, number, number];
}

/**
 * Mask data stored in GPU-ready format
 */
export interface MaskData {
    data: Uint8Array; // Binary mask values
    dimensions: [number, number, number];
}

/**
 * Slice data from API (JSON format)
 */
export interface SliceData {
    slice_index: number;
    hu_values: number[][];
    spacing_mm: { x: number; y: number };
}

/**
 * Mask slice data from API
 */
export interface MaskSliceData {
    slice_index: number;
    mask: number[][];
    sparse: boolean;
}

/**
 * Application state for viewer
 */
export interface ViewerState {
    viewMode: ViewMode;
    crosshair: CrosshairPosition;
    windowPreset: WindowPresetKey;
    customWindow?: { level: number; width: number };
    segmentation: SegmentationConfig;
    showWireframe: boolean;
    zoomLevel: number;
    panOffset: { x: number; y: number };
}

export const DEFAULT_VIEWER_STATE: ViewerState = {
    viewMode: '2D',
    crosshair: { x: 0, y: 0, z: 0 },
    windowPreset: 'SOFT_TISSUE',
    segmentation: DEFAULT_SEGMENTATION_CONFIG,
    showWireframe: false,
    zoomLevel: 1,
    panOffset: { x: 0, y: 0 },
};

/**
 * API Response Types
 */
export interface APIError {
    error: string;
    message: string;
    details?: Record<string, unknown>;
}
