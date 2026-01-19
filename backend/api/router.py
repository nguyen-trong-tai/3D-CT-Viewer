from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Form
from storage.repository import CaseRepository
from processing import loader
from services.pipeline import PipelineService
from models import schemas
import uuid
import numpy as np
import shutil
import tempfile
import os
from pathlib import Path
from fastapi.responses import FileResponse, JSONResponse
from typing import List, Optional
import pydicom
from io import BytesIO
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

router = APIRouter()
repo = CaseRepository()
pipeline_service = PipelineService(repo)

# Store for batch upload sessions
batch_sessions: dict[str, dict] = {}

# Thread pool for CPU-bound DICOM parsing
_dicom_executor = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)


def _parse_dicom_bytes(content: bytes) -> pydicom.Dataset:
    """Parse DICOM from bytes - runs in thread pool for parallelism"""
    return pydicom.dcmread(BytesIO(content))


def _process_dicom_slice(ds: pydicom.Dataset) -> np.ndarray:
    """Process a single DICOM slice with HU conversion - CPU bound"""
    slope = getattr(ds, 'RescaleSlope', 1)
    intercept = getattr(ds, 'RescaleIntercept', 0)
    return ds.pixel_array.astype(np.float64) * slope + intercept


@router.post("/cases", response_model=schemas.CaseResponse)
async def upload_case(file: UploadFile = File(...)):
    case_id = str(uuid.uuid4())
    repo.create_case(case_id)
    
    try:
        # Determine strict suffix (handle .nii.gz case)
        filename = file.filename or "temp"
        suffixes = Path(filename).suffixes
        suffix = "".join(suffixes) if suffixes else ".tmp"
        
        # Save temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
        
        # Load and parse (this converts to HU and extracts metadata)
        if filename.endswith('.zip'):
            volume, spacing = loader.load_dicom_series(tmp_path)
        elif filename.endswith('.nii') or filename.endswith('.nii.gz'):
            volume, spacing = loader.load_nifti(tmp_path)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format")
            
        # Clean up temp
        os.remove(tmp_path)
        
        # Save to internal storage
        repo.save_ct_volume(case_id, volume, spacing)
        
        return schemas.CaseResponse(case_id=case_id, status="uploaded")
        
    except Exception as e:
        import traceback
        traceback.print_exc() # Print to console for debugging
        repo.update_status(case_id, "error")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.post("/cases/dicom", response_model=schemas.CaseResponse)
async def upload_dicom_files(
    files: List[UploadFile] = File(...),
    metadata: Optional[str] = Form(None)  # Optional JSON metadata string
):
    """
    Upload multiple DICOM files in a single request.
    This is the FASTEST way to upload a DICOM folder - only 1 API call!
    
    - files: List of .dcm files
    - metadata: Optional JSON string with additional metadata
    
    Uses parallel processing for maximum speed (<2s for typical datasets).
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
                pass  # Ignore invalid metadata
        
        # Step 1: Read all file contents in parallel (I/O bound)
        async def read_file_async(f: UploadFile) -> tuple[str, bytes]:
            content = await f.read()
            return (f.filename or "", content)
        
        # Filter and read only .dcm files
        dcm_files = [f for f in files if f.filename and f.filename.lower().endswith('.dcm')]
        
        if not dcm_files:
            raise HTTPException(status_code=400, detail="No valid DICOM files found")
        
        # Read all files concurrently
        file_contents = await asyncio.gather(*[read_file_async(f) for f in dcm_files])
        
        # Step 2: Parse DICOM in thread pool (CPU bound) - parallel
        loop = asyncio.get_event_loop()
        parse_tasks = [
            loop.run_in_executor(_dicom_executor, _parse_dicom_bytes, content)
            for _, content in file_contents
        ]
        dicom_data = await asyncio.gather(*parse_tasks)
        
        if not dicom_data:
            raise HTTPException(status_code=400, detail="No valid DICOM files parsed")
        
        # Sort by ImagePositionPatient Z coordinate
        dicom_data = sorted(dicom_data, key=lambda x: float(x.ImagePositionPatient[2]))
        
        # Calculate spacing
        try:
            pixel_spacing = dicom_data[0].PixelSpacing
            slice_thickness = dicom_data[0].SliceThickness
            spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]), float(slice_thickness))
        except AttributeError:
            raise ValueError("DICOM missing Spacing attributes")
        
        # Step 3: Process slices in thread pool (CPU bound) - parallel
        process_tasks = [
            loop.run_in_executor(_dicom_executor, _process_dicom_slice, ds)
            for ds in dicom_data
        ]
        volume_slices = await asyncio.gather(*process_tasks)
        
        # Convert from (Y, X, Z) to (X, Y, Z)
        volume_np = np.stack(volume_slices, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        
        # Save to repository
        repo.save_ct_volume(case_id, volume_np, spacing)
        
        # Save extra metadata if provided
        if extra_metadata:
            repo.save_extra_metadata(case_id, extra_metadata)
        
        return schemas.CaseResponse(case_id=case_id, status="uploaded")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        repo.update_status(case_id, "error")
        raise HTTPException(status_code=500, detail=f"DICOM upload failed: {str(e)}")

# ============== BATCH UPLOAD ENDPOINTS ==============
# These endpoints allow uploading multiple DICOM files directly without client-side zipping

@router.post("/cases/batch/init", response_model=schemas.CaseResponse)
async def init_batch_upload():
    """Initialize a batch upload session. Returns a case_id to use for subsequent file uploads."""
    case_id = str(uuid.uuid4())
    repo.create_case(case_id)
    
    # Create temp directory for this batch
    temp_dir = tempfile.mkdtemp(prefix=f"batch_{case_id}_")
    batch_sessions[case_id] = {
        "temp_dir": temp_dir,
        "files_received": 0,
        "total_expected": 0
    }
    
    return schemas.CaseResponse(case_id=case_id, status="batch_initialized")

@router.post("/cases/batch/{case_id}/files")
async def upload_batch_files(case_id: str, files: List[UploadFile] = File(...)):
    """
    Upload multiple DICOM files for a batch session.
    Can be called multiple times with chunks of files for better performance.
    """
    if case_id not in batch_sessions:
        raise HTTPException(status_code=404, detail="Batch session not found. Call /cases/batch/init first.")
    
    session = batch_sessions[case_id]
    temp_dir = session["temp_dir"]
    
    saved_count = 0
    for file in files:
        if file.filename:
            # Preserve relative path structure if available
            file_path = os.path.join(temp_dir, file.filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'wb') as f:
                content = await file.read()
                f.write(content)
            saved_count += 1
    
    session["files_received"] += saved_count
    
    return {"case_id": case_id, "files_saved": saved_count, "total_received": session["files_received"]}

@router.post("/cases/batch/{case_id}/finalize", response_model=schemas.CaseResponse)
async def finalize_batch_upload(case_id: str):
    """
    Finalize batch upload: process all uploaded DICOM files into a volume.
    Must be called after all files have been uploaded.
    """
    if case_id not in batch_sessions:
        raise HTTPException(status_code=404, detail="Batch session not found")
    
    session = batch_sessions[case_id]
    temp_dir = session["temp_dir"]
    
    try:
        # Find all DICOM files in the temp directory
        dicom_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.lower().endswith('.dcm'):
                    dicom_files.append(os.path.join(root, file))
        
        if not dicom_files:
            raise HTTPException(status_code=400, detail="No DICOM files found in batch")
        
        # Sort and process DICOM files
        slices = [pydicom.dcmread(f) for f in dicom_files]
        slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))
        
        # Calculate spacing
        try:
            pixel_spacing = slices[0].PixelSpacing
            slice_thickness = slices[0].SliceThickness
            spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]), float(slice_thickness))
        except AttributeError:
            raise ValueError("DICOM missing Spacing attributes")
        
        # Create volume with HU conversion
        volume = []
        for s in slices:
            slope = getattr(s, 'RescaleSlope', 1)
            intercept = getattr(s, 'RescaleIntercept', 0)
            slice_data = s.pixel_array.astype(np.float64) * slope + intercept
            volume.append(slice_data)
        
        # Convert from (Y, X, Z) to (X, Y, Z)
        volume_np = np.stack(volume, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        
        # Save to repository
        repo.save_ct_volume(case_id, volume_np, spacing)
        
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
        del batch_sessions[case_id]
        
        return schemas.CaseResponse(case_id=case_id, status="uploaded")
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        repo.update_status(case_id, "error")
        # Cleanup on error
        shutil.rmtree(temp_dir, ignore_errors=True)
        if case_id in batch_sessions:
            del batch_sessions[case_id]
        raise HTTPException(status_code=500, detail=f"Batch finalize failed: {str(e)}")

# ============== END BATCH UPLOAD ==============

@router.post("/cases/{case_id}/process", response_model=schemas.ProcessingResponse)
async def trigger_processing(case_id: str, background_tasks: BackgroundTasks):
    status = repo.get_status(case_id)
    if status == "error":
         raise HTTPException(status_code=404, detail="Case not found")
         
    background_tasks.add_task(pipeline_service.process_case, case_id)
    return schemas.ProcessingResponse(case_id=case_id, status="processing_started")

@router.get("/cases/{case_id}/status", response_model=schemas.StatusResponse)
async def get_status(case_id: str):
    """
    Returns the current processing status of a case.
    
    This endpoint NEVER returns 404 for a case_id. Status values:
    - "uploaded": Case created, processing not yet started
    - "processing": Pipeline execution ongoing
    - "ready": Pipeline completed successfully  
    - "error": Pipeline failed
    """
    status = repo.get_status(case_id)
    return schemas.StatusResponse(case_id=case_id, status=status)

@router.get("/cases/{case_id}/metadata", response_model=schemas.MetadataResponse)
async def get_metadata(case_id: str):
    meta = repo.load_ct_metadata(case_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Metadata not found")
        
    shape = meta["shape"] # (X, Y, Z)
    spacing = meta["spacing"]
    
    return schemas.MetadataResponse(
        volume_shape={"x": shape[0], "y": shape[1], "z": shape[2]},
        voxel_spacing_mm={"x": spacing[0], "y": spacing[1], "z": spacing[2]},
        num_slices=shape[2]
    )

@router.get("/cases/{case_id}/extra-metadata")
async def get_extra_metadata(case_id: str):
    """
    Get extra metadata (patient info, study details, etc.) if it was uploaded.
    Returns 404 if no extra metadata was provided during upload.
    """
    meta = repo.load_extra_metadata(case_id)
    if not meta:
        raise HTTPException(status_code=404, detail="No extra metadata available")
    return JSONResponse(content=meta)

@router.get("/cases/{case_id}/ct/slices/{slice_index}", response_model=schemas.SliceResponse)
async def get_slice(case_id: str, slice_index: int):
    # Load entire volume? Eek. performance. 
    # For a demo/POC with local disk, loading memory mapping is best.
    # np.load(mmap_mode='r')
    path = repo._case_dir(case_id) / "ct_volume.npy"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Volume not found")
        
    try:
        # Use mmap to reading just the slice we need
        vol = np.load(path, mmap_mode='r') # (X, Y, Z)
        
        if slice_index < 0 or slice_index >= vol.shape[2]:
            raise HTTPException(status_code=404, detail="Slice index out of bounds")
            
        # Extract slice Z
        slice_data = vol[:, :, slice_index] # (X, Y)
        
        # Transpose to (Y, X) = (Rows, Cols) for standard image display
        # where X (width) is horizontal, Y (height) is vertical.
        # Frontend expects List[Rows][Cols] -> List[Y][X].
        slice_data = slice_data.T
        
        meta = repo.load_ct_metadata(case_id)
        spacing = meta["spacing"]
        
        return schemas.SliceResponse(
            slice_index=slice_index,
            hu_values=slice_data.tolist(), # Convert to native list
            spacing_mm={"x": spacing[0], "y": spacing[1]}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cases/{case_id}/mask/slices/{slice_index}", response_model=schemas.MaskSliceResponse)
async def get_mask_slice(case_id: str, slice_index: int):
    path = repo._case_dir(case_id) / "mask_volume.npy"
    if not path.exists():
         # If mask doesn't exist yet, return empty sparse
         # Or 404? PRD says "Missing or empty slices are valid"
         # But if processing hasn't run, maybe 404 is better?
         raise HTTPException(status_code=404, detail="Mask not found")

    try:
        vol = np.load(path, mmap_mode='r')
        if slice_index < 0 or slice_index >= vol.shape[2]:
             raise HTTPException(status_code=404, detail="Slice index out of bounds")
             
        mask_slice = vol[:, :, slice_index]
        mask_slice = mask_slice.T # Transpose (X,Y) -> (Y,X)
        
        # Check sparsity
        is_sparse = bool(np.sum(mask_slice) == 0)
        
        return schemas.MaskSliceResponse(
            slice_index=slice_index,
            mask=mask_slice.tolist(),
            sparse=is_sparse
        )
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@router.get("/cases/{case_id}/implicit", response_model=schemas.ImplicitMetadataResponse)
async def get_implicit_meta(case_id: str):
    # Static response as per PRD for now, verifying stage exists
    status = repo.get_status(case_id)
    if status != "ready":
         raise HTTPException(status_code=400, detail="Processing not complete")
    return schemas.ImplicitMetadataResponse()

@router.get("/cases/{case_id}/mesh")
async def get_mesh(case_id: str):
    path = repo.get_mesh_path(case_id)
    if not path:
        raise HTTPException(status_code=404, detail="Mesh not found")
        
    return FileResponse(path, media_type="model/obj", filename="reconstruction.obj")
