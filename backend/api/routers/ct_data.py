"""
CT Data Router — Volume, Slice, and Metadata endpoints

Handles serving CT volume data (binary & JSON) and metadata.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
import numpy as np
import json

from api.dependencies import get_artifact_service, get_repository
from config import settings
from models import ArtifactUrlResponse, MetadataResponse, SliceResponse, Spacing2D, VolumeShape, VoxelSpacing
from services.artifact_service import ArtifactService
from storage.repository import CaseRepository


router = APIRouter(tags=["CT Data"])


@router.get("/cases/{case_id}/metadata", response_model=MetadataResponse, summary="Get CT metadata")
async def get_metadata(
    case_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Get metadata about the CT volume (dimensions, spacing, etc.)."""
    try:
        meta = artifact_service.get_ct_metadata(case_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Metadata not found")

    shape = meta["shape"]
    spacing = meta["spacing"]
    hu_range = meta.get("hu_range", {"min": -1024, "max": 3071})
    preview_shape = meta.get("preview_shape")
    preview_spacing = meta.get("preview_spacing")

    return MetadataResponse(
        volume_shape=VolumeShape(x=shape[0], y=shape[1], z=shape[2]),
        voxel_spacing_mm=VoxelSpacing(x=spacing[0], y=spacing[1], z=spacing[2]),
        num_slices=shape[2],
        hu_range=hu_range,
        preview_available=bool(meta.get("preview_available")),
        preview_volume_shape=VolumeShape(x=preview_shape[0], y=preview_shape[1], z=preview_shape[2]) if preview_shape else None,
        preview_voxel_spacing_mm=VoxelSpacing(x=preview_spacing[0], y=preview_spacing[1], z=preview_spacing[2]) if preview_spacing else None,
        preview_mask_available=bool(meta.get("preview_mask_available")),
    )


@router.get("/cases/{case_id}/extra-metadata", summary="Get extra metadata")
async def get_extra_metadata(
    case_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Get extra metadata (patient info, study details, etc.) if available."""
    from fastapi.responses import JSONResponse
    try:
        meta = artifact_service.get_extra_metadata(case_id)
    except FileNotFoundError:
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
    repo.sync_for_read(scope="artifact")
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


@router.get("/cases/{case_id}/ct/preview-volume", summary="Get preview CT volume")
async def get_ct_preview_volume(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get the downsampled CT preview volume as raw binary data (int16)."""
    repo.sync_for_read(scope="artifact")
    volume = repo.load_ct_preview_volume(case_id)
    meta = repo.load_ct_metadata(case_id)

    if volume is None or meta is None:
        raise HTTPException(status_code=404, detail="Preview volume not found")

    spacing = meta.get("preview_spacing") or meta.get("spacing")
    headers = {
        "X-Volume-Shape": json.dumps(list(volume.shape)),
        "X-Volume-Spacing": json.dumps(spacing),
        "Content-Type": "application/octet-stream",
    }

    return Response(content=volume.astype(np.int16).tobytes(), headers=headers)


@router.get("/cases/{case_id}/ct/volume-url", response_model=ArtifactUrlResponse, summary="Get CT volume download URL")
async def get_ct_volume_url(
    case_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Get a presigned download URL for the full CT volume stored in R2."""
    try:
        url = artifact_service.get_artifact_download_url(
            case_id,
            "ct_volume",
            expires_in_seconds=settings.ARTIFACT_URL_TTL_SECONDS,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="CT volume URL not available")

    return ArtifactUrlResponse(
        case_id=case_id,
        artifact="ct_volume",
        url=url,
        expires_in_seconds=settings.ARTIFACT_URL_TTL_SECONDS,
    )


@router.get("/cases/{case_id}/ct/preview-volume-url", response_model=ArtifactUrlResponse, summary="Get preview CT volume download URL")
async def get_ct_preview_volume_url(
    case_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Get a presigned download URL for the preview CT volume stored in R2."""
    try:
        url = artifact_service.get_artifact_download_url(
            case_id,
            "ct_volume_preview",
            expires_in_seconds=settings.ARTIFACT_URL_TTL_SECONDS,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Preview CT volume URL not available")

    return ArtifactUrlResponse(
        case_id=case_id,
        artifact="ct_volume_preview",
        url=url,
        expires_in_seconds=settings.ARTIFACT_URL_TTL_SECONDS,
    )


@router.get("/cases/{case_id}/ct/slices/{slice_index}", response_model=SliceResponse, summary="Get single CT slice")
async def get_slice(
    case_id: str,
    slice_index: int,
    repo: CaseRepository = Depends(get_repository)
):
    """Get a single CT slice as HU values."""
    repo.sync_for_read(scope="artifact")
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
