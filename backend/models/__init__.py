"""
Models Package

Contains Pydantic schemas and enums for the CT Imaging Platform.
"""

from .schemas import (
    VolumeShape,
    VoxelSpacing,
    Spacing2D,
    CaseResponse,
    StatusResponse,
    ProcessingResponse,
    MetadataResponse,
    SliceResponse,
    MaskSliceResponse,
    SegmentationInfo,
    ImplicitMetadataResponse,
    MeshInfo,
    PipelineStage,
    PipelineStatus,
    ArtifactList,
    ErrorResponse,
    VolumeDataRequest,
    BulkUploadStatus,
)

from .enums import (
    CaseStatus,
    SegmentationType,
    ImplicitType,
    FileFormat,
)

__all__ = [
    # Schemas
    "VolumeShape",
    "VoxelSpacing",
    "Spacing2D",
    "CaseResponse",
    "StatusResponse",
    "ProcessingResponse",
    "MetadataResponse",
    "SliceResponse", 
    "MaskSliceResponse",
    "SegmentationInfo",
    "ImplicitMetadataResponse",
    "MeshInfo",
    "PipelineStage",
    "PipelineStatus",
    "ArtifactList",
    "ErrorResponse",
    "VolumeDataRequest",
    "BulkUploadStatus",
    # Enums
    "CaseStatus",
    "SegmentationType",
    "ImplicitType",
    "FileFormat",
]
