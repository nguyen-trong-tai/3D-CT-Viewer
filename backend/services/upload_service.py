"""
Upload service layer.

This keeps routers thin while preserving the existing local artifact workflow.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pydicom
from fastapi import BackgroundTasks, HTTPException, UploadFile

from config import settings
from models.enums import CaseStatus
from processing import extract_dicom_metadata, load_dicom_series, load_nifti
from storage.object_store.base import ObjectStore
from storage.repository import CaseRepository
from storage.state_store.base import StateStore
from workers.runtime import (
    commit_data_volume,
    has_distributed_runtime,
    is_running_in_modal,
    spawn_dicom_directory,
    spawn_single_upload,
)

UPLOAD_COPY_BUFFER_SIZE = 1024 * 1024


def get_temp_dir(prefix: str) -> str:
    """Create a temporary directory, preferring local ephemeral storage in distributed mode."""
    if is_running_in_modal() and has_distributed_runtime():
        return tempfile.mkdtemp(prefix=prefix)

    temp_base = settings.TEMP_STORAGE_ROOT / "uploads"
    temp_base.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=str(temp_base))


def parse_metadata_payload(metadata: Optional[str]) -> dict:
    """Parse optional JSON metadata payloads without aborting the upload flow."""
    if not metadata:
        return {}

    try:
        payload = json.loads(metadata)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def copy_upload_file(source: UploadFile, destination_path: str) -> None:
    """Persist an uploaded file with a larger buffer to reduce copy overhead."""
    with open(destination_path, "wb") as destination:
        shutil.copyfileobj(source.file, destination, length=UPLOAD_COPY_BUFFER_SIZE)


def build_staged_file_name(file_name: Optional[str], index: Optional[int] = None) -> str:
    """Create a collision-resistant staged filename while keeping the original basename visible."""
    safe_name = os.path.basename(file_name or f"{uuid.uuid4()}.dcm")
    if index is None:
        return f"{uuid.uuid4().hex}_{safe_name}"
    return f"{index:04d}_{safe_name}"


def upload_temp_file_to_object_store(
    local_path: str,
    object_store: ObjectStore,
    object_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload a temporary local file to object storage for worker handoff."""
    return object_store.upload_file(Path(local_path), object_key, content_type=content_type)


def download_object_to_temp(
    object_store: ObjectStore,
    object_key: str,
    suffix: str,
) -> str:
    """Download an object-store artifact into a local temporary file."""
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    object_store.download_file(object_key, Path(temp_path))
    return temp_path


def process_single_upload_task(case_id: str, tmp_path: str, filename: str, repo: CaseRepository):
    """Background task to process a single ZIP or NIfTI upload."""
    try:
        repo.update_status(case_id, CaseStatus.UPLOADING.value, "Processing volume data...")

        if filename.lower().endswith(".zip"):
            volume, spacing = load_dicom_series(tmp_path)
        elif filename.lower().endswith((".nii", ".nii.gz")):
            volume, spacing = load_nifti(tmp_path)
        else:
            raise ValueError(f"Unsupported file format: {filename}")

        repo.save_ct_volume(case_id, volume, spacing)

    except Exception as exc:
        traceback.print_exc()
        repo.update_status(case_id, CaseStatus.ERROR.value, str(exc))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def process_single_upload_object_task(
    case_id: str,
    object_key: str,
    filename: str,
    repo: CaseRepository,
):
    """Background task to process a single uploaded object-store artifact."""
    if repo.object_store is None:
        raise ValueError("Object store is required for object-backed upload handoff")

    suffix = "".join(Path(filename).suffixes) or Path(object_key).suffix
    temp_path = download_object_to_temp(repo.object_store, object_key, suffix=suffix)
    try:
        process_single_upload_task(case_id, temp_path, filename, repo)
    finally:
        try:
            repo.object_store.delete_object(object_key)
        except Exception:
            traceback.print_exc()


def process_dicom_directory_task(
    case_id: str,
    temp_dir: str,
    repo: CaseRepository,
    extra_metadata: Optional[dict],
):
    """Background task to process a directory full of DICOM files."""
    try:
        repo.update_status(case_id, CaseStatus.UPLOADING.value, "Processing DICOM directory...")

        dicom_files = []
        for root, _, files in os.walk(temp_dir):
            for file_name in files:
                if file_name.lower().endswith(".dcm"):
                    dicom_files.append(os.path.join(root, file_name))

        if not dicom_files:
            raise ValueError("No DICOM files found in batch directory")

        from processing.loader import load_dicom_from_files

        volume, spacing = load_dicom_from_files(dicom_files)
        repo.save_ct_volume(case_id, volume, spacing)

        if extra_metadata is None:
            extra_metadata = {}

        try:
            ds = pydicom.dcmread(dicom_files[0], stop_before_pixels=True)
            dicom_meta = extract_dicom_metadata(ds)
            if dicom_meta:
                extra_metadata.update({"dicom": dicom_meta})
        except Exception as meta_exc:
            print(f"[Metadata Extraction Error]: {meta_exc}")

        if extra_metadata:
            repo.save_extra_metadata(case_id, extra_metadata)

    except Exception as exc:
        traceback.print_exc()
        repo.update_status(case_id, CaseStatus.ERROR.value, str(exc))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def process_dicom_object_keys_task(
    case_id: str,
    object_keys: List[str],
    repo: CaseRepository,
    extra_metadata: Optional[dict],
):
    """Background task to process DICOM files staged in object storage."""
    if repo.object_store is None:
        raise ValueError("Object store is required for object-backed DICOM handoff")

    temp_dir = get_temp_dir(f"dicom_obj_{case_id}_")
    try:
        for index, object_key in enumerate(object_keys):
            suffix = Path(object_key).suffix or ".dcm"
            local_path = os.path.join(temp_dir, f"{index:04d}{suffix}")
            repo.object_store.download_file(object_key, Path(local_path))

        process_dicom_directory_task(case_id, temp_dir, repo, extra_metadata)
    finally:
        for object_key in object_keys:
            try:
                repo.object_store.delete_object(object_key)
            except Exception:
                traceback.print_exc()


class UploadService:
    """Service for single-file and batch upload workflows."""

    def __init__(self, repo: CaseRepository, state_store: StateStore):
        self.repo = repo
        self.state_store = state_store

    @property
    def _use_object_store_handoff(self) -> bool:
        return is_running_in_modal() and has_distributed_runtime() and self.repo.object_store is not None

    def _single_upload_object_key(self, case_id: str, suffix: str) -> str:
        return f"uploads/{case_id}/source{suffix}"

    def _dicom_upload_object_key(self, case_id: str, file_name: str, index: int | None = None) -> str:
        safe_name = os.path.basename(file_name or f"{uuid.uuid4()}.dcm")
        prefix = f"{index:04d}_" if index is not None else ""
        return f"uploads/{case_id}/dicom/{prefix}{safe_name}"

    def _batch_upload_object_key(self, object_prefix: str, file_name: str) -> str:
        safe_name = os.path.basename(file_name or f"{uuid.uuid4()}.dcm")
        return f"{object_prefix}{uuid.uuid4().hex}_{safe_name}"

    def upload_case(self, background_tasks: BackgroundTasks, file: UploadFile) -> Dict[str, str]:
        case_id = str(uuid.uuid4())
        self.repo.create_case(case_id)
        self.repo.update_status(case_id, CaseStatus.UPLOADING.value, "Receiving file...")

        try:
            filename = file.filename or ""
            suffixes = Path(filename).suffixes
            suffix = "".join(suffixes).lower()

            if not filename.lower().endswith((".zip", ".nii", ".nii.gz")):
                error_msg = f"Unsupported file format: {suffix}. Use .zip (DICOM) or .nii (NIfTI)"
                self.repo.update_status(case_id, CaseStatus.ERROR.value, error_msg)
                raise HTTPException(status_code=400, detail=error_msg)

            temp_base = settings.TEMP_STORAGE_ROOT / "uploads"
            temp_base.mkdir(parents=True, exist_ok=True)

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=str(temp_base)) as tmp:
                shutil.copyfileobj(file.file, tmp, length=UPLOAD_COPY_BUFFER_SIZE)
                tmp_path = tmp.name

            source_ref = tmp_path
            source_kind = "local"
            if self._use_object_store_handoff and self.repo.object_store is not None:
                object_key = self._single_upload_object_key(case_id, suffix)
                upload_temp_file_to_object_store(tmp_path, self.repo.object_store, object_key)
                os.remove(tmp_path)
                source_ref = object_key
                source_kind = "object_store"
            else:
                commit_data_volume(scope="upload_handoff")

            if not spawn_single_upload(case_id, source_ref, filename, source_kind=source_kind):
                if source_kind == "object_store":
                    background_tasks.add_task(process_single_upload_object_task, case_id, source_ref, filename, self.repo)
                else:
                    background_tasks.add_task(process_single_upload_task, case_id, tmp_path, filename, self.repo)

            return {"case_id": case_id, "status": CaseStatus.UPLOADING.value}

        except HTTPException:
            raise
        except Exception as exc:
            traceback.print_exc()
            self.repo.update_status(case_id, CaseStatus.ERROR.value, str(exc))
            raise HTTPException(status_code=500, detail=f"Upload failed: {str(exc)}")

    def upload_dicom_files(
        self,
        background_tasks: BackgroundTasks,
        files: List[UploadFile],
        metadata: Optional[str],
    ) -> Dict[str, str]:
        case_id = str(uuid.uuid4())
        self.repo.create_case(case_id)
        self.repo.update_status(case_id, CaseStatus.UPLOADING.value, "Receiving files...")

        try:
            if not files:
                raise HTTPException(status_code=400, detail="No files provided")

            extra_metadata = parse_metadata_payload(metadata)

            dcm_files = [file for file in files if file.filename and file.filename.lower().endswith(".dcm")]
            if not dcm_files:
                raise HTTPException(status_code=400, detail="No valid DICOM files (.dcm) found")

            if self._use_object_store_handoff and self.repo.object_store is not None:
                object_keys: List[str] = []
                for index, file in enumerate(dcm_files):
                    suffix = Path(file.filename or "").suffix or ".dcm"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        shutil.copyfileobj(file.file, tmp, length=UPLOAD_COPY_BUFFER_SIZE)
                        tmp_path = tmp.name
                    object_key = self._dicom_upload_object_key(case_id, file.filename or f"{index}.dcm", index=index)
                    try:
                        upload_temp_file_to_object_store(tmp_path, self.repo.object_store, object_key)
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    object_keys.append(object_key)

                if not spawn_dicom_directory(case_id, object_keys, extra_metadata, source_kind="object_store_keys"):
                    background_tasks.add_task(process_dicom_object_keys_task, case_id, object_keys, self.repo, extra_metadata)
            else:
                temp_dir = get_temp_dir(f"dicom_{case_id}_")

                for index, file in enumerate(dcm_files):
                    file_path = os.path.join(temp_dir, build_staged_file_name(file.filename, index=index))
                    copy_upload_file(file, file_path)

                commit_data_volume(scope="upload_handoff")

                if not spawn_dicom_directory(case_id, temp_dir, extra_metadata, source_kind="local_dir"):
                    background_tasks.add_task(process_dicom_directory_task, case_id, temp_dir, self.repo, extra_metadata)

            return {"case_id": case_id, "status": CaseStatus.UPLOADING.value}

        except HTTPException:
            raise
        except Exception as exc:
            traceback.print_exc()
            self.repo.update_status(case_id, CaseStatus.ERROR.value, str(exc))
            raise HTTPException(status_code=500, detail=f"DICOM upload failed: {str(exc)}")

    def init_batch_upload(self) -> Dict[str, str | bool | int | None]:
        case_id = str(uuid.uuid4())
        self.repo.create_case(case_id)
        self.repo.update_status(case_id, CaseStatus.UPLOADING.value, "Batch initialized")

        direct_upload_enabled = self._use_object_store_handoff
        payload = {
            "storage_kind": "object_store" if direct_upload_enabled else "local_dir",
            "files_received": 0,
            "object_keys": [],
        }
        if direct_upload_enabled:
            payload["object_prefix"] = f"uploads/{case_id}/batch/"
        else:
            payload["temp_dir"] = get_temp_dir(f"batch_{case_id}_")
        self.state_store.create_batch_session(case_id, payload, settings.BATCH_SESSION_TTL_SECONDS)
        if not direct_upload_enabled:
            commit_data_volume(scope="upload_handoff")
        return {
            "case_id": case_id,
            "status": CaseStatus.UPLOADING.value,
            "storage_kind": payload["storage_kind"],
            "direct_upload_enabled": direct_upload_enabled,
            "upload_url_ttl_seconds": settings.UPLOAD_URL_TTL_SECONDS if direct_upload_enabled else None,
            "recommended_upload_concurrency": settings.DIRECT_UPLOAD_CONCURRENCY if direct_upload_enabled else None,
        }

    def prepare_batch_uploads(
        self,
        case_id: str,
        files: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        session = self.state_store.get_batch_session(case_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Batch session not found. Call /cases/batch/init first.")
        if session.get("storage_kind") != "object_store" or self.repo.object_store is None:
            raise HTTPException(status_code=400, detail="Direct batch upload is not available for this session.")
        if not files:
            raise HTTPException(status_code=400, detail="No files provided for presigning.")

        object_prefix = session["object_prefix"]
        targets = []
        for file in files:
            client_id = str(file.get("client_id") or "").strip()
            filename = str(file.get("filename") or "").strip()
            if not client_id or not filename:
                raise HTTPException(status_code=400, detail="Each file must include client_id and filename.")

            object_key = self._batch_upload_object_key(object_prefix, filename)
            upload_url = self.repo.object_store.generate_upload_url(
                object_key,
                expires_in_seconds=settings.UPLOAD_URL_TTL_SECONDS,
            )
            targets.append(
                {
                    "client_id": client_id,
                    "filename": filename,
                    "object_key": object_key,
                    "upload_url": upload_url,
                    "method": "PUT",
                }
            )

        return {
            "case_id": case_id,
            "expires_in_seconds": settings.UPLOAD_URL_TTL_SECONDS,
            "targets": targets,
        }

    def complete_batch_uploads(
        self,
        case_id: str,
        uploads: List[Dict[str, Any]],
    ) -> Dict[str, int | str]:
        session = self.state_store.get_batch_session(case_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Batch session not found. Call /cases/batch/init first.")
        if session.get("storage_kind") != "object_store":
            raise HTTPException(status_code=400, detail="This batch session does not accept direct upload completion.")
        if not uploads:
            raise HTTPException(status_code=400, detail="No uploaded objects provided.")

        object_prefix = str(session.get("object_prefix") or "")
        object_keys = list(session.get("object_keys", []))
        known_keys = set(object_keys)
        saved_count = 0

        for upload in uploads:
            object_key = str(upload.get("object_key") or "").strip()
            if not object_key:
                raise HTTPException(status_code=400, detail="Each uploaded object must include object_key.")
            if object_prefix and not object_key.startswith(object_prefix):
                raise HTTPException(status_code=400, detail="Uploaded object does not belong to this batch session.")
            if object_key in known_keys:
                continue
            object_keys.append(object_key)
            known_keys.add(object_key)
            saved_count += 1

        files_received = int(session.get("files_received", 0)) + saved_count
        updated_session = self.state_store.update_batch_session(
            case_id,
            {"files_received": files_received, "object_keys": object_keys},
            ttl_seconds=settings.BATCH_SESSION_TTL_SECONDS,
        )
        return {
            "case_id": case_id,
            "files_saved": saved_count,
            "total_received": int(updated_session["files_received"]) if updated_session else files_received,
        }

    def upload_batch_files(self, case_id: str, files: List[UploadFile]) -> Dict[str, int | str]:
        session = self.state_store.get_batch_session(case_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Batch session not found. Call /cases/batch/init first.")

        saved_count = 0
        object_keys = list(session.get("object_keys", []))
        if session.get("storage_kind") == "object_store" and self.repo.object_store is not None:
            object_prefix = session["object_prefix"]
            for file in files:
                if not file.filename:
                    continue
                suffix = Path(file.filename).suffix or ".dcm"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    shutil.copyfileobj(file.file, tmp, length=UPLOAD_COPY_BUFFER_SIZE)
                    tmp_path = tmp.name
                object_key = self._batch_upload_object_key(object_prefix, file.filename)
                try:
                    upload_temp_file_to_object_store(tmp_path, self.repo.object_store, object_key)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                object_keys.append(object_key)
                saved_count += 1
        else:
            temp_dir = session["temp_dir"]
            os.makedirs(temp_dir, exist_ok=True)
            start_index = int(session.get("files_received", 0))
            for index, file in enumerate(files, start=start_index):
                if file.filename:
                    file_path = os.path.join(temp_dir, build_staged_file_name(file.filename, index=index))
                    copy_upload_file(file, file_path)
                    saved_count += 1

        files_received = int(session.get("files_received", 0)) + saved_count
        updates = {"files_received": files_received}
        if session.get("storage_kind") == "object_store":
            updates["object_keys"] = object_keys
        session = self.state_store.update_batch_session(case_id, updates, ttl_seconds=settings.BATCH_SESSION_TTL_SECONDS)
        if session.get("storage_kind") != "object_store":
            commit_data_volume(scope="upload_handoff")
        return {
            "case_id": case_id,
            "files_saved": saved_count,
            "total_received": int(session["files_received"]) if session else files_received,
        }

    def finalize_batch_upload(
        self,
        case_id: str,
        background_tasks: BackgroundTasks,
        metadata: Optional[str],
    ) -> Dict[str, str]:
        session = self.state_store.get_batch_session(case_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Batch session not found")

        extra_metadata = parse_metadata_payload(metadata)
        self.state_store.delete_batch_session(case_id)
        if session.get("storage_kind") == "object_store" and self.repo.object_store is not None:
            object_keys = list(session.get("object_keys", []))
            if not spawn_dicom_directory(case_id, object_keys, extra_metadata, source_kind="object_store_keys"):
                background_tasks.add_task(process_dicom_object_keys_task, case_id, object_keys, self.repo, extra_metadata)
        else:
            temp_dir = session["temp_dir"]
            commit_data_volume(scope="upload_handoff")

            if not spawn_dicom_directory(case_id, temp_dir, extra_metadata, source_kind="local_dir"):
                background_tasks.add_task(process_dicom_directory_task, case_id, temp_dir, self.repo, extra_metadata)

        return {"case_id": case_id, "status": CaseStatus.UPLOADING.value}
