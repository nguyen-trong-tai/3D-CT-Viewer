"""
Processing Router — Pipeline and Segmentation endpoints

Handles triggering the processing pipeline and serving mask/SDF data.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse, Response
import numpy as np
import json
import asyncio

from api.dependencies import get_artifact_service, get_case_service, get_pipeline_service, get_repository
from config import settings
from models import ArtifactUrlResponse, ProcessingResponse, MaskSliceResponse, ImplicitMetadataResponse
from models.enums import CaseStatus
from services.artifact_service import ArtifactService
from services.case_service import CaseService
from services.pipeline import PipelineService
from storage.repository import CaseRepository
from workers.runtime import spawn_process_case


router = APIRouter(tags=["Processing"])


@router.post("/cases/{case_id}/process", response_model=ProcessingResponse, summary="Start processing")
async def trigger_processing(
    case_id: str,
    repo: CaseRepository = Depends(get_repository),
    case_service: CaseService = Depends(get_case_service),
    pipeline: PipelineService = Depends(get_pipeline_service),
):
    """
    Trigger the processing pipeline for a case.
    Processing runs in a thread pool to avoid blocking async requests,
    or runs on a dedicated Modal worker if deployed.
    Use GET /cases/{case_id}/status to check progress.
    """
    repo.sync_for_read(scope="state")
    state = case_service.can_start_processing(case_id)
    if state == "missing":
        raise HTTPException(status_code=404, detail="Case not found")

    if state == "processing":
        return ProcessingResponse(
            case_id=case_id,
            status="already_processing",
            estimated_time_seconds=15.0
        )

    if not spawn_process_case(case_id):
        # Run CPU-heavy pipeline in a thread to keep async event loop free
        asyncio.get_event_loop().run_in_executor(None, pipeline.process_case, case_id)

    return ProcessingResponse(
        case_id=case_id,
        status="processing_started",
        estimated_time_seconds=15.0
    )


@router.get("/cases/{case_id}/pipeline", summary="Get detailed pipeline status")
async def get_pipeline_status(
    case_id: str,
    repo: CaseRepository = Depends(get_repository),
    pipeline: PipelineService = Depends(get_pipeline_service)
):
    """Get detailed status of pipeline stages and available artifacts."""
    repo.sync_for_read(scope="all")
    return JSONResponse(content=pipeline.get_pipeline_status(case_id))


@router.get("/cases/{case_id}/mask/volume", summary="Get full segmentation mask")
async def get_mask_volume(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get the full segmentation mask as raw binary data (uint8)."""
    repo.sync_for_read(scope="artifact")
    mask = repo.load_mask(case_id)
    if mask is None:
        raise HTTPException(status_code=404, detail="Mask not found")

    meta = repo.load_ct_metadata(case_id)
    mask_bytes = mask.astype(np.uint8).tobytes()

    headers = {
        "X-Volume-Shape": json.dumps(list(mask.shape)),
        "X-Volume-Spacing": json.dumps(meta["spacing"]),
        "Content-Type": "application/octet-stream",
    }

    return Response(content=mask_bytes, headers=headers)


@router.get("/cases/{case_id}/mask/preview-volume", summary="Get preview segmentation mask")
async def get_mask_preview_volume(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get the downsampled segmentation mask as raw binary data (uint8)."""
    repo.sync_for_read(scope="artifact")
    mask = repo.load_mask_preview(case_id)
    if mask is None:
        raise HTTPException(status_code=404, detail="Preview mask not found")

    meta = repo.load_ct_metadata(case_id) or {}
    headers = {
        "X-Volume-Shape": json.dumps(list(mask.shape)),
        "X-Volume-Spacing": json.dumps(meta.get("preview_spacing") or meta.get("spacing") or [1, 1, 1]),
        "Content-Type": "application/octet-stream",
    }

    return Response(content=mask.astype(np.uint8).tobytes(), headers=headers)


@router.get("/cases/{case_id}/mask/volume-url", response_model=ArtifactUrlResponse, summary="Get mask volume download URL")
async def get_mask_volume_url(
    case_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Get a presigned download URL for the full segmentation mask stored in R2."""
    try:
        url = artifact_service.get_artifact_download_url(
            case_id,
            "segmentation_mask",
            expires_in_seconds=settings.ARTIFACT_URL_TTL_SECONDS,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Mask volume URL not available")

    return ArtifactUrlResponse(
        case_id=case_id,
        artifact="segmentation_mask",
        url=url,
        expires_in_seconds=settings.ARTIFACT_URL_TTL_SECONDS,
    )


@router.get("/cases/{case_id}/mask/preview-volume-url", response_model=ArtifactUrlResponse, summary="Get preview mask volume download URL")
async def get_mask_preview_volume_url(
    case_id: str,
    artifact_service: ArtifactService = Depends(get_artifact_service),
):
    """Get a presigned download URL for the preview segmentation mask stored in R2."""
    try:
        url = artifact_service.get_artifact_download_url(
            case_id,
            "segmentation_mask_preview",
            expires_in_seconds=settings.ARTIFACT_URL_TTL_SECONDS,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Preview mask volume URL not available")

    return ArtifactUrlResponse(
        case_id=case_id,
        artifact="segmentation_mask_preview",
        url=url,
        expires_in_seconds=settings.ARTIFACT_URL_TTL_SECONDS,
    )


@router.get("/cases/{case_id}/mask/slices/{slice_index}", response_model=MaskSliceResponse, summary="Get single mask slice")
async def get_mask_slice(
    case_id: str,
    slice_index: int,
    repo: CaseRepository = Depends(get_repository)
):
    """Get a single segmentation mask slice."""
    repo.sync_for_read(scope="artifact")
    mask = repo.load_mask_mmap(case_id)
    if mask is None:
        raise HTTPException(status_code=404, detail="Mask not found")

    if slice_index < 0 or slice_index >= mask.shape[2]:
        raise HTTPException(
            status_code=404,
            detail=f"Slice index out of bounds. Valid range: 0-{mask.shape[2]-1}"
        )

    mask_slice = mask[:, :, slice_index].T
    is_sparse = bool(np.sum(mask_slice) == 0)

    return MaskSliceResponse(
        slice_index=slice_index,
        mask=mask_slice.tolist(),
        sparse=is_sparse
    )


@router.get("/cases/{case_id}/implicit", response_model=ImplicitMetadataResponse, summary="Get implicit representation info")
async def get_implicit_info(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get metadata about the implicit representation (SDF)."""
    repo.sync_for_read(scope="all")
    status = repo.get_status(case_id)

    if status not in [CaseStatus.READY.value, "ready"]:
        raise HTTPException(status_code=400, detail="Processing not complete")

    if not repo.sdf_exists(case_id):
        raise HTTPException(status_code=404, detail="SDF not available")

    return ImplicitMetadataResponse()
