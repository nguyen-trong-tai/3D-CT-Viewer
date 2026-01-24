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
    message: Optional[str] = Field(None, description="Additional status information")
    
    class Config:
        json_schema_extra = {
            "example": {
                "case_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "ready",
                "message": "All processing complete"
            }
        }


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
    
    class Config:
        json_schema_extra = {
            "example": {
                "volume_shape": {"x": 512, "y": 512, "z": 200},
                "voxel_spacing_mm": {"x": 0.5, "y": 0.5, "z": 1.0},
                "num_slices": 200,
                "hu_range": {"min": -1024, "max": 3071}
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
    """Single segmentation mask slice response."""
    slice_index: int = Field(..., description="Z-axis slice index (0-indexed)")
    mask: List[List[int]] = Field(
        ..., 
        description="2D binary mask [rows][cols] = [Y][X]. Values: 0=background, 1=segmented"
    )
    sparse: bool = Field(
        ..., 
        description="True if slice contains no segmentation (all zeros)"
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
