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
    ArtifactUrlResponse,
    ErrorResponse,
    VolumeDataRequest,
    BulkUploadStatus,
    BatchInitResponse,
    BatchUploadFileDescriptor,
    BatchUploadTarget,
    BatchUploadPresignRequest,
    BatchUploadPresignResponse,
    BatchUploadCompleteItem,
    BatchUploadCompleteRequest,
    BatchUploadProgressResponse,
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
    "ArtifactUrlResponse",
    "ErrorResponse",
    "VolumeDataRequest",
    "BulkUploadStatus",
    "BatchInitResponse",
    "BatchUploadFileDescriptor",
    "BatchUploadTarget",
    "BatchUploadPresignRequest",
    "BatchUploadPresignResponse",
    "BatchUploadCompleteItem",
    "BatchUploadCompleteRequest",
    "BatchUploadProgressResponse",
    # Enums
    "CaseStatus",
    "SegmentationType",
    "ImplicitType",
    "FileFormat",
]
