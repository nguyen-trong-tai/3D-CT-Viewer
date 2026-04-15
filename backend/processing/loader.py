"""
DICOM and NIfTI Loader Module

Handles loading and parsing of medical imaging data formats.
Ensures proper HU conversion and metadata extraction.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter
from typing import Any, List, Tuple
import zipfile

import nibabel as nib
import numpy as np
import pydicom

from config import settings


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
        volume, spacing, _, _ = cls.load_dicom_series_with_metadata(zip_path)
        return volume, spacing

    @classmethod
    def load_dicom_series_with_metadata(
        cls,
        zip_path: str,
    ) -> Tuple[np.ndarray, Tuple[float, float, float], pydicom.Dataset, dict[str, Any]]:
        """
        Load a DICOM series from a ZIP file and return any bundled metadata.json payload.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            dicom_files: list[str] = []
            for root, _, files in os.walk(temp_dir):
                for file_name in files:
                    if file_name.lower() == "metadata.json":
                        continue
                    dicom_files.append(os.path.join(root, file_name))

            if not dicom_files:
                raise ValueError("No uploaded files found in ZIP archive")

            selected_datasets, spacing, representative_header = cls.load_selected_dicom_datasets(dicom_files)
            volume, spacing = cls.build_volume_from_datasets(selected_datasets, spacing)
            archive_metadata = cls._load_archive_metadata(temp_dir)
            return volume, spacing, representative_header, archive_metadata

    @classmethod
    def load_dicom_from_files(cls, file_paths: List[str]) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Load a DICOM series from a list of file paths."""
        selected_datasets, spacing, _ = cls.load_selected_dicom_datasets(file_paths)
        return cls.build_volume_from_datasets(selected_datasets, spacing)

    @classmethod
    def load_selected_dicom_datasets(
        cls,
        file_paths: List[str],
    ) -> Tuple[List[pydicom.Dataset], Tuple[float, float, float], pydicom.Dataset]:
        """Select the primary series from headers first, then load only that series' datasets."""
        if not file_paths:
            raise ValueError("No DICOM files provided")

        started_at = perf_counter()
        headers = cls._load_candidate_dicom_file_headers(file_paths)
        if not headers:
            raise ValueError("No valid DICOM files found")

        selected_headers = cls._select_primary_series_headers(headers)
        selected_entries = cls._load_dataset_entries_from_selected_headers(selected_headers)
        if len(selected_entries) != len(selected_headers):
            # Fall back to the legacy full scan when header-first selection cannot be decoded
            # completely. This keeps series selection and pipeline output stable for partially
            # corrupt or mixed-content folders while still accelerating the common case.
            dataset_entries = cls._load_candidate_dicom_datasets(file_paths)
            if not dataset_entries:
                raise ValueError("No valid DICOM files found")
            selected_entries = cls._select_primary_series_headers(dataset_entries)

        spacing = cls._extract_spacing(selected_entries[0]["header"])
        selected_datasets = [entry["dataset"] for entry in selected_entries]
        print(
            f"[MedicalVolumeLoader] Loaded and selected primary DICOM series with {len(selected_datasets)}/{len(file_paths)} slices "
            f"in {perf_counter() - started_at:.2f}s"
        )
        return selected_datasets, spacing, selected_entries[0]["header"]

    @classmethod
    def build_volume_from_datasets(
        cls,
        slices: List[pydicom.Dataset],
        spacing: Tuple[float, float, float],
    ) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Build a CT volume from already loaded DICOM datasets."""
        if not slices:
            raise ValueError("No DICOM datasets provided")
        return cls._build_volume_from_slices(slices, spacing=spacing)

    @classmethod
    def inspect_dicom_file_paths(
        cls,
        file_paths: List[str],
    ) -> Tuple[List[str], Tuple[float, float, float], pydicom.Dataset]:
        """Inspect DICOM file paths, select the primary series, and return ordered paths."""
        if not file_paths:
            raise ValueError("No DICOM files provided")

        started_at = perf_counter()
        headers = cls._load_candidate_dicom_file_headers(file_paths)
        if not headers:
            raise ValueError("No valid DICOM files found")

        selected_headers = cls._select_primary_series_headers(headers)
        spacing = cls._extract_spacing(selected_headers[0]["header"])
        ordered_paths = [str(entry["source"]) for entry in selected_headers]
        print(
            f"[MedicalVolumeLoader] Selected primary DICOM series with {len(ordered_paths)}/{len(file_paths)} slices "
            f"in {perf_counter() - started_at:.2f}s"
        )
        return ordered_paths, spacing, selected_headers[0]["header"]

    @classmethod
    def load_dicom_from_selected_files(
        cls,
        selected_paths: List[str],
        spacing: Tuple[float, float, float],
    ) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Decode a pre-selected ordered DICOM file list into a volume."""
        if not selected_paths:
            raise ValueError("No selected DICOM files provided")

        started_at = perf_counter()
        if len(selected_paths) >= 8:
            max_workers = cls._dicom_worker_count(len(selected_paths))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                volume_slices = [
                    slice_data
                    for slice_data in executor.map(cls._load_and_process_dicom_path, selected_paths)
                    if slice_data is not None
                ]
        else:
            volume_slices = [
                slice_data
                for slice_data in (cls._load_and_process_dicom_path(path) for path in selected_paths)
                if slice_data is not None
            ]

        if not volume_slices:
            raise ValueError("No valid DICOM files found")

        volume_np = np.stack(volume_slices, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        print(
            f"[MedicalVolumeLoader] Decoded and stacked {len(volume_slices)} selected DICOM slices "
            f"into volume {tuple(volume_np.shape)} in {perf_counter() - started_at:.2f}s"
        )
        return volume_np, spacing

    @classmethod
    def load_dicom_from_bytes_list(
        cls,
        file_contents: List[bytes],
    ) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Load a DICOM series from in-memory byte payloads."""
        if not file_contents:
            raise ValueError("No DICOM file contents provided")

        started_at = perf_counter()
        selected_contents, spacing = cls._prepare_dicom_byte_payloads(file_contents)
        if not selected_contents:
            raise ValueError("No valid DICOM files could be parsed")

        slices: list[pydicom.Dataset] = []
        for content in selected_contents:
            try:
                ds = cls.parse_dicom_bytes(content)
                if "PixelData" in ds:
                    slices.append(ds)
            except Exception:
                continue

        if not slices:
            raise ValueError("No valid DICOM files could be parsed")

        print(
            f"[MedicalVolumeLoader] Parsed {len(slices)} in-memory DICOM slices "
            f"in {perf_counter() - started_at:.2f}s"
        )
        return cls._build_volume_from_slices(slices, spacing=spacing)

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
    def parse_dicom_bytes(content: bytes, stop_before_pixels: bool = False) -> pydicom.Dataset:
        """Parse a single DICOM file from bytes."""
        return pydicom.dcmread(BytesIO(content), stop_before_pixels=stop_before_pixels)

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
        selected_paths, spacing, _ = cls.inspect_dicom_file_paths(file_paths)
        return cls.load_dicom_from_selected_files(selected_paths, spacing)

    @classmethod
    def _build_volume_from_slices(
        cls,
        slices: List[pydicom.Dataset],
        spacing: Tuple[float, float, float] | None = None,
    ) -> Tuple[np.ndarray, Tuple[float, float, float]]:
        """Build a 3D volume from parsed DICOM slices."""
        if not slices:
            raise ValueError("No slices provided")

        started_at = perf_counter()
        try:
            slices.sort(key=lambda ds: float(ds.ImagePositionPatient[2]))
        except AttributeError:
            try:
                slices.sort(key=lambda ds: int(ds.InstanceNumber))
            except AttributeError:
                pass

        if spacing is None:
            spacing = cls._extract_spacing(slices[0])

        if len(slices) >= 8:
            max_workers = cls._dicom_worker_count(len(slices))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                volume_slices = list(executor.map(cls.process_dicom_slice, slices))
        else:
            volume_slices = [cls.process_dicom_slice(ds) for ds in slices]

        volume_np = np.stack(volume_slices, axis=-1)
        volume_np = np.transpose(volume_np, (1, 0, 2))
        print(
            f"[MedicalVolumeLoader] Decoded and stacked {len(slices)} slices "
            f"into volume {tuple(volume_np.shape)} in {perf_counter() - started_at:.2f}s"
        )

        return volume_np, spacing

    @classmethod
    def _prepare_dicom_file_paths(
        cls,
        file_paths: List[str],
    ) -> Tuple[List[str], Tuple[float, float, float]]:
        ordered_paths, spacing, _ = cls.inspect_dicom_file_paths(file_paths)
        return ordered_paths, spacing

    @classmethod
    def _load_candidate_dicom_file_headers(
        cls,
        file_paths: List[str],
    ) -> List[dict[str, Any]]:
        def read_header(path: str) -> dict[str, Any] | None:
            try:
                header = pydicom.dcmread(path, stop_before_pixels=True)
                if cls._looks_like_image_slice(header):
                    return {"source": path, "header": header}
            except Exception:
                return None
            return None

        if len(file_paths) >= 8:
            max_workers = cls._dicom_worker_count(len(file_paths))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                return [entry for entry in executor.map(read_header, file_paths) if entry is not None]

        headers: List[dict[str, Any]] = []
        for path in file_paths:
            entry = read_header(path)
            if entry is not None:
                headers.append(entry)
        return headers

    @classmethod
    def _load_candidate_dicom_datasets(
        cls,
        file_paths: List[str],
    ) -> List[dict[str, Any]]:
        def read_dataset(path: str) -> dict[str, Any] | None:
            try:
                dataset = pydicom.dcmread(path)
                if cls._looks_like_image_slice(dataset) and "PixelData" in dataset:
                    return {
                        "source": path,
                        "header": dataset,
                        "dataset": dataset,
                    }
            except Exception:
                return None
            return None

        if len(file_paths) >= 8:
            max_workers = cls._dicom_worker_count(len(file_paths))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                return [entry for entry in executor.map(read_dataset, file_paths) if entry is not None]

        datasets: List[dict[str, Any]] = []
        for path in file_paths:
            entry = read_dataset(path)
            if entry is not None:
                datasets.append(entry)
        return datasets

    @classmethod
    def _load_dataset_entries_from_selected_headers(
        cls,
        selected_headers: List[dict[str, Any]],
    ) -> List[dict[str, Any]]:
        def read_selected_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
            path = str(entry["source"])
            try:
                dataset = pydicom.dcmread(path)
                if cls._looks_like_image_slice(dataset) and "PixelData" in dataset:
                    return {
                        "source": path,
                        "header": dataset,
                        "dataset": dataset,
                    }
            except Exception:
                return None
            return None

        if len(selected_headers) >= 8:
            max_workers = cls._dicom_worker_count(len(selected_headers))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                return [entry for entry in executor.map(read_selected_entry, selected_headers) if entry is not None]

        datasets: List[dict[str, Any]] = []
        for header_entry in selected_headers:
            entry = read_selected_entry(header_entry)
            if entry is not None:
                datasets.append(entry)
        return datasets

    @classmethod
    def _prepare_dicom_byte_payloads(
        cls,
        file_contents: List[bytes],
    ) -> Tuple[List[bytes], Tuple[float, float, float]]:
        headers = []
        for content in file_contents:
            try:
                header = cls.parse_dicom_bytes(content, stop_before_pixels=True)
                if cls._looks_like_image_slice(header):
                    headers.append({"source": content, "header": header})
            except Exception:
                continue

        if not headers:
            raise ValueError("No valid DICOM files could be parsed")

        selected_headers = cls._select_primary_series_headers(headers)
        spacing = cls._extract_spacing(selected_headers[0]["header"])
        ordered_contents = [entry["source"] for entry in selected_headers]
        return ordered_contents, spacing

    @classmethod
    def _select_primary_series_headers(
        cls,
        headers: List[dict[str, Any]],
    ) -> List[dict[str, Any]]:
        series_counts: dict[str, int] = {}
        for entry in headers:
            header = entry["header"]
            series_uid = str(getattr(header, "SeriesInstanceUID", "") or "")
            if series_uid:
                series_counts[series_uid] = series_counts.get(series_uid, 0) + 1

        if series_counts:
            primary_series_uid = max(series_counts.items(), key=lambda item: item[1])[0]
            headers = [
                entry
                for entry in headers
                if str(getattr(entry["header"], "SeriesInstanceUID", "") or "") == primary_series_uid
            ]

        headers.sort(key=lambda entry: cls.get_sort_position(entry["header"]))
        return headers

    @staticmethod
    def _dicom_worker_count(item_count: int) -> int:
        configured = max(1, int(getattr(settings, "MAX_WORKERS", os.cpu_count() or 1) or 1))
        return max(1, min(item_count, configured))

    @staticmethod
    def _looks_like_image_slice(ds: pydicom.Dataset) -> bool:
        return hasattr(ds, "Rows") and hasattr(ds, "Columns")

    @staticmethod
    def _load_and_process_dicom_path(path: str) -> np.ndarray | None:
        try:
            ds = pydicom.dcmread(path)
            if "PixelData" not in ds:
                return None
            return MedicalVolumeLoader.process_dicom_slice(ds)
        except Exception:
            return None

    @staticmethod
    def _load_archive_metadata(extracted_dir: str) -> dict[str, Any]:
        for root, _, files in os.walk(extracted_dir):
            for file_name in files:
                if file_name.lower() != "metadata.json":
                    continue
                metadata_path = Path(root) / file_name
                try:
                    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        return payload
                except Exception:
                    return {}
        return {}

    @staticmethod
    def _extract_spacing(ds: pydicom.Dataset) -> Tuple[float, float, float]:
        try:
            pixel_spacing = ds.PixelSpacing
            slice_thickness = ds.SliceThickness
            return (
                float(pixel_spacing[0]),
                float(pixel_spacing[1]),
                float(slice_thickness),
            )
        except AttributeError as exc:
            raise ValueError(
                "DICOM files missing required spacing attributes (PixelSpacing, SliceThickness)"
            ) from exc

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
