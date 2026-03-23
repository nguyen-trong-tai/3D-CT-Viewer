"""
Cases Router — Upload and Case Management

Handles file uploads (DICOM/NIfTI), batch uploads, and case lifecycle.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, Form, Depends, BackgroundTasks
from typing import List, Optional
import uuid
import numpy as np
import shutil
import tempfile
import os
import json
import asyncio
from pathlib import Path

import pydicom

from models import CaseResponse, StatusResponse, ArtifactList
from models.enums import CaseStatus
from storage.repository import CaseRepository
from processing import (
    load_dicom_series,
    load_nifti,
    extract_dicom_metadata,
)
from api.dependencies import get_repository
from config import settings


router = APIRouter(tags=["Cases"])

_batch_sessions: dict = {}


# --- Helpers for Hybrid Environment (Local / Modal) ---

def is_running_in_modal() -> bool:
    """Check if the code is executing inside a Modal container."""
    try:
        import modal
        return modal.is_local() is False
    except ImportError:
        return False

def get_temp_dir(prefix: str) -> str:
    """Get a temp directory inside the shared storage root so background Modal workers can access it."""
    temp_base = settings.STORAGE_ROOT / "temp_uploads"
    temp_base.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=str(temp_base))

def _commit_if_modal():
    """Commit writes to Modal Volume so other containers can see them."""
    if is_running_in_modal():
        try:
            from modal_app import data_volume
            data_volume.commit()
        except ImportError:
            pass

def _reload_if_modal():
    """Reload reads from Modal Volume to avoid stale cached data."""
    if is_running_in_modal():
        try:
            from modal_app import data_volume
            data_volume.reload()
        except ImportError:
            pass


# --- Background Tasks ---

def process_single_upload_task(case_id: str, tmp_path: str, filename: str, repo: CaseRepository):
    """Background task to process a single ZIP or NIfTI upload."""
    try:
        repo.update_status(case_id, CaseStatus.UPLOADING.value, "Processing volume data...")
        
        if filename.lower().endswith('.zip'):
            volume, spacing = load_dicom_series(tmp_path)
        elif filename.lower().endswith(('.nii', '.nii.gz')):
            volume, spacing = load_nifti(tmp_path)
        else:
            raise ValueError(f"Unsupported file format: {filename}")
            
        repo.save_ct_volume(case_id, volume, spacing)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        repo.update_status(case_id, CaseStatus.ERROR.value, str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def process_dicom_directory_task(case_id: str, temp_dir: str, repo: CaseRepository, extra_metadata: Optional[dict]):
    """Background task to process a directory full of DICOM files."""
    try:
        repo.update_status(case_id, CaseStatus.UPLOADING.value, "Processing DICOM directory...")
        
        dicom_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.lower().endswith('.dcm'):
                    dicom_files.append(os.path.join(root, file))
                    
        if not dicom_files:
            raise ValueError("No DICOM files found in batch directory")
            
        # Load using optimized loader
        from processing.loader import load_dicom_from_files
        volume, spacing = load_dicom_from_files(dicom_files)
        
        repo.save_ct_volume(case_id, volume, spacing)
        
        # Save or extract metadata
        if extra_metadata is None:
            extra_metadata = {}
            
        # Extract metadata from the first file
        try:
            ds = pydicom.dcmread(dicom_files[0], stop_before_pixels=True)
            dicom_meta = extract_dicom_metadata(ds)
            if dicom_meta:
                extra_metadata.update({"dicom": dicom_meta})
        except Exception as meta_ex:
            print(f"[Metadata Extraction Error]: {meta_ex}")
        
        if extra_metadata:
            repo.save_extra_metadata(case_id, extra_metadata)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        repo.update_status(case_id, CaseStatus.ERROR.value, str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# --- Endpoints ---

@router.post("/cases", response_model=CaseResponse, summary="Upload a CT file")
async def upload_case(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    repo: CaseRepository = Depends(get_repository)
):
    """
    Upload a single CT file (ZIP containing DICOM series or NIfTI file).

    Returns a case_id to use for subsequent API calls. Task is processed in background.
    """
    case_id = str(uuid.uuid4())
    repo.create_case(case_id)
    repo.update_status(case_id, CaseStatus.UPLOADING.value, "Receiving file...")

    try:
        filename = file.filename or ""
        suffixes = Path(filename).suffixes
        suffix = "".join(suffixes).lower()

        if not filename.lower().endswith(('.zip', '.nii', '.nii.gz')):
            error_msg = f"Unsupported file format: {suffix}. Use .zip (DICOM) or .nii (NIfTI)"
            repo.update_status(case_id, CaseStatus.ERROR.value, error_msg)
            raise HTTPException(status_code=400, detail=error_msg)

        # Save to shared storage so background containers can access it
        temp_base = settings.STORAGE_ROOT / "temp_uploads"
        temp_base.mkdir(parents=True, exist_ok=True)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=str(temp_base)) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        _commit_if_modal()

        if is_running_in_modal():
            from modal_app import process_upload_modal
            process_upload_modal.spawn(case_id, tmp_path, filename)
        else:
            background_tasks.add_task(process_single_upload_task, case_id, tmp_path, filename, repo)
            
        return CaseResponse(case_id=case_id, status=CaseStatus.UPLOADING.value)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        repo.update_status(case_id, CaseStatus.ERROR.value, str(e))
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/cases/dicom", response_model=CaseResponse, summary="Upload DICOM files directly")
async def upload_dicom_files(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    metadata: Optional[str] = Form(None),
    repo: CaseRepository = Depends(get_repository)
):
    """Upload multiple DICOM files in a single request. Processed in background."""
    case_id = str(uuid.uuid4())
    repo.create_case(case_id)
    repo.update_status(case_id, CaseStatus.UPLOADING.value, "Receiving files...")

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

        temp_dir = get_temp_dir(f"dicom_{case_id}_")
        
        # Save files directly to disk piece by piece to avoid RAM bloat
        for f in dcm_files:
            file_path = os.path.join(temp_dir, os.path.basename(f.filename or str(uuid.uuid4())))
            with open(file_path, 'wb') as tmp_file:
                shutil.copyfileobj(f.file, tmp_file)

        _commit_if_modal()

        if is_running_in_modal():
            from modal_app import process_dicom_dir_modal
            process_dicom_dir_modal.spawn(case_id, temp_dir, extra_metadata)
        else:
            background_tasks.add_task(process_dicom_directory_task, case_id, temp_dir, repo, extra_metadata)
            
        return CaseResponse(case_id=case_id, status=CaseStatus.UPLOADING.value)

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
    repo.update_status(case_id, CaseStatus.UPLOADING.value, "Batch initialized")

    temp_dir = get_temp_dir(f"batch_{case_id}_")
    
    _batch_sessions[case_id] = {
        "temp_dir": temp_dir,
        "files_received": 0
    }

    _commit_if_modal()
    return CaseResponse(case_id=case_id, status=CaseStatus.UPLOADING.value)


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
    for f in files:
        if f.filename:
            file_path = os.path.join(temp_dir, os.path.basename(f.filename))
            with open(file_path, 'wb') as tmp:
                shutil.copyfileobj(f.file, tmp)
            saved_count += 1

    session["files_received"] += saved_count

    _commit_if_modal()
    return {"case_id": case_id, "files_saved": saved_count, "total_received": session["files_received"]}


@router.post("/cases/batch/{case_id}/finalize", response_model=CaseResponse, summary="Finalize batch upload")
async def finalize_batch_upload(
    case_id: str,
    background_tasks: BackgroundTasks,
    repo: CaseRepository = Depends(get_repository)
):
    """Process all uploaded files and create the CT volume in the background."""
    if case_id not in _batch_sessions:
        raise HTTPException(status_code=404, detail="Batch session not found")

    session = _batch_sessions[case_id]
    temp_dir = session["temp_dir"]
    
    _batch_sessions.pop(case_id, None)

    if is_running_in_modal():
        from modal_app import process_dicom_dir_modal
        process_dicom_dir_modal.spawn(case_id, temp_dir, None)
    else:
        background_tasks.add_task(process_dicom_directory_task, case_id, temp_dir, repo, None)
        
    return CaseResponse(case_id=case_id, status=CaseStatus.UPLOADING.value)


@router.get("/cases/{case_id}/status", response_model=StatusResponse, summary="Get case status")
async def get_status(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """Get the current processing status of a case."""
    _reload_if_modal()
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
    _reload_if_modal()
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
