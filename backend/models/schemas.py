"""
Pydantic Schemas for API Request/Response Models

These models define the contract between frontend and backend.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from .enums import CaseStatus, SegmentationType, ImplicitType


# ============================================================================
# Common Components
# ============================================================================

class VolumeShape(BaseModel):
    """3D volume dimensions in voxels."""
    x: int = Field(..., description="Width (number of voxels in X direction)")
    y: int = Field(..., description="Height (number of voxels in Y direction)")  
    z: int = Field(..., description="Depth/Slices (number of voxels in Z direction)")


class VoxelSpacing(BaseModel):
    """Voxel spacing in physical units (millimeters)."""
    x: float = Field(..., description="Spacing in X direction (mm)")
    y: float = Field(..., description="Spacing in Y direction (mm)")
    z: float = Field(..., description="Spacing in Z direction (mm) - slice thickness")


class Spacing2D(BaseModel):
    """2D spacing for slice data."""
    x: float
    y: float


# ============================================================================
# Case Management
# ============================================================================

class CaseResponse(BaseModel):
    """Response after case creation/upload."""
    case_id: str = Field(..., description="Unique identifier for the case")
    status: str = Field(..., description="Current case status")
    
    class Config:
        json_schema_extra = {
            "example": {
                "case_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "uploaded"
            }
        }


class StatusResponse(BaseModel):
    """Response for case status queries."""
    case_id: str
    status: str
    viewer_ready: bool = Field(
        default=False,
        description="Whether the case has enough volume artifacts for the 2D viewer to open",
    )
    volume_ready: bool = Field(
        default=False,
        description="Whether the full-resolution CT volume artifact is available",
    )
    message: Optional[str] = Field(None, description="Additional status information")
    expires_at: Optional[str] = Field(None, description="UTC timestamp when the case will be auto-deleted")
    current_stage: Optional[str] = Field(None, description="Current backend stage name when available")
    progress_percent: Optional[float] = Field(None, description="Best-effort overall progress percentage")
    
    class Config:
        json_schema_extra = {
            "example": {
                "case_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "ready",
                "viewer_ready": True,
                "volume_ready": True,
                "message": "All processing complete",
                "expires_at": "2026-03-25T12:00:00",
                "current_stage": "mesh",
                "progress_percent": 100.0,
            }
        }


class CaseEventStageSnapshot(BaseModel):
    """Pipeline stage state embedded inside case SSE events."""
    name: str
    status: str
    duration_seconds: Optional[float] = None
    message: Optional[str] = None
    output_shape: Optional[Any] = None


class CaseEventSnapshot(BaseModel):
    """Compact pipeline snapshot embedded inside case SSE events."""
    overall_status: str
    viewer_ready: bool = Field(
        default=False,
        description="Whether the case can already be opened in the 2D viewer",
    )
    volume_ready: bool = Field(
        default=False,
        description="Whether the full-resolution CT volume is available",
    )
    stages: List[CaseEventStageSnapshot] = Field(default_factory=list)
    artifacts: Dict[str, bool] = Field(default_factory=dict)


class CaseEventPayload(BaseModel):
    """Event payload emitted over the case SSE stream."""
    type: str = Field(..., description="Event category")
    case_id: str = Field(..., description="Case identifier")
    status: Optional[str] = Field(None, description="Overall case status when applicable")
    viewer_ready: Optional[bool] = Field(None, description="Whether the viewer can open immediately")
    volume_ready: Optional[bool] = Field(None, description="Whether the full-resolution volume is ready")
    stage: Optional[str] = Field(None, description="Pipeline stage name for pipeline events")
    artifact: Optional[str] = Field(None, description="Artifact name for artifact readiness events")
    message: Optional[str] = Field(None, description="Human-readable event message")
    progress_percent: Optional[float] = Field(None, description="Best-effort progress percentage")
    current_stage: Optional[str] = Field(None, description="Current backend stage label")
    duration_seconds: Optional[float] = Field(None, description="Stage duration when available")
    snapshot: Optional[CaseEventSnapshot] = Field(
        None,
        description="Latest pipeline/artifact snapshot so clients can reconcile state without extra polling",
    )
    timestamp: str = Field(..., description="UTC ISO-8601 timestamp for the event")


class ProcessingResponse(BaseModel):
    """Response after triggering processing."""
    case_id: str
    status: str
    estimated_time_seconds: Optional[float] = Field(
        None, 
        description="Estimated processing time in seconds"
    )


# ============================================================================
# CT Data & Metadata
# ============================================================================

class MetadataResponse(BaseModel):
    """CT volume metadata response."""
    volume_shape: VolumeShape = Field(..., description="Volume dimensions in voxels")
    voxel_spacing_mm: VoxelSpacing = Field(..., description="Voxel spacing in mm")
    num_slices: int = Field(..., description="Total number of slices (Z dimension)")
    hu_range: Optional[Dict[str, float]] = Field(
        None,
        description="HU value range (min, max)"
    )
    orientation: Optional[str] = Field(
        None,
        description="Image orientation if available"
    )
    preview_available: bool = Field(
        default=False,
        description="Whether a downsampled preview volume is available"
    )
    preview_volume_shape: Optional[VolumeShape] = Field(
        None,
        description="Preview volume dimensions in voxels when available"
    )
    preview_voxel_spacing_mm: Optional[VoxelSpacing] = Field(
        None,
        description="Preview voxel spacing in mm when available"
    )
    preview_mask_available: bool = Field(
        default=False,
        description="Whether a downsampled preview mask is available"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "volume_shape": {"x": 512, "y": 512, "z": 200},
                "voxel_spacing_mm": {"x": 0.5, "y": 0.5, "z": 1.0},
                "num_slices": 200,
                "hu_range": {"min": -1024, "max": 3071},
                "preview_available": True,
                "preview_volume_shape": {"x": 256, "y": 256, "z": 100},
                "preview_voxel_spacing_mm": {"x": 1.0, "y": 1.0, "z": 2.0},
                "preview_mask_available": True
            }
        }


class SliceResponse(BaseModel):
    """Single CT slice data response."""
    slice_index: int = Field(..., description="Z-axis slice index (0-indexed)")
    hu_values: List[List[float]] = Field(
        ..., 
        description="2D array of HU values [rows][cols] = [Y][X]"
    )
    spacing_mm: Spacing2D = Field(..., description="Pixel spacing in mm")
    
    class Config:
        json_schema_extra = {
            "example": {
                "slice_index": 100,
                "hu_values": [[-1024, -1000], [-900, -800]],
                "spacing_mm": {"x": 0.5, "y": 0.5}
            }
        }


# ============================================================================
# Segmentation
# ============================================================================

class MaskSliceResponse(BaseModel):
    """Single labeled segmentation mask slice response."""
    slice_index: int = Field(..., description="Z-axis slice index (0-indexed)")
    mask: List[List[int]] = Field(
        ...,
        description="2D labeled mask [rows][cols] = [Y][X]. Values: 0=background, 1=left_lung, 2=right_lung, 3=nodule"
    )
    sparse: bool = Field(
        ...,
        description="True if slice contains no segmentation labels (all zeros)"
    )
    labels_present: List[int] = Field(
        default_factory=list,
        description="Sorted segmentation label ids present on the slice (excluding background)",
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "slice_index": 100,
                "mask": [[0, 0, 1], [0, 1, 1], [1, 1, 0]],
                "sparse": False
            }
        }


class SegmentationInfo(BaseModel):
    """Information about available segmentations."""
    type: SegmentationType
    available: bool = True
    voxel_count: Optional[int] = Field(None, description="Number of segmented voxels")


class SegmentationLabel(BaseModel):
    """Metadata describing a labeled segmentation component."""
    label_id: int = Field(..., description="Voxel label id stored in the mask volume")
    key: str = Field(..., description="Stable component key")
    display_name: str = Field(..., description="Human-readable label name")
    color: str = Field(..., description="Default hex color used in 2D and 3D viewers")
    available: bool = Field(default=True, description="Whether this component is available for the case")
    visible_by_default: bool = Field(default=True, description="Whether the UI should enable this component by default")
    render_2d: bool = Field(default=True, description="Whether to render this component in slice viewers")
    render_3d: bool = Field(default=True, description="Whether to render this component in 3D viewers")
    voxel_count: int = Field(default=0, description="Voxel count for this component")
    mesh_component_name: Optional[str] = Field(
        default=None,
        description="Stable geometry name expected inside the GLB scene",
    )


class SegmentationManifestResponse(BaseModel):
    """Manifest describing all labeled segmentation components for a case."""
    case_id: str
    labels: List[SegmentationLabel] = Field(default_factory=list)
    has_labeled_mask: bool = Field(
        default=True,
        description="Whether the stored mask volume uses multi-label semantics",
    )


# ============================================================================
# Implicit Representation
# ============================================================================

class ImplicitMetadataResponse(BaseModel):
    """Metadata about the implicit representation (SDF)."""
    type: str = Field(
        default=ImplicitType.SDF.value,
        description="Type of implicit representation"
    )
    grid_aligned: bool = Field(
        default=True,
        description="Whether the SDF is aligned to the CT voxel grid"
    )
    level_set: float = Field(
        default=0.0,
        description="The level set value used for surface extraction"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "type": "signed_distance_function",
                "grid_aligned": True,
                "level_set": 0.0
            }
        }


# ============================================================================
# 3D Mesh
# ============================================================================

class MeshInfo(BaseModel):
    """Information about generated 3D mesh."""
    vertex_count: int = Field(..., description="Number of vertices")
    face_count: int = Field(..., description="Number of triangular faces")
    format: str = Field(default="obj", description="Mesh file format")
    physical_bounds_mm: Optional[Dict[str, float]] = Field(
        None,
        description="Bounding box in physical coordinates (mm)"
    )


# ============================================================================
# Pipeline & Artifacts
# ============================================================================

class PipelineStage(BaseModel):
    """Information about a single pipeline stage."""
    name: str
    status: str  # "pending", "running", "completed", "failed"
    duration_seconds: Optional[float] = None


class PipelineStatus(BaseModel):
    """Full pipeline execution status."""
    case_id: str
    overall_status: str
    stages: List[PipelineStage]
    total_duration_seconds: Optional[float] = None


class ArtifactList(BaseModel):
    """List of available artifacts for a case."""
    case_id: str
    artifacts: Dict[str, bool] = Field(
        ...,
        description="Map of artifact name to availability"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "case_id": "abc123",
                "artifacts": {
                    "ct_volume": True,
                    "segmentation_mask": True,
                    "sdf": True,
                    "mesh": True
                }
            }
        }


class ArtifactUrlResponse(BaseModel):
    """Presigned or resolved download URL for an artifact."""
    case_id: str
    artifact: str
    url: str
    expires_in_seconds: int


# ============================================================================ 
# Error Handling
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str = Field(..., description="Error type or code")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(
        None, 
        description="Additional error details"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "CASE_NOT_FOUND",
                "message": "The requested case does not exist",
                "details": {"case_id": "invalid-id"}
            }
        }


# ============================================================================
# Bulk Data Transfer
# ============================================================================

class VolumeDataRequest(BaseModel):
    """Request for bulk volume data."""
    format: str = Field(
        default="raw",
        description="Data format: 'raw' (binary), 'base64', 'compressed'"
    )
    dtype: str = Field(
        default="int16",
        description="Data type: 'int16' for HU, 'uint8' for masks"
    )


class BulkUploadStatus(BaseModel):
    """Status of batch/bulk file upload."""
    case_id: str
    files_received: int
    total_expected: Optional[int] = None
    status: str


class BatchInitResponse(CaseResponse):
    """Extended response for initializing a batch upload session."""
    storage_kind: str = Field(..., description="Storage backend used for the staged upload")
    direct_upload_enabled: bool = Field(
        default=False,
        description="Whether the client should upload files directly to object storage",
    )
    preferred_upload_layout: str = Field(
        default="archive_shards",
        description="Recommended client-side packaging strategy for large folder uploads",
    )
    upload_url_ttl_seconds: Optional[int] = Field(
        default=None,
        description="TTL for presigned upload URLs when direct upload is enabled",
    )
    recommended_upload_concurrency: Optional[int] = Field(
        default=None,
        description="Suggested client-side concurrency for direct uploads",
    )


class BatchUploadFileDescriptor(BaseModel):
    """Client-side description of a file that needs an upload target."""
    client_id: str = Field(..., description="Stable client-side identifier for matching files to targets")
    filename: str = Field(..., description="Original file name")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes")
    content_type: Optional[str] = Field(default=None, description="Browser-reported content type")


class BatchUploadTarget(BaseModel):
    """Presigned target for a single direct-to-object-store upload."""
    client_id: str
    filename: str
    object_key: str
    upload_url: str
    method: str = Field(default="PUT", description="HTTP method required by the upload target")


class BatchUploadPresignRequest(BaseModel):
    """Request one upload target per file in a chunk."""
    files: List[BatchUploadFileDescriptor]


class BatchUploadPresignResponse(BaseModel):
    """Presigned upload targets for a chunk of files."""
    case_id: str
    expires_in_seconds: int
    targets: List[BatchUploadTarget]


class BatchUploadCompleteItem(BaseModel):
    """Single completed object-store upload recorded against the session."""
    client_id: str
    filename: str
    object_key: str


class BatchUploadCompleteRequest(BaseModel):
    """Mark a chunk of direct uploads as committed."""
    uploads: List[BatchUploadCompleteItem]


class BatchUploadProgressResponse(BaseModel):
    """Progress response for batch upload staging."""
    case_id: str
    files_saved: int
    total_received: int
