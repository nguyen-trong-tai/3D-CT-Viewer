"""
Cases Router — Upload and Case Management

Handles file uploads (DICOM/NIfTI), batch uploads, and case lifecycle.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Depends
from typing import List, Optional
import uuid
import numpy as np
import shutil
import tempfile
import os
import json
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pydicom

from models import CaseResponse, StatusResponse, ArtifactList
from models.enums import CaseStatus
from storage.repository import CaseRepository
from processing import (
    load_dicom_series,
    load_nifti,
    parse_dicom_bytes,
    process_dicom_slice,
    extract_dicom_metadata,
)
from api.dependencies import get_repository
from config import settings


router = APIRouter(tags=["Cases"])

_dicom_executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)
_batch_sessions: dict = {}


@router.post("/cases", response_model=CaseResponse, summary="Upload a CT file")
async def upload_case(
    file: UploadFile = File(...),
    repo: CaseRepository = Depends(get_repository)
):
    """
    Upload a single CT file (ZIP containing DICOM series or NIfTI file).

    Supported formats:
    - `.zip` containing DICOM files (`.dcm`)
    - `.nii` or `.nii.gz` NIfTI volumes

    Returns a case_id to use for subsequent API calls.
    """
    case_id = str(uuid.uuid4())
    repo.create_case(case_id)

    try:
        filename = file.filename or ""
        suffixes = Path(filename).suffixes
        suffix = "".join(suffixes).lower()

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            if filename.lower().endswith('.zip'):
                volume, spacing = load_dicom_series(tmp_path)
            elif filename.lower().endswith(('.nii', '.nii.gz')):
                volume, spacing = load_nifti(tmp_path)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file format: {suffix}. Use .zip (DICOM) or .nii/.nii.gz (NIfTI)"
                )
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        repo.save_ct_volume(case_id, volume, spacing)
        return CaseResponse(case_id=case_id, status=CaseStatus.UPLOADED.value)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        repo.update_status(case_id, CaseStatus.ERROR.value, str(e))
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/cases/dicom", response_model=CaseResponse, summary="Upload DICOM files directly")
async def upload_dicom_files(
    files: List[UploadFile] = File(...),
    metadata: Optional[str] = Form(None),
    repo: CaseRepository = Depends(get_repository)
):
    """Upload multiple DICOM files in a single request."""
    case_id = str(uuid.uuid4())
    repo.create_case(case_id)

    try:
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        extra_metadata = {}
        if metadata:
            try:
                extra_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                pass

        dcm_files = [f for f in files if f.filename and f.filename.lower().endswith('.dcm')]
        if not dcm_files:
            raise HTTPException(status_code=400, detail="No valid DICOM files (.dcm) found")

        async def read_file_async(f: UploadFile) -> tuple:
            content = await f.read()
            return (f.filename, content)

        file_contents = await asyncio.gather(*[read_file_async(f) for f in dcm_files])

        loop = asyncio.get_event_loop()
        parse_tasks = [
            loop.run_in_executor(_dicom_executor, parse_dicom_bytes, content)
            for _, content in file_contents
        ]
        dicom_datasets = await asyncio.gather(*parse_tasks)

        if not dicom_datasets:
            raise HTTPException(status_code=400, detail="No valid DICOM files could be parsed")

        dicom_datasets = sorted(
            dicom_datasets,
            key=lambda x: float(getattr(x, 'ImagePositionPatient', [0, 0, 0])[2])
        )

        try:
            pixel_spacing = dicom_datasets[0].PixelSpacing
            slice_thickness = dicom_datasets[0].SliceThickness
            spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]), float(slice_thickness))
        except AttributeError:
            raise HTTPException(
                status_code=400,
                detail="DICOM files missing required spacing attributes (PixelSpacing, SliceThickness)"
            )

        process_tasks = [
            loop.run_in_executor(_dicom_executor, process_dicom_slice, ds)
            for ds in dicom_datasets
        ]
        volume_slices = await asyncio.gather(*process_tasks)

        volume_np = np.stack(volume_slices, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        repo.save_ct_volume(case_id, volume_np, spacing)

        if extra_metadata:
            repo.save_extra_metadata(case_id, extra_metadata)

        if dicom_datasets:
            dicom_meta = extract_dicom_metadata(dicom_datasets[0])
            if dicom_meta:
                existing_meta = extra_metadata or {}
                existing_meta.update({"dicom": dicom_meta})
                repo.save_extra_metadata(case_id, existing_meta)

        return CaseResponse(case_id=case_id, status=CaseStatus.UPLOADED.value)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        repo.update_status(case_id, CaseStatus.ERROR.value, str(e))
        raise HTTPException(status_code=500, detail=f"DICOM upload failed: {str(e)}")


# Batch Upload Endpoints

@router.post("/cases/batch/init", response_model=CaseResponse, summary="Initialize batch upload")
async def init_batch_upload(repo: CaseRepository = Depends(get_repository)):
    """Initialize a batch upload session for uploading DICOM files in chunks."""
    case_id = str(uuid.uuid4())
    repo.create_case(case_id)

    temp_dir = tempfile.mkdtemp(prefix=f"batch_{case_id}_")
    _batch_sessions[case_id] = {
        "temp_dir": temp_dir,
        "files_received": 0.
    }

    return CaseResponse(case_id=case_id, status="batch_initialized")


@router.post("/cases/batch/{case_id}/files", summary="Upload batch files")
async def upload_batch_files(
    case_id: str,
    files: List[UploadFile] = File(...)
):
    """Upload files to an existing batch session."""
    if case_id not in _batch_sessions:
        raise HTTPException(status_code=404, detail="Batch session not found. Call /cases/batch/init first.")

    session = _batch_sessions[case_id]
    temp_dir = session["temp_dir"]

    saved_count = 0
    for file in files:
        if file.filename:
            file_path = os.path.join(temp_dir, os.path.basename(file.filename))
            with open(file_path, 'wb') as f:
                content = await file.read()
                f.write(content)
            saved_count += 1

    session["files_received"] += saved_count

    return {"case_id": case_id, "files_saved": saved_count, "total_received": session["files_received"]}


@router.post("/cases/batch/{case_id}/finalize", response_model=CaseResponse, summary="Finalize batch upload")
async def finalize_batch_upload(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Process all uploaded files and create the CT volume."""
    if case_id not in _batch_sessions:
        raise HTTPException(status_code=404, detail="Batch session not found")

    session = _batch_sessions[case_id]
    temp_dir = session["temp_dir"]

    try:
        dicom_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.lower().endswith('.dcm'):
                    dicom_files.append(os.path.join(root, file))

        if not dicom_files:
            raise HTTPException(status_code=400, detail="No DICOM files found in batch")

        slices = [pydicom.dcmread(f) for f in dicom_files]
        slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))

        pixel_spacing = slices[0].PixelSpacing
        slice_thickness = slices[0].SliceThickness
        spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]), float(slice_thickness))

        volume_slices = []
        for s in slices:
            slope = getattr(s, 'RescaleSlope', 1)
            intercept = getattr(s, 'RescaleIntercept', 0)
            slice_data = s.pixel_array.astype(np.float64) * slope + intercept
            volume_slices.append(slice_data)

        volume_np = np.stack(volume_slices, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        repo.save_ct_volume(case_id, volume_np, spacing)

        return CaseResponse(case_id=case_id, status=CaseStatus.UPLOADED.value)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        repo.update_status(case_id, CaseStatus.ERROR.value, str(e))
        raise HTTPException(status_code=500, detail=f"Batch finalize failed: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        _batch_sessions.pop(case_id, None)


@router.get("/cases/{case_id}/status", response_model=StatusResponse, summary="Get case status")
async def get_status(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get the current processing status of a case."""
    status = repo.get_status(case_id)
    status_info = repo.get_status_info(case_id)

    message = None
    if status_info:
        message = status_info.get("message")

    return StatusResponse(case_id=case_id, status=status, message=message)


@router.get("/cases/{case_id}/artifacts", response_model=ArtifactList, summary="List available artifacts")
async def list_artifacts(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """List all available artifacts for a case."""
    if not repo.case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    artifacts = repo.get_available_artifacts(case_id)
    return ArtifactList(case_id=case_id, artifacts=artifacts)


@router.delete("/cases/{case_id}", summary="Delete a case")
async def delete_case(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Delete a case and all its associated artifacts."""
    if not repo.case_exists(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    success = repo.delete_case(case_id)
    if success:
        return {"message": "Case deleted successfully", "case_id": case_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete case")
