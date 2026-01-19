import numpy as np
import nibabel as nib
import pydicom
import zipfile
import tempfile
import os
from pathlib import Path
from typing import Tuple, List

def load_dicom_series(zip_path: str) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """
    Loads a DICOM series from a zip file.
    Returns: (volume_hu, (spacing_x, spacing_y, spacing_z))
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Find all DICOM files
        dicom_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('.dcm') or file.endswith('.DCM'):
                    dicom_files.append(os.path.join(root, file))
        
        if not dicom_files:
            raise ValueError("No DICOM files found in zip")
            
        # Sort files by InstanceNumber or SliceLocation
        slices = [pydicom.dcmread(f) for f in dicom_files]
        slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))
        
        # Calculate spacing
        try:
            pixel_spacing = slices[0].PixelSpacing
            slice_thickness = slices[0].SliceThickness
            # Check spacing consistency (basic check)
            spacing = (float(pixel_spacing[0]), float(pixel_spacing[1]), float(slice_thickness))
        except AttributeError:
             # Fallback or strict error? PRD says strict.
             raise ValueError("DICOM missing Spacing attributes")

        # Create volume
        # Rescale Slope/Intercept application is CRITICAL
        volume = []
        for s in slices:
            # pydicom .pixel_array is raw
            # We must apply rescale
            slope = getattr(s, 'RescaleSlope', 1)
            intercept = getattr(s, 'RescaleIntercept', 0)
            
            # Apply linear transformation: HU = m*x + b
            slice_data = s.pixel_array.astype(np.float64) * slope + intercept
            volume.append(slice_data)
            
        # Convert from (Y, X, Z) to (X, Y, Z) to match NIfTI and standard schema
        # pydicom pixel_array is (Rows, Cols) -> (Y, X)
        # Stacked on axis -1 -> (Y, X, Z)
        # Transpose to (X, Y, Z)
        volume_np = np.stack(volume, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        
        return volume_np, spacing

def load_nifti(file_path: str) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    """
    Loads a NIfTI file.
    Returns: (volume_hu, (spacing_x, spacing_y, spacing_z))
    """
    img = nib.load(file_path)
    # NIfTI usually applies slope/intercept automatically in get_fdata()
    # It returns float64.
    volume = img.get_fdata()
    
    header = img.header
    pixdim = header['pixdim'] # indexes 1,2,3 are x,y,z
    spacing = (float(pixdim[1]), float(pixdim[2]), float(pixdim[3]))
    
    return volume, spacing
