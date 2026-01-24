"""
Enums for the CT Imaging Platform

Defines status values and other enumerated types used across the application.
"""

from enum import Enum


class CaseStatus(str, Enum):
    """
    Case processing status values.
    
    State machine flow:
    PENDING -> UPLOADING -> UPLOADED -> PROCESSING -> READY
                                                  |-> ERROR
    """
    PENDING = "pending"           # Case created, awaiting file upload
    UPLOADING = "uploading"       # File upload in progress
    UPLOADED = "uploaded"         # Upload complete, ready for processing
    PROCESSING = "processing"     # AI pipeline execution ongoing
    READY = "ready"               # All processing complete, artifacts available
    ERROR = "error"               # Processing failed
    

class SegmentationType(str, Enum):
    """Types of segmentation targets."""
    LUNG = "lung"
    TUMOR = "tumor"
    BONE = "bone"
    SOFT_TISSUE = "soft_tissue"


class ImplicitType(str, Enum):
    """Types of implicit representations."""
    SDF = "signed_distance_function"


class FileFormat(str, Enum):
    """Supported input file formats."""
    DICOM = "dicom"
    NIFTI = "nifti"
    NIFTI_GZ = "nifti_gz"
