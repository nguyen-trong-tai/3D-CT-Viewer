"""
API Router

REST API endpoints for the CT-based Medical Imaging & AI Research Platform.

This API follows the case-based architecture defined in the PRD:
- Case-based, not slice-based operations
- Used for data upload, AI processing, and artifact delivery
- No real-time interaction (slice navigation is handled client-side)
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Form, Depends
from fastapi.responses import FileResponse, JSONResponse, Response
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
from io import BytesIO

import pydicom

from models import (
    CaseResponse,
    StatusResponse,
    ProcessingResponse,
    MetadataResponse,
    SliceResponse,
    MaskSliceResponse,
    ImplicitMetadataResponse,
    ArtifactList,
    ErrorResponse,
    Spacing2D,
    VolumeShape,
    VoxelSpacing,
)
from models.enums import CaseStatus
from storage.repository import CaseRepository
from services.pipeline import PipelineService
from processing import (
    load_dicom_series,
    load_nifti,
    parse_dicom_bytes,
    process_dicom_slice,
    extract_dicom_metadata,
)
from api.dependencies import get_repository, get_pipeline_service
from config import settings


router = APIRouter(prefix="/api/v1", tags=["CT Imaging Platform"])

# Thread pool for CPU-bound DICOM parsing
_dicom_executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)

# Temporary storage for batch upload sessions
_batch_sessions: dict = {}


# =============================================================================
# Case Management Endpoints
# =============================================================================

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
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
        
        try:
            # Load based on file type
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
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        
        # Save to repository
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
    """
    Upload multiple DICOM files in a single request.
    
    Args:
        files: List of .dcm files
        metadata: Optional JSON string with additional metadata (patient info, etc.)
    """
    case_id = str(uuid.uuid4())
    repo.create_case(case_id)
    
    try:
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")
        
        # Parse optional metadata
        extra_metadata = {}
        if metadata:
            try:
                extra_metadata = json.loads(metadata)
            except json.JSONDecodeError:
                pass
        
        # Filter DICOM files
        dcm_files = [f for f in files if f.filename and f.filename.lower().endswith('.dcm')]
        
        if not dcm_files:
            raise HTTPException(status_code=400, detail="No valid DICOM files (.dcm) found")
        
        # Step 1: Read all file contents concurrently (I/O bound)
        async def read_file_async(f: UploadFile) -> tuple:
            content = await f.read()
            return (f.filename, content)
        
        file_contents = await asyncio.gather(*[read_file_async(f) for f in dcm_files])
        
        # Step 2: Parse DICOM files in thread pool (CPU bound)
        loop = asyncio.get_event_loop()
        parse_tasks = [
            loop.run_in_executor(_dicom_executor, parse_dicom_bytes, content)
            for _, content in file_contents
        ]
        dicom_datasets = await asyncio.gather(*parse_tasks)
        
        if not dicom_datasets:
            raise HTTPException(status_code=400, detail="No valid DICOM files could be parsed")
        
        # Sort by Z position
        dicom_datasets = sorted(
            dicom_datasets,
            key=lambda x: float(getattr(x, 'ImagePositionPatient', [0, 0, 0])[2])
        )
        
        # Extract spacing
        try:
            pixel_spacing = dicom_datasets[0].PixelSpacing
            slice_thickness = dicom_datasets[0].SliceThickness
            spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]), float(slice_thickness))
        except AttributeError:
            raise HTTPException(
                status_code=400,
                detail="DICOM files missing required spacing attributes (PixelSpacing, SliceThickness)"
            )
        
        # Step 3: Process slices in thread pool (CPU bound)
        process_tasks = [
            loop.run_in_executor(_dicom_executor, process_dicom_slice, ds)
            for ds in dicom_datasets
        ]
        volume_slices = await asyncio.gather(*process_tasks)
        
        # Build volume: (Y, X, Z) -> (X, Y, Z)
        volume_np = np.stack(volume_slices, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        
        # Save to repository
        repo.save_ct_volume(case_id, volume_np, spacing)
        
        # Save extra metadata if provided
        if extra_metadata:
            repo.save_extra_metadata(case_id, extra_metadata)
        
        # Extract and save DICOM metadata from first file
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


# Batch Upload Endpoints (Alternative approach for large uploads)

@router.post("/cases/batch/init", response_model=CaseResponse, summary="Initialize batch upload")
async def init_batch_upload(repo: CaseRepository = Depends(get_repository)):
    """
    Initialize a batch upload session for uploading DICOM files in chunks.
    
    Use this if you need to upload files in multiple requests.
    For most cases, use POST /cases/dicom instead.
    """
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
        raise HTTPException(
            status_code=404,
            detail="Batch session not found. Call /cases/batch/init first."
        )
    
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
    
    return {
        "case_id": case_id,
        "files_saved": saved_count,
        "total_received": session["files_received"]
    }


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
        # Find all DICOM files
        dicom_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.lower().endswith('.dcm'):
                    dicom_files.append(os.path.join(root, file))
        
        if not dicom_files:
            raise HTTPException(status_code=400, detail="No DICOM files found in batch")
        
        # Sort and process
        slices = [pydicom.dcmread(f) for f in dicom_files]
        slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))
        
        # Extract spacing
        pixel_spacing = slices[0].PixelSpacing
        slice_thickness = slices[0].SliceThickness
        spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]), float(slice_thickness))
        
        # Build volume with HU conversion
        volume_slices = []
        for s in slices:
            slope = getattr(s, 'RescaleSlope', 1)
            intercept = getattr(s, 'RescaleIntercept', 0)
            slice_data = s.pixel_array.astype(np.float64) * slope + intercept
            volume_slices.append(slice_data)
        
        volume_np = np.stack(volume_slices, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        
        # Save
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
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
        _batch_sessions.pop(case_id, None)


# =============================================================================
# Processing Endpoints
# =============================================================================

@router.post("/cases/{case_id}/process", response_model=ProcessingResponse, summary="Start AI processing")
async def trigger_processing(
    case_id: str,
    background_tasks: BackgroundTasks,
    repo: CaseRepository = Depends(get_repository),
    pipeline: PipelineService = Depends(get_pipeline_service)
):
    """
    Trigger the AI processing pipeline for a case.
    
    Pipeline stages:
    1. Segmentation (threshold-based)
    2. SDF computation
    3. Mesh extraction (Marching Cubes)
    
    Processing runs in the background. Use GET /cases/{case_id}/status to check progress.
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
    
    # Start pipeline in background
    background_tasks.add_task(pipeline.process_case, case_id)
    
    return ProcessingResponse(
        case_id=case_id,
        status="processing_started",
        estimated_time_seconds=15.0  # Typical time for standard volumes
    )


@router.get("/cases/{case_id}/status", response_model=StatusResponse, summary="Get case status")
async def get_status(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """
    Get the current processing status of a case.
    
    Status values:
    - `pending`: Case created, awaiting file upload
    - `uploaded`: Upload complete, ready for processing
    - `processing`: AI pipeline running
    - `ready`: All processing complete, artifacts available
    - `error`: Processing failed
    """
    status = repo.get_status(case_id)
    status_info = repo.get_status_info(case_id)
    
    message = None
    if status_info:
        message = status_info.get("message")
    
    return StatusResponse(
        case_id=case_id,
        status=status,
        message=message
    )


@router.get("/cases/{case_id}/pipeline", summary="Get detailed pipeline status")
async def get_pipeline_status(
    case_id: str,
    pipeline: PipelineService = Depends(get_pipeline_service)
):
    """Get detailed status of pipeline stages and available artifacts."""
    return JSONResponse(content=pipeline.get_pipeline_status(case_id))


# =============================================================================
# Data Retrieval Endpoints
# =============================================================================

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
    
    This transfers the entire volume in a single request for frontend caching.
    The frontend should load this into GPU memory for real-time interaction.
    
    Response is raw binary data with shape and spacing in headers.
    """
    volume = repo.load_ct_volume(case_id)
    meta = repo.load_ct_metadata(case_id)
    
    if volume is None or meta is None:
        raise HTTPException(status_code=404, detail="Volume not found")
    
    # Convert to int16 bytes
    volume_bytes = volume.astype(np.int16).tobytes()
    
    # Include metadata in headers
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
    """
    Get a single CT slice as HU values.
    
    Note: For optimal performance, use GET /cases/{case_id}/ct/volume to get
    the full volume and handle slice navigation client-side.
    """
    # Use memory-mapped access for efficiency
    volume = repo.load_ct_volume_mmap(case_id)
    
    if volume is None:
        raise HTTPException(status_code=404, detail="Volume not found")
    
    if slice_index < 0 or slice_index >= volume.shape[2]:
        raise HTTPException(
            status_code=404,
            detail=f"Slice index out of bounds. Valid range: 0-{volume.shape[2]-1}"
        )
    
    # Extract slice: volume is (X, Y, Z)
    slice_data = volume[:, :, slice_index]  # (X, Y)
    
    # Transpose to (Y, X) for standard image display (rows, cols)
    slice_data = slice_data.T
    
    meta = repo.load_ct_metadata(case_id)
    spacing = meta["spacing"]
    
    return SliceResponse(
        slice_index=slice_index,
        hu_values=slice_data.tolist(),
        spacing_mm=Spacing2D(x=spacing[0], y=spacing[1])
    )


@router.get("/cases/{case_id}/mask/volume", summary="Get full segmentation mask")
async def get_mask_volume(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """
    Get the full segmentation mask as raw binary data (uint8).
    
    Similar to CT volume endpoint, for frontend caching.
    """
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
    
    mask_slice = mask[:, :, slice_index]
    mask_slice = mask_slice.T  # Transpose (X,Y) -> (Y,X)
    
    # Check sparsity (empty slice)
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


@router.get("/cases/{case_id}/mesh", summary="Get 3D mesh")
async def get_mesh(
    case_id: str,
    repo: CaseRepository = Depends(get_repository)
):
    """
    Get the reconstructed 3D mesh in OBJ format.
    
    The mesh is in physical coordinates (mm) and respects voxel spacing.
    """
    mesh_path = repo.get_mesh_path(case_id)
    
    if mesh_path is None:
        raise HTTPException(status_code=404, detail="Mesh not found")
    
    return FileResponse(
        path=mesh_path,
        media_type="model/obj",
        filename="reconstruction.obj"
    )


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


# =============================================================================
# Case Management Endpoints (Additional)
# =============================================================================

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


# =============================================================================
# Health Check
# =============================================================================

@router.get("/health", summary="Health check")
async def health_check():
    """Check if the API is running."""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "storage_root": str(settings.STORAGE_ROOT)
    }
