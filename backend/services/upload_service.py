"""
Upload service layer.

This keeps routers thin while preserving the existing local artifact workflow.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import shutil
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, HTTPException, UploadFile

from config import settings
from models.enums import CaseStatus
from processing import MedicalVolumeLoader
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


@dataclass(frozen=True)
class UploadSourceReference:
    """Reference to a staged upload source and the transport used to hand it off."""

    source_ref: str
    source_kind: str


@dataclass
class UploadBatchSession:
    """Typed view over batch-upload session state."""

    case_id: str
    storage_kind: str
    files_received: int = 0
    object_keys: List[str] = field(default_factory=list)
    object_prefix: Optional[str] = None
    temp_dir: Optional[str] = None

    @property
    def direct_upload_enabled(self) -> bool:
        return self.storage_kind == "object_store"

    @classmethod
    def create(
        cls,
        case_id: str,
        direct_upload_enabled: bool,
        artifacts: "UploadArtifactManager",
    ) -> "UploadBatchSession":
        if direct_upload_enabled:
            return cls(
                case_id=case_id,
                storage_kind="object_store",
                object_prefix=f"uploads/{case_id}/batch/",
            )

        return cls(
            case_id=case_id,
            storage_kind="local_dir",
            temp_dir=artifacts.create_temp_dir(f"batch_{case_id}_"),
        )

    @classmethod
    def from_payload(cls, case_id: str, payload: Dict[str, Any]) -> "UploadBatchSession":
        return cls(
            case_id=case_id,
            storage_kind=str(payload.get("storage_kind") or "local_dir"),
            files_received=int(payload.get("files_received", 0)),
            object_keys=list(payload.get("object_keys") or []),
            object_prefix=payload.get("object_prefix"),
            temp_dir=payload.get("temp_dir"),
        )

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "storage_kind": self.storage_kind,
            "files_received": self.files_received,
            "object_keys": list(self.object_keys),
        }
        if self.object_prefix is not None:
            payload["object_prefix"] = self.object_prefix
        if self.temp_dir is not None:
            payload["temp_dir"] = self.temp_dir
        return payload


class UploadArtifactManager:
    """Encapsulates temp-file staging and object-store handoff operations."""

    def __init__(self, object_store: ObjectStore | None = None):
        self.object_store = object_store

    @property
    def uses_ephemeral_temp_dirs(self) -> bool:
        return is_running_in_modal() and has_distributed_runtime()

    def create_temp_dir(self, prefix: str) -> str:
        """Create a temporary directory, preferring local ephemeral storage in distributed mode."""
        if self.uses_ephemeral_temp_dirs:
            return tempfile.mkdtemp(prefix=prefix)

        temp_base = settings.TEMP_STORAGE_ROOT / "uploads"
        temp_base.mkdir(parents=True, exist_ok=True)
        return tempfile.mkdtemp(prefix=prefix, dir=str(temp_base))

    @staticmethod
    def parse_metadata_payload(metadata: Optional[str]) -> Dict[str, Any]:
        """Parse optional JSON metadata payloads without aborting the upload flow."""
        if not metadata:
            return {}

        try:
            payload = json.loads(metadata)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def copy_upload_file(source: UploadFile, destination_path: str) -> None:
        """Persist an uploaded file with a larger buffer to reduce copy overhead."""
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            shutil.copyfileobj(source.file, handle, length=UPLOAD_COPY_BUFFER_SIZE)

    @staticmethod
    def build_staged_file_name(file_name: Optional[str], index: Optional[int] = None) -> str:
        """Create a collision-resistant staged filename while keeping the original basename visible."""
        safe_name = os.path.basename(file_name or f"{uuid.uuid4()}.dcm")
        if index is None:
            return f"{uuid.uuid4().hex}_{safe_name}"
        return f"{index:04d}_{safe_name}"

    def stage_upload_file(
        self,
        source: UploadFile,
        *,
        suffix: str,
        temp_dir: Optional[str] = None,
    ) -> str:
        """Copy an incoming upload into a temporary file and return its local path."""
        if temp_dir is not None:
            Path(temp_dir).mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=temp_dir) as tmp:
            shutil.copyfileobj(source.file, tmp, length=UPLOAD_COPY_BUFFER_SIZE)
            return tmp.name

    def upload_temp_file(
        self,
        local_path: str,
        object_key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a local staging file into object storage for worker handoff."""
        return self._require_object_store().upload_file(
            Path(local_path),
            object_key,
            content_type=content_type,
        )

    def download_object_to_temp(self, object_key: str, suffix: str) -> str:
        """Download an object-store artifact into a local temporary file."""
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self._require_object_store().download_file(object_key, Path(temp_path))
        return temp_path

    def download_object_to_path(self, object_key: str, destination_path: str) -> str:
        """Download an object-store artifact to a specific local path."""
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._require_object_store().download_file(object_key, destination)
        return str(destination)

    def delete_object_quietly(self, object_key: str) -> None:
        """Best-effort object cleanup for background workers."""
        if self.object_store is None:
            return

        try:
            self.object_store.delete_object(object_key)
        except Exception:
            traceback.print_exc()

    def _require_object_store(self) -> ObjectStore:
        if self.object_store is None:
            raise ValueError("Object store is required for object-backed upload handoff")
        return self.object_store


class UploadBackgroundProcessor:
    """Executes background upload processing against a repository instance."""

    def __init__(self, repo: CaseRepository, artifacts: UploadArtifactManager | None = None):
        self.repo = repo
        self.artifacts = artifacts or UploadArtifactManager(repo.object_store)

    def _update_upload_status(
        self,
        case_id: str,
        message: str,
        *,
        current_stage: str,
        progress_percent: float,
        status: str = CaseStatus.UPLOADING.value,
    ) -> None:
        self.repo.update_status(
            case_id,
            status,
            message,
            current_stage=current_stage,
            progress_percent=progress_percent,
        )

    def _publish_preview_first_best_effort(
        self,
        case_id: str,
        *,
        volume: Any,
        spacing: Any,
    ) -> bool:
        try:
            self._update_upload_status(
                case_id,
                "Generating preview...",
                current_stage="generating_preview",
                progress_percent=82.0,
            )
            return self.repo.publish_ct_preview(case_id, volume=volume, spacing=spacing)
        except Exception:
            traceback.print_exc()
            self.repo.mark_ct_preview_unavailable(case_id)
            return False

    def _generate_preview_best_effort(
        self,
        case_id: str,
        *,
        volume: Any,
        spacing: Any,
    ) -> None:
        try:
            self._update_upload_status(
                case_id,
                "Generating preview...",
                current_stage="generating_preview",
                progress_percent=92.0,
                status=CaseStatus.UPLOADED.value,
            )
            self.repo.generate_ct_preview(case_id, volume=volume, spacing=spacing)
        except Exception as exc:
            traceback.print_exc()
            self.repo.mark_ct_preview_unavailable(case_id)
            self.repo.update_status(
                case_id,
                CaseStatus.UPLOADED.value,
                f"CT volume ready. Preview generation failed: {exc}",
                current_stage="uploaded",
                progress_percent=100.0,
            )

    def process_single_upload(self, case_id: str, tmp_path: str, filename: str) -> None:
        """Background task to process a single ZIP or NIfTI upload."""
        try:
            self._update_upload_status(
                case_id,
                "Reading uploaded volume...",
                current_stage="reading_volume",
                progress_percent=20.0,
            )

            lower_name = filename.lower()
            load_started_at = time.perf_counter()
            metadata_payload: Dict[str, Any] | None = None
            if lower_name.endswith(".zip"):
                volume, spacing, representative_header, archive_metadata = MedicalVolumeLoader.load_dicom_series_with_metadata(tmp_path)
                metadata_payload = dict(archive_metadata or {})
                dicom_meta = MedicalVolumeLoader.extract_dicom_metadata(representative_header)
                if dicom_meta:
                    metadata_payload["dicom"] = dicom_meta
            elif lower_name.endswith((".nii", ".nii.gz")):
                volume, spacing = MedicalVolumeLoader.load_nifti(tmp_path)
            else:
                raise ValueError(f"Unsupported file format: {filename}")

            print(
                f"[UploadBackgroundProcessor] Loaded single upload {filename} for {case_id} "
                f"in {time.perf_counter() - load_started_at:.2f}s"
            )
            preview_ready = self._publish_preview_first_best_effort(case_id, volume=volume, spacing=spacing)
            self._update_upload_status(
                case_id,
                "Saving CT volume...",
                current_stage="saving_volume",
                progress_percent=90.0 if preview_ready else 86.0,
            )
            self.repo.save_ct_volume(case_id, volume, spacing, generate_preview=False)
            if metadata_payload:
                self.repo.save_extra_metadata(case_id, metadata_payload)
            if not preview_ready:
                self._generate_preview_best_effort(case_id, volume=volume, spacing=spacing)

        except Exception as exc:
            traceback.print_exc()
            self.repo.update_status(case_id, CaseStatus.ERROR.value, str(exc))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def process_single_upload_object(self, case_id: str, object_key: str, filename: str) -> None:
        """Background task to process a single uploaded object-store artifact."""
        suffix = "".join(Path(filename).suffixes) or Path(object_key).suffix
        temp_path = self.artifacts.download_object_to_temp(object_key, suffix=suffix)
        try:
            self.process_single_upload(case_id, temp_path, filename)
        finally:
            self.artifacts.delete_object_quietly(object_key)

    def process_dicom_directory(
        self,
        case_id: str,
        temp_dir: str,
        extra_metadata: Optional[Dict[str, Any]],
    ) -> None:
        """Background task to process a directory full of DICOM files."""
        try:
            overall_started_at = time.perf_counter()
            self._update_upload_status(
                case_id,
                "Reading DICOM headers...",
                current_stage="reading_dicom_headers",
                progress_percent=20.0,
            )

            dicom_files = self._collect_dicom_files(temp_dir)
            if not dicom_files:
                raise ValueError("No uploaded files found in batch directory")

            volume, spacing, metadata_payload = self._load_dicom_volume_from_paths(
                case_id,
                dicom_files,
                extra_metadata,
            )
            preview_ready = self._publish_preview_first_best_effort(case_id, volume=volume, spacing=spacing)
            self._update_upload_status(
                case_id,
                "Saving CT volume...",
                current_stage="saving_volume",
                progress_percent=90.0 if preview_ready else 86.0,
            )
            self.repo.save_ct_volume(case_id, volume, spacing, generate_preview=False)

            if metadata_payload:
                self.repo.save_extra_metadata(case_id, metadata_payload)
            if not preview_ready:
                self._generate_preview_best_effort(case_id, volume=volume, spacing=spacing)
            print(
                f"[UploadBackgroundProcessor] Processed DICOM directory for {case_id} "
                f"in {time.perf_counter() - overall_started_at:.2f}s"
            )

        except Exception as exc:
            traceback.print_exc()
            self.repo.update_status(case_id, CaseStatus.ERROR.value, str(exc))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def process_dicom_object_keys(
        self,
        case_id: str,
        object_keys: List[str],
        extra_metadata: Optional[Dict[str, Any]],
    ) -> None:
        """Background task to process DICOM files staged in object storage."""
        overall_started_at = time.perf_counter()
        temp_dir = self.artifacts.create_temp_dir(f"dicom_obj_{case_id}_")
        try:
            self._update_upload_status(
                case_id,
                "Downloading DICOM files from object storage...",
                current_stage="receiving_upload",
                progress_percent=10.0,
            )
            download_started_at = time.perf_counter()
            dicom_files = self._download_objects_to_directory_parallel(case_id, object_keys, temp_dir)
            print(
                f"[UploadBackgroundProcessor] Downloaded {len(dicom_files)} DICOM objects for {case_id} "
                f"in {time.perf_counter() - download_started_at:.2f}s"
            )

            volume, spacing, metadata_payload = self._load_dicom_volume_from_paths(
                case_id,
                dicom_files,
                extra_metadata,
            )
            preview_ready = self._publish_preview_first_best_effort(case_id, volume=volume, spacing=spacing)

            self._update_upload_status(
                case_id,
                "Saving CT volume...",
                current_stage="saving_volume",
                progress_percent=90.0 if preview_ready else 86.0,
            )
            self.repo.save_ct_volume(case_id, volume, spacing, generate_preview=False)
            if metadata_payload:
                self.repo.save_extra_metadata(case_id, metadata_payload)
            if not preview_ready:
                self._generate_preview_best_effort(case_id, volume=volume, spacing=spacing)
            print(
                f"[UploadBackgroundProcessor] Processed {len(object_keys)} object-backed DICOM files for {case_id} "
                f"in {time.perf_counter() - overall_started_at:.2f}s"
            )
        except Exception as exc:
            traceback.print_exc()
            self.repo.update_status(case_id, CaseStatus.ERROR.value, str(exc))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            for object_key in object_keys:
                self.artifacts.delete_object_quietly(object_key)

    def _load_dicom_volume_from_paths(
        self,
        case_id: str,
        dicom_files: List[str],
        extra_metadata: Optional[Dict[str, Any]],
    ) -> tuple[Any, Any, Dict[str, Any]]:
        if not dicom_files:
            raise ValueError("No DICOM files available for parsing")

        header_started_at = time.perf_counter()
        self._update_upload_status(
            case_id,
            "Reading DICOM headers...",
            current_stage="reading_dicom_headers",
            progress_percent=28.0,
        )
        selected_datasets, spacing, representative_header = MedicalVolumeLoader.load_selected_dicom_datasets(dicom_files)
        print(
            f"[UploadBackgroundProcessor] Selected {len(selected_datasets)}/{len(dicom_files)} DICOM files for primary series "
            f"for {case_id} in {time.perf_counter() - header_started_at:.2f}s"
        )

        parse_started_at = time.perf_counter()
        self._update_upload_status(
            case_id,
            "Decoding DICOM slices...",
            current_stage="decoding_dicom_slices",
            progress_percent=55.0,
        )
        volume, spacing = MedicalVolumeLoader.build_volume_from_datasets(selected_datasets, spacing)
        print(
            f"[UploadBackgroundProcessor] Decoded primary DICOM series for {case_id} "
            f"in {time.perf_counter() - parse_started_at:.2f}s"
        )

        metadata_payload = dict(extra_metadata or {})
        try:
            dicom_meta = MedicalVolumeLoader.extract_dicom_metadata(representative_header)
            if dicom_meta:
                metadata_payload["dicom"] = dicom_meta
        except Exception as meta_exc:
            print(f"[Metadata Extraction Error]: {meta_exc}")

        return volume, spacing, metadata_payload

    def _download_objects_to_directory_parallel(
        self,
        case_id: str,
        object_keys: List[str],
        temp_dir: str,
    ) -> List[str]:
        if not object_keys:
            return []
        if self.artifacts.object_store is None:
            raise ValueError("Object store is unavailable for object-backed DICOM ingest")

        max_workers = max(
            1,
            min(
                len(object_keys),
                settings.OBJECT_STORE_DOWNLOAD_CONCURRENCY,
            ),
        )
        results: list[str | None] = [None] * len(object_keys)
        completed = 0

        def download_one(index_and_key: tuple[int, str]) -> tuple[int, str]:
            index, object_key = index_and_key
            suffix = Path(object_key).suffix or ".dcm"
            local_path = os.path.join(temp_dir, f"{index:04d}{suffix}")
            self.artifacts.download_object_to_path(object_key, local_path)
            return index, local_path

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(download_one, (index, object_key))
                for index, object_key in enumerate(object_keys)
            ]
            for future in as_completed(futures):
                index, payload = future.result()
                results[index] = payload
                completed += 1

                if completed == 1 or completed == len(object_keys) or completed % 16 == 0:
                    progress = 10.0 + (completed / max(len(object_keys), 1)) * 15.0
                    self._update_upload_status(
                        case_id,
                        (
                            f"Downloaded {completed}/{len(object_keys)} DICOM files from object storage "
                            f"with concurrency={max_workers}..."
                        ),
                        current_stage="receiving_upload",
                        progress_percent=progress,
                    )

        missing_indexes = [index for index, path in enumerate(results) if path is None]
        if missing_indexes:
            raise ValueError(f"Failed to download {len(missing_indexes)} DICOM objects from object storage")

        return [path for path in results if path is not None]

    @staticmethod
    def _collect_dicom_files(temp_dir: str) -> List[str]:
        dicom_files: List[str] = []
        candidate_files: List[str] = []
        for root, _, files in os.walk(temp_dir):
            for file_name in files:
                lower_name = file_name.lower()
                if lower_name == "metadata.json":
                    continue

                file_path = os.path.join(root, file_name)
                if lower_name.endswith(".dcm"):
                    dicom_files.append(file_path)
                else:
                    candidate_files.append(file_path)
        return dicom_files + candidate_files

class UploadService:
    """Service for single-file and batch upload workflows."""

    def __init__(
        self,
        repo: CaseRepository,
        state_store: StateStore,
        artifacts: UploadArtifactManager | None = None,
        processor: UploadBackgroundProcessor | None = None,
    ):
        self.repo = repo
        self.state_store = state_store
        self.artifacts = artifacts or UploadArtifactManager(repo.object_store)
        self.processor = processor or UploadBackgroundProcessor(repo, self.artifacts)

    @property
    def _use_object_store_handoff(self) -> bool:
        return (
            is_running_in_modal()
            and has_distributed_runtime()
            and not settings.should_prefer_local_modal_ingest()
            and self.artifacts.object_store is not None
        )

    @property
    def _use_object_store_batch_handoff(self) -> bool:
        # Batch uploads span multiple requests, so worker-local temp directories are
        # unsafe once session state is shared across replicas or containers.
        return has_distributed_runtime() and self.artifacts.object_store is not None

    @property
    def _should_spawn_modal_ingest(self) -> bool:
        if not is_running_in_modal():
            return False
        if has_distributed_runtime() and settings.should_prefer_local_modal_ingest():
            return False
        return True

    def _create_upload_case(self, message: str) -> str:
        case_id = str(uuid.uuid4())
        self.repo.create_case(case_id)
        self.repo.update_status(case_id, CaseStatus.UPLOADING.value, message)
        return case_id

    def _single_upload_object_key(self, case_id: str, suffix: str) -> str:
        return f"uploads/{case_id}/source{suffix}"

    def _dicom_upload_object_key(self, case_id: str, file_name: str, index: int | None = None) -> str:
        safe_name = os.path.basename(file_name or f"{uuid.uuid4()}.dcm")
        prefix = f"{index:04d}_" if index is not None else ""
        return f"uploads/{case_id}/dicom/{prefix}{safe_name}"

    def _batch_upload_object_key(self, object_prefix: str, file_name: str) -> str:
        safe_name = os.path.basename(file_name or f"{uuid.uuid4()}.dcm")
        return f"{object_prefix}{uuid.uuid4().hex}_{safe_name}"

    def _require_batch_session(self, case_id: str, detail: str) -> UploadBatchSession:
        payload = self.state_store.get_batch_session(case_id)
        if payload is None:
            raise HTTPException(status_code=404, detail=detail)
        return UploadBatchSession.from_payload(case_id, payload)

    def _persist_batch_session(self, session: UploadBatchSession) -> UploadBatchSession:
        updated_payload = self.state_store.update_batch_session(
            session.case_id,
            session.to_payload(),
            ttl_seconds=settings.BATCH_SESSION_TTL_SECONDS,
        )
        if updated_payload is None:
            return session
        return UploadBatchSession.from_payload(session.case_id, updated_payload)

    def _stage_single_upload_source(
        self,
        case_id: str,
        file: UploadFile,
        filename: str,
        suffix: str,
    ) -> UploadSourceReference:
        temp_base = str(settings.TEMP_STORAGE_ROOT / "uploads")
        tmp_path = self.artifacts.stage_upload_file(file, suffix=suffix, temp_dir=temp_base)

        if self._use_object_store_handoff:
            object_key = self._single_upload_object_key(case_id, suffix)
            try:
                self.artifacts.upload_temp_file(tmp_path, object_key)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            return UploadSourceReference(source_ref=object_key, source_kind="object_store")

        commit_data_volume(scope="upload_handoff")
        return UploadSourceReference(source_ref=tmp_path, source_kind="local")

    def _stage_file_to_object_store(self, file: UploadFile, object_key: str, suffix: str) -> None:
        tmp_path = self.artifacts.stage_upload_file(file, suffix=suffix)
        try:
            self.artifacts.upload_temp_file(tmp_path, object_key)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _stage_uploads_to_directory(
        self,
        files: List[UploadFile],
        temp_dir: str,
        *,
        start_index: int = 0,
    ) -> int:
        saved_count = 0
        for index, file in enumerate(files, start=start_index):
            if not file.filename:
                continue
            file_path = os.path.join(
                temp_dir,
                self.artifacts.build_staged_file_name(file.filename, index=index),
            )
            self.artifacts.copy_upload_file(file, file_path)
            saved_count += 1
        return saved_count

    def _dispatch_single_upload(
        self,
        background_tasks: BackgroundTasks,
        case_id: str,
        source: UploadSourceReference,
        filename: str,
    ) -> None:
        if self._should_spawn_modal_ingest and spawn_single_upload(
            case_id,
            source.source_ref,
            filename,
            source_kind=source.source_kind,
        ):
            return

        if source.source_kind == "object_store":
            background_tasks.add_task(
                self.processor.process_single_upload_object,
                case_id,
                source.source_ref,
                filename,
            )
            return

        background_tasks.add_task(
            self.processor.process_single_upload,
            case_id,
            source.source_ref,
            filename,
        )

    def _dispatch_dicom_directory(
        self,
        background_tasks: BackgroundTasks,
        case_id: str,
        temp_dir: str,
        extra_metadata: Optional[Dict[str, Any]],
    ) -> None:
        if self._should_spawn_modal_ingest and spawn_dicom_directory(
            case_id,
            temp_dir,
            extra_metadata,
            source_kind="local_dir",
        ):
            return

        background_tasks.add_task(
            self.processor.process_dicom_directory,
            case_id,
            temp_dir,
            extra_metadata,
        )

    def _dispatch_dicom_object_keys(
        self,
        background_tasks: BackgroundTasks,
        case_id: str,
        object_keys: List[str],
        extra_metadata: Optional[Dict[str, Any]],
    ) -> None:
        if self._should_spawn_modal_ingest and spawn_dicom_directory(
            case_id,
            object_keys,
            extra_metadata,
            source_kind="object_store_keys",
        ):
            return

        background_tasks.add_task(
            self.processor.process_dicom_object_keys,
            case_id,
            object_keys,
            extra_metadata,
        )

    def upload_case(self, background_tasks: BackgroundTasks, file: UploadFile) -> Dict[str, str]:
        case_id = self._create_upload_case("Receiving file...")

        try:
            filename = file.filename or ""
            suffix = "".join(Path(filename).suffixes).lower()

            if not filename.lower().endswith((".zip", ".nii", ".nii.gz")):
                error_msg = f"Unsupported file format: {suffix}. Use .zip (DICOM) or .nii (NIfTI)"
                self.repo.update_status(case_id, CaseStatus.ERROR.value, error_msg)
                raise HTTPException(status_code=400, detail=error_msg)

            source = self._stage_single_upload_source(case_id, file, filename, suffix)
            self._dispatch_single_upload(background_tasks, case_id, source, filename)
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
        case_id = self._create_upload_case("Receiving files...")

        try:
            if not files:
                raise HTTPException(status_code=400, detail="No files provided")

            extra_metadata = self.artifacts.parse_metadata_payload(metadata)
            dcm_files = [
                file
                for file in files
                if file.filename and file.filename.lower() != "metadata.json"
            ]
            if not dcm_files:
                raise HTTPException(status_code=400, detail="No uploadable DICOM files found")

            if self._use_object_store_handoff:
                object_keys: List[str] = []
                for index, upload_file in enumerate(dcm_files):
                    suffix = Path(upload_file.filename or "").suffix or ".dcm"
                    object_key = self._dicom_upload_object_key(
                        case_id,
                        upload_file.filename or f"{index}.dcm",
                        index=index,
                    )
                    self._stage_file_to_object_store(upload_file, object_key, suffix=suffix)
                    object_keys.append(object_key)

                self._dispatch_dicom_object_keys(background_tasks, case_id, object_keys, extra_metadata)
            else:
                temp_dir = self.artifacts.create_temp_dir(f"dicom_{case_id}_")
                self._stage_uploads_to_directory(dcm_files, temp_dir)
                commit_data_volume(scope="upload_handoff")
                self._dispatch_dicom_directory(background_tasks, case_id, temp_dir, extra_metadata)

            return {"case_id": case_id, "status": CaseStatus.UPLOADING.value}

        except HTTPException:
            raise
        except Exception as exc:
            traceback.print_exc()
            self.repo.update_status(case_id, CaseStatus.ERROR.value, str(exc))
            raise HTTPException(status_code=500, detail=f"DICOM upload failed: {str(exc)}")

    def init_batch_upload(self) -> Dict[str, str | bool | int | None]:
        case_id = self._create_upload_case("Batch initialized")

        session = UploadBatchSession.create(
            case_id,
            direct_upload_enabled=self._use_object_store_batch_handoff,
            artifacts=self.artifacts,
        )
        self.state_store.create_batch_session(
            case_id,
            session.to_payload(),
            settings.BATCH_SESSION_TTL_SECONDS,
        )

        if not session.direct_upload_enabled:
            commit_data_volume(scope="upload_handoff")

        return {
            "case_id": case_id,
            "status": CaseStatus.UPLOADING.value,
            "storage_kind": session.storage_kind,
            "direct_upload_enabled": session.direct_upload_enabled,
            "upload_url_ttl_seconds": (
                settings.UPLOAD_URL_TTL_SECONDS if session.direct_upload_enabled else None
            ),
            "recommended_upload_concurrency": (
                settings.DIRECT_UPLOAD_CONCURRENCY if session.direct_upload_enabled else None
            ),
        }

    def prepare_batch_uploads(
        self,
        case_id: str,
        files: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        session = self._require_batch_session(
            case_id,
            "Batch session not found. Call /cases/batch/init first.",
        )
        if not session.direct_upload_enabled or self.repo.object_store is None:
            raise HTTPException(
                status_code=400,
                detail="Direct batch upload is not available for this session.",
            )
        if not files:
            raise HTTPException(status_code=400, detail="No files provided for presigning.")

        object_prefix = session.object_prefix or ""
        targets = []
        for file in files:
            client_id = str(file.get("client_id") or "").strip()
            filename = str(file.get("filename") or "").strip()
            if not client_id or not filename:
                raise HTTPException(
                    status_code=400,
                    detail="Each file must include client_id and filename.",
                )

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
        session = self._require_batch_session(
            case_id,
            "Batch session not found. Call /cases/batch/init first.",
        )
        if not session.direct_upload_enabled:
            raise HTTPException(
                status_code=400,
                detail="This batch session does not accept direct upload completion.",
            )
        if not uploads:
            raise HTTPException(status_code=400, detail="No uploaded objects provided.")

        object_prefix = session.object_prefix or ""
        known_keys = set(session.object_keys)
        saved_count = 0

        for upload in uploads:
            object_key = str(upload.get("object_key") or "").strip()
            if not object_key:
                raise HTTPException(
                    status_code=400,
                    detail="Each uploaded object must include object_key.",
                )
            if object_prefix and not object_key.startswith(object_prefix):
                raise HTTPException(
                    status_code=400,
                    detail="Uploaded object does not belong to this batch session.",
                )
            if object_key in known_keys:
                continue

            session.object_keys.append(object_key)
            known_keys.add(object_key)
            saved_count += 1

        session.files_received += saved_count
        session = self._persist_batch_session(session)
        return {
            "case_id": case_id,
            "files_saved": saved_count,
            "total_received": session.files_received,
        }

    def upload_batch_files(self, case_id: str, files: List[UploadFile]) -> Dict[str, int | str]:
        session = self._require_batch_session(
            case_id,
            "Batch session not found. Call /cases/batch/init first.",
        )

        saved_count = 0
        if session.direct_upload_enabled:
            if self.repo.object_store is None:
                raise HTTPException(
                    status_code=500,
                    detail="Object store is unavailable for this batch session.",
                )

            object_prefix = session.object_prefix or ""
            for upload_file in files:
                if not upload_file.filename:
                    continue
                suffix = Path(upload_file.filename).suffix or ".dcm"
                object_key = self._batch_upload_object_key(object_prefix, upload_file.filename)
                self._stage_file_to_object_store(upload_file, object_key, suffix=suffix)
                session.object_keys.append(object_key)
                saved_count += 1
        else:
            if not session.temp_dir:
                raise HTTPException(
                    status_code=500,
                    detail="Temporary directory is unavailable for this batch session.",
                )
            os.makedirs(session.temp_dir, exist_ok=True)
            saved_count = self._stage_uploads_to_directory(
                files,
                session.temp_dir,
                start_index=session.files_received,
            )

        session.files_received += saved_count
        session = self._persist_batch_session(session)
        if not session.direct_upload_enabled:
            commit_data_volume(scope="upload_handoff")

        return {
            "case_id": case_id,
            "files_saved": saved_count,
            "total_received": session.files_received,
        }

    def finalize_batch_upload(
        self,
        case_id: str,
        background_tasks: BackgroundTasks,
        metadata: Optional[str],
    ) -> Dict[str, str]:
        session = self._require_batch_session(case_id, "Batch session not found")
        extra_metadata = self.artifacts.parse_metadata_payload(metadata)
        self.state_store.delete_batch_session(case_id)

        if session.direct_upload_enabled:
            if self.repo.object_store is None:
                raise HTTPException(
                    status_code=500,
                    detail="Object store is unavailable for this batch session.",
                )
            self._dispatch_dicom_object_keys(
                background_tasks,
                case_id,
                list(session.object_keys),
                extra_metadata,
            )
        else:
            if not session.temp_dir:
                raise HTTPException(
                    status_code=500,
                    detail="Temporary directory is unavailable for this batch session.",
                )
            commit_data_volume(scope="upload_handoff")
            self._dispatch_dicom_directory(
                background_tasks,
                case_id,
                session.temp_dir,
                extra_metadata,
            )

        return {"case_id": case_id, "status": CaseStatus.UPLOADING.value}


# Backward-compatible module-level adapters for existing call sites.
def get_temp_dir(prefix: str) -> str:
    return UploadArtifactManager().create_temp_dir(prefix)



def parse_metadata_payload(metadata: Optional[str]) -> Dict[str, Any]:
    return UploadArtifactManager.parse_metadata_payload(metadata)



def copy_upload_file(source: UploadFile, destination_path: str) -> None:
    UploadArtifactManager.copy_upload_file(source, destination_path)



def build_staged_file_name(file_name: Optional[str], index: Optional[int] = None) -> str:
    return UploadArtifactManager.build_staged_file_name(file_name, index=index)



def upload_temp_file_to_object_store(
    local_path: str,
    object_store: ObjectStore,
    object_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    return UploadArtifactManager(object_store).upload_temp_file(
        local_path,
        object_key,
        content_type=content_type,
    )



def download_object_to_temp(
    object_store: ObjectStore,
    object_key: str,
    suffix: str,
) -> str:
    return UploadArtifactManager(object_store).download_object_to_temp(object_key, suffix=suffix)



def process_single_upload_task(
    case_id: str,
    tmp_path: str,
    filename: str,
    repo: CaseRepository,
) -> None:
    UploadBackgroundProcessor(repo).process_single_upload(case_id, tmp_path, filename)



def process_single_upload_object_task(
    case_id: str,
    object_key: str,
    filename: str,
    repo: CaseRepository,
) -> None:
    UploadBackgroundProcessor(repo).process_single_upload_object(case_id, object_key, filename)



def process_dicom_directory_task(
    case_id: str,
    temp_dir: str,
    repo: CaseRepository,
    extra_metadata: Optional[Dict[str, Any]],
) -> None:
    UploadBackgroundProcessor(repo).process_dicom_directory(case_id, temp_dir, extra_metadata)



def process_dicom_object_keys_task(
    case_id: str,
    object_keys: List[str],
    repo: CaseRepository,
    extra_metadata: Optional[Dict[str, Any]],
) -> None:
    UploadBackgroundProcessor(repo).process_dicom_object_keys(case_id, object_keys, extra_metadata)
