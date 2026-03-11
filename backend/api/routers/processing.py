"""
Processing Router — Pipeline and Segmentation endpoints

Handles triggering the processing pipeline and serving mask/SDF data.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse, Response
import numpy as np
import json
import asyncio

from models import ProcessingResponse, MaskSliceResponse, ImplicitMetadataResponse
from models.enums import CaseStatus
from storage.repository import CaseRepository
from services.pipeline import PipelineService
from api.dependencies import get_repository, get_pipeline_service


router = APIRouter(tags=["Processing"])


@router.post("/cases/{case_id}/process", response_model=ProcessingResponse, summary="Start AI processing")
async def trigger_processing(
    case_id: str,
    repo: CaseRepository = Depends(get_repository),
    pipeline: PipelineService = Depends(get_pipeline_service)
):
    """
    Trigger the AI processing pipeline for a case.
    Processing runs in a thread pool to avoid blocking async requests.
    Use GET /cases/{case_id}/status to check progress.
    """
    status = repo.get_status(case_id)

    if status == "error" and not repo.case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")

    if status == CaseStatus.PROCESSING.value:
        return ProcessingResponse(
            case_id=case_id,
            status="already_processing",
            estimated_time_seconds=15.0
        )

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
    pipeline: PipelineService = Depends(get_pipeline_service)
):
    """Get detailed status of pipeline stages and available artifacts."""
    return JSONResponse(content=pipeline.get_pipeline_status(case_id))


@router.get("/cases/{case_id}/mask/volume", summary="Get full segmentation mask")
async def get_mask_volume(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get the full segmentation mask as raw binary data (uint8)."""
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


@router.get("/cases/{case_id}/mask/slices/{slice_index}", response_model=MaskSliceResponse, summary="Get single mask slice")
async def get_mask_slice(
    case_id: str,
    slice_index: int,
    repo: CaseRepository = Depends(get_repository)
):
    """Get a single segmentation mask slice."""
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
    status = repo.get_status(case_id)

    if status not in [CaseStatus.READY.value, "ready"]:
        raise HTTPException(status_code=400, detail="Processing not complete")

    if not repo.sdf_exists(case_id):
        raise HTTPException(status_code=404, detail="SDF not available")

    return ImplicitMetadataResponse()
