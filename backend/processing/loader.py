"""
DICOM and NIfTI Loader Module

Handles loading and parsing of medical imaging data formats.
Ensures proper HU conversion and metadata extraction.
"""

import numpy as np
import nibabel as nib
import pydicom
import zipfile
import tempfile
import os
from pathlib import Path
from typing import Tuple, List, Optional
from io import BytesIO


def load_dicom_series(zip_path: str) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """
    Load a DICOM series from a ZIP file.
    
    Args:
        zip_path: Path to the ZIP file containing DICOM files
        
    Returns:
        Tuple of:
        - volume: HU-converted volume as np.ndarray, shape (X, Y, Z)
        - spacing: Voxel spacing as (sx, sy, sz) in mm
        
    Raises:
        ValueError: If no DICOM files found or missing required attributes
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Find all DICOM files recursively
        dicom_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.lower().endswith('.dcm'):
                    dicom_files.append(os.path.join(root, file))
        
        if not dicom_files:
            raise ValueError("No DICOM files found in ZIP archive")
            
        return _process_dicom_files(dicom_files)


def load_dicom_from_files(file_paths: List[str]) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """
    Load a DICOM series from a list of file paths.
    
    Args:
        file_paths: List of paths to DICOM files
    Returns:
        Tuple of volume and spacing
    """
    return _process_dicom_files(file_paths)


def load_dicom_from_bytes_list(
    file_contents: List[bytes]
) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """
    Load a DICOM series from a list of byte contents.
    
    This is optimized for cases where files are already in memory
    (e.g., uploaded via HTTP).
    
    Args:
        file_contents: List of raw DICOM file contents as bytes
        
    Returns:
        Tuple of volume and spacing
    """
    if not file_contents:
        raise ValueError("No DICOM file contents provided")
    
    # Parse all DICOM files
    slices = []
    for content in file_contents:
        try:
            ds = pydicom.dcmread(BytesIO(content))
            if "PixelData" in ds:
                slices.append(ds)
        except Exception:
            # Skip invalid DICOM files
            continue
    
    if not slices:
        raise ValueError("No valid DICOM files could be parsed")
    
    return _build_volume_from_slices(slices)


def load_nifti(file_path: str) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """
    Load a NIfTI volume (.nii or .nii.gz).
    
    Args:
        file_path: Path to the NIfTI file
        
    Returns:
        Tuple of:
        - volume: Volume data as np.ndarray, shape (X, Y, Z)
        - spacing: Voxel spacing as (sx, sy, sz) in mm
    """
    img = nib.load(file_path)
    
    # NIfTI's get_fdata() automatically applies slope/intercept
    volume = img.get_fdata(dtype=np.float32)
    
    # Extract spacing from header
    header = img.header
    pixdim = header['pixdim']
    spacing = (float(pixdim[1]), float(pixdim[2]), float(pixdim[3]))
    
    return volume, spacing


def parse_dicom_bytes(content: bytes) -> pydicom.Dataset:
    """
    Parse a single DICOM file from bytes.
    
    Thread-safe function for parallel processing.
    """
    return pydicom.dcmread(BytesIO(content))


def process_dicom_slice(ds: pydicom.Dataset) -> np.ndarray:
    """
    Process a single DICOM slice with HU conversion.
    
    Applies RescaleSlope and RescaleIntercept to convert
    raw pixel values to Hounsfield Units.
    
    Thread-safe function for parallel processing.
    """
    slope = float(getattr(ds, 'RescaleSlope', 1) or 1)
    intercept = float(getattr(ds, 'RescaleIntercept', 0) or 0)
    raw_pixels = ds.pixel_array

    if slope == 1.0 and intercept == 0.0:
        return raw_pixels.astype(np.int16, copy=False)

    # float32 is sufficient for HU conversion and halves memory versus float64.
    slice_data = raw_pixels.astype(np.float32, copy=False)
    slice_data = slice_data * slope + intercept
    return slice_data.astype(np.float32, copy=False)


def extract_dicom_metadata(ds: pydicom.Dataset) -> dict:
    """
    Extract relevant metadata from a DICOM dataset.
    
    Returns a dictionary with commonly needed metadata fields.
    """
    metadata = {}
    
    # Patient Information
    if hasattr(ds, 'PatientName'):
        metadata['patient_name'] = str(ds.PatientName)
    if hasattr(ds, 'PatientID'):
        metadata['patient_id'] = str(ds.PatientID)
    if hasattr(ds, 'PatientBirthDate'):
        metadata['patient_birth_date'] = str(ds.PatientBirthDate)
    if hasattr(ds, 'PatientSex'):
        metadata['patient_sex'] = str(ds.PatientSex)
        
    # Study Information
    if hasattr(ds, 'StudyDate'):
        metadata['study_date'] = str(ds.StudyDate)
    if hasattr(ds, 'StudyDescription'):
        metadata['study_description'] = str(ds.StudyDescription)
    if hasattr(ds, 'StudyInstanceUID'):
        metadata['study_uid'] = str(ds.StudyInstanceUID)
        
    # Series Information
    if hasattr(ds, 'SeriesDescription'):
        metadata['series_description'] = str(ds.SeriesDescription)
    if hasattr(ds, 'SeriesInstanceUID'):
        metadata['series_uid'] = str(ds.SeriesInstanceUID)
    if hasattr(ds, 'Modality'):
        metadata['modality'] = str(ds.Modality)
        
    # Image Information
    if hasattr(ds, 'Manufacturer'):
        metadata['manufacturer'] = str(ds.Manufacturer)
    if hasattr(ds, 'KVP'):
        metadata['kvp'] = float(ds.KVP)
    if hasattr(ds, 'SliceThickness'):
        metadata['slice_thickness'] = float(ds.SliceThickness)
        
    return metadata


def _process_dicom_files(
    file_paths: List[str]
) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """Process a list of DICOM file paths into a volume."""
    if not file_paths:
        raise ValueError("No DICOM files provided")
    
    # Read all DICOM files
    slices = []
    for path in file_paths:
        try:
            ds = pydicom.dcmread(path)
            if "PixelData" in ds:
                slices.append(ds)
        except Exception:
            continue
    
    if not slices:
        raise ValueError("No valid DICOM files found")
    
    return _build_volume_from_slices(slices)


def _build_volume_from_slices(
    slices: List[pydicom.Dataset]
) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """
    Build a 3D volume from a list of DICOM slices.
    
    Handles sorting, spacing extraction, and HU conversion.
    """
    if not slices:
        raise ValueError("No slices provided")
    
    # Sort slices by Z position (ImagePositionPatient[2])
    try:
        slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))
    except AttributeError:
        # Fallback: try InstanceNumber
        try:
            slices.sort(key=lambda x: int(x.InstanceNumber))
        except AttributeError:
            # Last resort: use file index
            pass
    
    # Extract spacing
    try:
        pixel_spacing = slices[0].PixelSpacing
        slice_thickness = slices[0].SliceThickness
        spacing = (
            float(pixel_spacing[0]),
            float(pixel_spacing[1]),
            float(slice_thickness)
        )
    except AttributeError:
        raise ValueError(
            "DICOM files missing required spacing attributes "
            "(PixelSpacing, SliceThickness)"
        )
    
    # Build volume with HU conversion
    volume_slices = []
    for ds in slices:
        slice_data = process_dicom_slice(ds)
        volume_slices.append(slice_data)
    
    # Stack slices along Z axis
    # pydicom pixel_array is (Rows, Cols) = (Y, X)
    # After stacking: (Y, X, Z)
    volume_np = np.stack(volume_slices, axis=-1)
    
    # Transpose to (X, Y, Z) for consistency with NIfTI and standard orientation
    volume_np = np.transpose(volume_np, (1, 0, 2))
    
    return volume_np, spacing


def get_sort_position(ds: pydicom.Dataset) -> float:
    """
    Get the Z-position for slice sorting.
    
    Tries ImagePositionPatient first, then SliceLocation,
    then InstanceNumber.
    """
    if hasattr(ds, 'ImagePositionPatient'):
        return float(ds.ImagePositionPatient[2])
    elif hasattr(ds, 'SliceLocation'):
        return float(ds.SliceLocation)
    elif hasattr(ds, 'InstanceNumber'):
        return float(ds.InstanceNumber)
    else:
        return 0.0
