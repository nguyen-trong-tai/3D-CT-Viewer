"""
CT Data Router — Volume, Slice, and Metadata endpoints

Handles serving CT volume data (binary & JSON) and metadata.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
import numpy as np
import json

from models import MetadataResponse, SliceResponse, Spacing2D, VolumeShape, VoxelSpacing
from storage.repository import CaseRepository
from api.dependencies import get_repository


router = APIRouter(tags=["CT Data"])


@router.get("/cases/{case_id}/metadata", response_model=MetadataResponse, summary="Get CT metadata")
async def get_metadata(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get metadata about the CT volume (dimensions, spacing, etc.)."""
    meta = repo.load_ct_metadata(case_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Metadata not found")

    shape = meta["shape"]
    spacing = meta["spacing"]
    hu_range = meta.get("hu_range", {"min": -1024, "max": 3071})

    return MetadataResponse(
        volume_shape=VolumeShape(x=shape[0], y=shape[1], z=shape[2]),
        voxel_spacing_mm=VoxelSpacing(x=spacing[0], y=spacing[1], z=spacing[2]),
        num_slices=shape[2],
        hu_range=hu_range
    )


@router.get("/cases/{case_id}/extra-metadata", summary="Get extra metadata")
async def get_extra_metadata(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get extra metadata (patient info, study details, etc.) if available."""
    from fastapi.responses import JSONResponse
    meta = repo.load_extra_metadata(case_id)
    if not meta:
        raise HTTPException(status_code=404, detail="No extra metadata available")
    return JSONResponse(content=meta)


@router.get("/cases/{case_id}/ct/volume", summary="Get full CT volume")
async def get_ct_volume(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """
    Get the full CT volume as raw binary data (int16).
    Response is raw binary data with shape and spacing in headers.
    """
    volume = repo.load_ct_volume(case_id)
    meta = repo.load_ct_metadata(case_id)

    if volume is None or meta is None:
        raise HTTPException(status_code=404, detail="Volume not found")

    volume_bytes = volume.astype(np.int16).tobytes()

    headers = {
        "X-Volume-Shape": json.dumps(meta["shape"]),
        "X-Volume-Spacing": json.dumps(meta["spacing"]),
        "Content-Type": "application/octet-stream",
    }

    return Response(content=volume_bytes, headers=headers)


@router.get("/cases/{case_id}/ct/slices/{slice_index}", response_model=SliceResponse, summary="Get single CT slice")
async def get_slice(
    case_id: str,
    slice_index: int,
    repo: CaseRepository = Depends(get_repository)
):
    """Get a single CT slice as HU values."""
    volume = repo.load_ct_volume_mmap(case_id)
    if volume is None:
        raise HTTPException(status_code=404, detail="Volume not found")

    if slice_index < 0 or slice_index >= volume.shape[2]:
        raise HTTPException(
            status_code=404,
            detail=f"Slice index out of bounds. Valid range: 0-{volume.shape[2]-1}"
        )

    slice_data = volume[:, :, slice_index].T
    meta = repo.load_ct_metadata(case_id)
    spacing = meta["spacing"]

    return SliceResponse(
        slice_index=slice_index,
        hu_values=slice_data.tolist(),
        spacing_mm=Spacing2D(x=spacing[0], y=spacing[1])
    )
