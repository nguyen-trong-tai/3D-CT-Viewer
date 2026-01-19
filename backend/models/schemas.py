from pydantic import BaseModel
from typing import List, Optional, Tuple, Any

class CaseResponse(BaseModel):
    case_id: str
    status: str

class ProcessingResponse(BaseModel):
    case_id: str
    status: str

class StatusResponse(BaseModel):
    case_id: str
    status: str

class VolumeShape(BaseModel):
    x: int
    y: int
    z: int

class VoxelSpacing(BaseModel):
    x: float
    y: float
    z: float

class MetadataResponse(BaseModel):
    volume_shape: VolumeShape
    voxel_spacing_mm: VoxelSpacing
    num_slices: int

class SliceResponse(BaseModel):
    slice_index: int
    hu_values: List[List[float]]
    spacing_mm: dict

class MaskSliceResponse(BaseModel):
    slice_index: int
    mask: List[List[int]]
    sparse: bool

class ImplicitMetadataResponse(BaseModel):
    type: str = "signed_distance_function"
    grid_aligned: bool = True
    level_set: float = 0.0

class ErrorResponse(BaseModel):
    error: str
    details: Optional[str] = None
