"""
Cases Router - Upload and Case Management

Handles file uploads, batch uploads, and case lifecycle.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
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
CASE_EVENT_POLL_INTERVAL_SECONDS = 0.75
CASE_EVENT_KEEPALIVE_SECONDS = 15.0
CASE_PIPELINE_STAGE_ORDER = ("load_volume", "segmentation", "sdf", "mesh")


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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_event_type(status: Optional[str]) -> str:
    if status == "ready":
        return "case_ready"
    if status == "error":
        return "case_error"
    return "upload_status"


def _serialize_sse_payload(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"


def _build_pipeline_snapshot(snapshot: dict) -> dict:
    status_payload = snapshot.get("status", {})
    raw_stages = snapshot.get("stages", {})
    stage_map = raw_stages if isinstance(raw_stages, dict) else {}

    stages: list[dict] = []
    seen_stage_names: set[str] = set()

    for stage_name in CASE_PIPELINE_STAGE_ORDER:
        payload = stage_map.get(stage_name)
        if not isinstance(payload, dict):
            payload = {"status": "pending"}
        stages.append(
            {
                "name": stage_name,
                "status": payload.get("status", "pending"),
                "duration_seconds": payload.get("duration_seconds"),
                "message": payload.get("message"),
                "output_shape": payload.get("output_shape"),
            }
        )
        seen_stage_names.add(stage_name)

    for stage_name, payload in stage_map.items():
        if stage_name in seen_stage_names or not isinstance(payload, dict):
            continue
        stages.append(
            {
                "name": stage_name,
                "status": payload.get("status", "pending"),
                "duration_seconds": payload.get("duration_seconds"),
                "message": payload.get("message"),
                "output_shape": payload.get("output_shape"),
            }
        )

    return {
        "overall_status": status_payload.get("status"),
        "viewer_ready": bool(status_payload.get("viewer_ready")),
        "volume_ready": bool(status_payload.get("volume_ready")),
        "artifacts": snapshot.get("artifacts", {}),
        "stages": stages,
    }


def _build_case_events(snapshot: dict, previous_snapshot: Optional[dict]) -> list[dict]:
    events: list[dict] = []
    pipeline_snapshot = _build_pipeline_snapshot(snapshot)
    previous_status = (previous_snapshot or {}).get("status", {})
    current_status = snapshot.get("status", {})

    if previous_snapshot is None or current_status != previous_status:
        events.append(
            {
                "type": _status_event_type(current_status.get("status")),
                "case_id": snapshot["case_id"],
                "status": current_status.get("status"),
                "viewer_ready": current_status.get("viewer_ready"),
                "volume_ready": current_status.get("volume_ready"),
                "message": current_status.get("message"),
                "current_stage": current_status.get("current_stage"),
                "progress_percent": current_status.get("progress_percent"),
                "snapshot": pipeline_snapshot,
                "timestamp": _utc_now_iso(),
            }
        )

    previous_stages = (previous_snapshot or {}).get("stages", {})
    for stage_name, stage_payload in snapshot.get("stages", {}).items():
        if previous_snapshot is None or previous_stages.get(stage_name) != stage_payload:
            events.append(
                {
                    "type": "pipeline_stage",
                    "case_id": snapshot["case_id"],
                    "status": stage_payload.get("status"),
                    "viewer_ready": current_status.get("viewer_ready"),
                    "volume_ready": current_status.get("volume_ready"),
                    "stage": stage_name,
                    "message": stage_payload.get("message"),
                    "duration_seconds": stage_payload.get("duration_seconds"),
                    "snapshot": pipeline_snapshot,
                    "timestamp": _utc_now_iso(),
                }
            )

    previous_artifacts = (previous_snapshot or {}).get("artifacts", {})
    for artifact_name, available in snapshot.get("artifacts", {}).items():
        if available and not previous_artifacts.get(artifact_name):
            events.append(
                {
                    "type": "artifact_ready",
                    "case_id": snapshot["case_id"],
                    "viewer_ready": current_status.get("viewer_ready"),
                    "volume_ready": current_status.get("volume_ready"),
                    "artifact": artifact_name,
                    "snapshot": pipeline_snapshot,
                    "timestamp": _utc_now_iso(),
                }
            )

    return events


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


@router.get("/cases/{case_id}/events", summary="Stream case events")
async def stream_case_events(
    case_id: str,
    request: Request,
    case_service: CaseService = Depends(get_case_service),
):
    """Stream upload, pipeline, and artifact events for a case via SSE."""
    try:
        case_service.get_event_snapshot(case_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Case not found")

    async def event_stream():
        previous_snapshot: Optional[dict] = None
        last_emit_at = time.monotonic()

        while True:
            if await request.is_disconnected():
                break

            try:
                snapshot = await run_in_threadpool(case_service.get_event_snapshot, case_id)
            except FileNotFoundError:
                yield _serialize_sse_payload(
                    {
                        "type": "case_error",
                        "case_id": case_id,
                        "status": "error",
                        "message": "Case not found",
                        "timestamp": _utc_now_iso(),
                    }
                )
                break

            events = _build_case_events(snapshot, previous_snapshot)
            if events:
                previous_snapshot = snapshot
                for payload in events:
                    yield _serialize_sse_payload(payload)
                last_emit_at = time.monotonic()

                if snapshot.get("status", {}).get("status") in {"ready", "error"}:
                    break
            elif time.monotonic() - last_emit_at >= CASE_EVENT_KEEPALIVE_SECONDS:
                yield ": keep-alive\n\n"
                last_emit_at = time.monotonic()

            await asyncio.sleep(CASE_EVENT_POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
