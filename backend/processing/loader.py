"""
DICOM and NIfTI Loader Module

Handles loading and parsing of medical imaging data formats.
Ensures proper HU conversion and metadata extraction.
"""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import tempfile
from typing import List, Tuple
import zipfile

import nibabel as nib
import numpy as np
import pydicom


class MedicalVolumeLoader:
    """Loader utilities for DICOM series and NIfTI volumes."""

    @classmethod
    def load_dicom_series(cls, zip_path: str) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """
        Load a DICOM series from a ZIP file.

        Returns:
            Tuple of:
            - volume: HU-converted volume as np.ndarray, shape (X, Y, Z)
            - spacing: Voxel spacing as (sx, sy, sz) in mm
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            dicom_files: list[str] = []
            for root, _, files in os.walk(temp_dir):
                for file_name in files:
                    if file_name.lower().endswith(".dcm"):
                        dicom_files.append(os.path.join(root, file_name))

            if not dicom_files:
                raise ValueError("No DICOM files found in ZIP archive")

            return cls._process_dicom_files(dicom_files)

    @classmethod
    def load_dicom_from_files(cls, file_paths: List[str]) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Load a DICOM series from a list of file paths."""
        return cls._process_dicom_files(file_paths)

    @classmethod
    def load_dicom_from_bytes_list(
        cls,
        file_contents: List[bytes],
    ) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Load a DICOM series from in-memory byte payloads."""
        if not file_contents:
            raise ValueError("No DICOM file contents provided")

        slices: list[pydicom.Dataset] = []
        for content in file_contents:
            try:
                ds = cls.parse_dicom_bytes(content)
                if "PixelData" in ds:
                    slices.append(ds)
            except Exception:
                continue

        if not slices:
            raise ValueError("No valid DICOM files could be parsed")

        return cls._build_volume_from_slices(slices)

    @staticmethod
    def load_nifti(file_path: str) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Load a NIfTI volume as (X, Y, Z) plus voxel spacing."""
        img = nib.load(file_path)
        volume = img.get_fdata(dtype=np.float32)

        header = img.header
        pixdim = header["pixdim"]
        spacing = (float(pixdim[1]), float(pixdim[2]), float(pixdim[3]))

        return volume, spacing

    @staticmethod
    def parse_dicom_bytes(content: bytes) -> pydicom.Dataset:
        """Parse a single DICOM file from bytes."""
        return pydicom.dcmread(BytesIO(content))

    @staticmethod
    def process_dicom_slice(ds: pydicom.Dataset) -> np.ndarray:
        """
        Convert a single DICOM slice from stored pixels to Hounsfield Units.
        """
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        raw_pixels = ds.pixel_array

        if slope == 1.0 and intercept == 0.0:
            return raw_pixels.astype(np.int16, copy=False)

        slice_data = raw_pixels.astype(np.float32, copy=False)
        slice_data = slice_data * slope + intercept
        return slice_data.astype(np.float32, copy=False)

    @staticmethod
    def extract_dicom_metadata(ds: pydicom.Dataset) -> dict:
        """Extract commonly used metadata fields from a DICOM dataset."""
        metadata: dict[str, object] = {}

        if hasattr(ds, "PatientName"):
            metadata["patient_name"] = str(ds.PatientName)
        if hasattr(ds, "PatientID"):
            metadata["patient_id"] = str(ds.PatientID)
        if hasattr(ds, "PatientBirthDate"):
            metadata["patient_birth_date"] = str(ds.PatientBirthDate)
        if hasattr(ds, "PatientSex"):
            metadata["patient_sex"] = str(ds.PatientSex)

        if hasattr(ds, "StudyDate"):
            metadata["study_date"] = str(ds.StudyDate)
        if hasattr(ds, "StudyDescription"):
            metadata["study_description"] = str(ds.StudyDescription)
        if hasattr(ds, "StudyInstanceUID"):
            metadata["study_uid"] = str(ds.StudyInstanceUID)

        if hasattr(ds, "SeriesDescription"):
            metadata["series_description"] = str(ds.SeriesDescription)
        if hasattr(ds, "SeriesInstanceUID"):
            metadata["series_uid"] = str(ds.SeriesInstanceUID)
        if hasattr(ds, "Modality"):
            metadata["modality"] = str(ds.Modality)

        if hasattr(ds, "Manufacturer"):
            metadata["manufacturer"] = str(ds.Manufacturer)
        if hasattr(ds, "KVP"):
            metadata["kvp"] = float(ds.KVP)
        if hasattr(ds, "SliceThickness"):
            metadata["slice_thickness"] = float(ds.SliceThickness)

        return metadata

    @classmethod
    def _process_dicom_files(
        cls,
        file_paths: List[str],
    ) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Process a list of DICOM file paths into a volume."""
        if not file_paths:
            raise ValueError("No DICOM files provided")

        slices: list[pydicom.Dataset] = []
        for path in file_paths:
            try:
                ds = pydicom.dcmread(path)
                if "PixelData" in ds:
                    slices.append(ds)
            except Exception:
                continue

        if not slices:
            raise ValueError("No valid DICOM files found")

        return cls._build_volume_from_slices(slices)

    @classmethod
    def _build_volume_from_slices(
        cls,
        slices: List[pydicom.Dataset],
    ) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Build a 3D volume from parsed DICOM slices."""
        if not slices:
            raise ValueError("No slices provided")

        try:
            slices.sort(key=lambda ds: float(ds.ImagePositionPatient[2]))
        except AttributeError:
            try:
                slices.sort(key=lambda ds: int(ds.InstanceNumber))
            except AttributeError:
                pass

        try:
            pixel_spacing = slices[0].PixelSpacing
            slice_thickness = slices[0].SliceThickness
            spacing = (
                float(pixel_spacing[0]),
                float(pixel_spacing[1]),
                float(slice_thickness),
            )
        except AttributeError as exc:
            raise ValueError(
                "DICOM files missing required spacing attributes (PixelSpacing, SliceThickness)"
            ) from exc

        volume_slices = [cls.process_dicom_slice(ds) for ds in slices]

        volume_np = np.stack(volume_slices, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))

        return volume_np, spacing

    @staticmethod
    def get_sort_position(ds: pydicom.Dataset) -> float:
        """Get a numeric Z-like position for slice ordering."""
        if hasattr(ds, "ImagePositionPatient"):
            return float(ds.ImagePositionPatient[2])
        if hasattr(ds, "SliceLocation"):
            return float(ds.SliceLocation)
        if hasattr(ds, "InstanceNumber"):
            return float(ds.InstanceNumber)
        return 0.0


def load_dicom_series(zip_path: str) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    return MedicalVolumeLoader.load_dicom_series(zip_path)


def load_dicom_from_files(file_paths: List[str]) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    return MedicalVolumeLoader.load_dicom_from_files(file_paths)


def load_dicom_from_bytes_list(
    file_contents: List[bytes],
) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    return MedicalVolumeLoader.load_dicom_from_bytes_list(file_contents)


def load_nifti(file_path: str) -> Tuple[np.ndarray, Tuple[float, float, float]]:
    return MedicalVolumeLoader.load_nifti(file_path)


def parse_dicom_bytes(content: bytes) -> pydicom.Dataset:
    return MedicalVolumeLoader.parse_dicom_bytes(content)


def process_dicom_slice(ds: pydicom.Dataset) -> np.ndarray:
    return MedicalVolumeLoader.process_dicom_slice(ds)


def extract_dicom_metadata(ds: pydicom.Dataset) -> dict:
    return MedicalVolumeLoader.extract_dicom_metadata(ds)


def get_sort_position(ds: pydicom.Dataset) -> float:
    return MedicalVolumeLoader.get_sort_position(ds)
