"""
Cases Router - Upload and Case Management

Handles file uploads, batch uploads, and case lifecycle.
"""

from __future__ import annotations

import json
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_case_service, get_upload_service
from models import (
    ArtifactList,
    BatchInitResponse,
    BatchUploadCompleteRequest,
    BatchUploadPresignRequest,
    BatchUploadPresignResponse,
    BatchUploadProgressResponse,
    CaseResponse,
    StatusResponse,
)
from services.case_service import CaseService
from services.upload_service import UploadService


router = APIRouter(tags=["Cases"])


async def _extract_optional_metadata(request: Request) -> Optional[str]:
    """Parse optional metadata from form or JSON requests without hard-failing on empty bodies."""
    content_type = (request.headers.get("content-type") or "").lower()

    try:
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            metadata = form.get("metadata")
            return str(metadata) if metadata is not None else None

        if "application/json" in content_type:
            payload = await request.json()
            if isinstance(payload, dict) and "metadata" in payload:
                metadata = payload["metadata"]
                if isinstance(metadata, str):
                    return metadata
                return json.dumps(metadata)
    except Exception:
        return None

    return None


@router.post("/cases", response_model=CaseResponse, summary="Upload a CT file")
async def upload_case(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    upload_service: UploadService = Depends(get_upload_service),
):
    """Upload a single CT file (ZIP containing DICOM series or NIfTI file)."""
    payload = await run_in_threadpool(upload_service.upload_case, background_tasks, file)
    return CaseResponse(**payload)


@router.post("/cases/dicom", response_model=CaseResponse, summary="Upload DICOM files directly")
async def upload_dicom_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    metadata: Optional[str] = Form(None),
    upload_service: UploadService = Depends(get_upload_service),
):
    """Upload multiple DICOM files in a single request. Processed in background."""
    payload = await run_in_threadpool(upload_service.upload_dicom_files, background_tasks, files, metadata)
    return CaseResponse(**payload)


@router.post("/cases/batch/init", response_model=BatchInitResponse, summary="Initialize batch upload")
async def init_batch_upload(upload_service: UploadService = Depends(get_upload_service)):
    """Initialize a batch upload session for uploading DICOM files in chunks."""
    payload = await run_in_threadpool(upload_service.init_batch_upload)
    return BatchInitResponse(**payload)


@router.post("/cases/batch/{case_id}/files/presign", response_model=BatchUploadPresignResponse, summary="Create direct upload targets")
async def presign_batch_uploads(
    case_id: str,
    body: BatchUploadPresignRequest,
    upload_service: UploadService = Depends(get_upload_service),
):
    """Create presigned object-store upload targets for a batch chunk."""
    payload = await run_in_threadpool(
        upload_service.prepare_batch_uploads,
        case_id,
        [file.model_dump() for file in body.files],
    )
    return BatchUploadPresignResponse(**payload)


@router.post("/cases/batch/{case_id}/files/complete", response_model=BatchUploadProgressResponse, summary="Record completed direct uploads")
async def complete_batch_uploads(
    case_id: str,
    body: BatchUploadCompleteRequest,
    upload_service: UploadService = Depends(get_upload_service),
):
    """Record successfully uploaded object keys against the active batch session."""
    payload = await run_in_threadpool(
        upload_service.complete_batch_uploads,
        case_id,
        [upload.model_dump() for upload in body.uploads],
    )
    return BatchUploadProgressResponse(**payload)


@router.post("/cases/batch/{case_id}/files", response_model=BatchUploadProgressResponse, summary="Upload batch files")
async def upload_batch_files(
    case_id: str,
    files: List[UploadFile] = File(...),
    upload_service: UploadService = Depends(get_upload_service),
):
    """Upload files to an existing batch session."""
    payload = await run_in_threadpool(upload_service.upload_batch_files, case_id, files)
    return BatchUploadProgressResponse(**payload)


@router.post("/cases/batch/{case_id}/finalize", response_model=CaseResponse, summary="Finalize batch upload")
async def finalize_batch_upload(
    case_id: str,
    background_tasks: BackgroundTasks,
    request: Request,
    upload_service: UploadService = Depends(get_upload_service),
):
    """Process all uploaded files and create the CT volume in the background."""
    metadata = await _extract_optional_metadata(request)
    payload = await run_in_threadpool(upload_service.finalize_batch_upload, case_id, background_tasks, metadata)
    return CaseResponse(**payload)


@router.get("/cases/{case_id}/status", response_model=StatusResponse, summary="Get case status")
async def get_status(
    case_id: str,
    case_service: CaseService = Depends(get_case_service),
):
    """Get the current processing status of a case."""
    return StatusResponse(**case_service.get_status(case_id))


@router.get("/cases/{case_id}/artifacts", response_model=ArtifactList, summary="List available artifacts")
async def list_artifacts(
    case_id: str,
    case_service: CaseService = Depends(get_case_service),
):
    """List all available artifacts for a case."""
    try:
        return ArtifactList(**case_service.list_artifacts(case_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Case not found")


@router.delete("/cases/{case_id}", summary="Delete a case")
async def delete_case(
    case_id: str,
    case_service: CaseService = Depends(get_case_service),
):
    """Delete a case and all its associated artifacts."""
    success = case_service.delete_case(case_id)
    if success:
        return {"message": "Case deleted successfully", "case_id": case_id}
    raise HTTPException(status_code=404, detail="Case not found")
