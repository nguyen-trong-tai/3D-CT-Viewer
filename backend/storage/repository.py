"""
Storage Repository

File-based persistence layer for CT volumes, masks, meshes, and case metadata.
Implements the repository pattern for clean separation of storage concerns.
"""

import os
import json
import math
from io import BytesIO
import numpy as np
import trimesh
from pathlib import Path
from time import perf_counter
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

from config import settings
from models.enums import CaseStatus
from storage.object_store.base import ObjectStore
from storage.state_store.base import StateStore
from workers.runtime import commit_data_volume, reload_data_volume


class CaseRepository:
    """
    Repository for managing case data and artifacts.
    
    Storage structure per case:
    {STORAGE_ROOT}/{case_id}/
        ├── status.json           # Case status and metadata
        ├── ct_volume.npy         # HU volume data (int16)
        ├── ct_metadata.json      # Volume dimensions, spacing, etc.
        ├── extra_metadata.json   # Patient/study info (optional)
        ├── mask_volume.npy       # Segmentation mask (uint8)
        ├── sdf_volume.npy        # SDF data (float32)
        └── mesh.glb              # Surface mesh (Draco-compressed GLB format)
    """
    
    def __init__(self, root_dir: Path = None, state_store: StateStore = None, object_store: ObjectStore = None):
        self.root_dir = root_dir or settings.STORAGE_ROOT
        self.state_store = state_store
        self.object_store = object_store
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def sync_for_read(self, scope: str = "artifact"):
        """Refresh shared Modal volume reads when still needed for the given scope."""
        reload_data_volume(scope=scope)

    def sync_for_write(self, scope: str = "artifact"):
        """Commit shared Modal volume writes when still needed for the given scope."""
        commit_data_volume(scope=scope)
        
    def _case_dir(self, case_id: str) -> Path:
        """Get the directory path for a specific case."""
        return self.root_dir / case_id

    def _preview_downsample_factor(self, shape: Tuple[int, int, int]) -> int:
        """Choose an integer downsample factor for remote preview artifacts."""
        if not shape:
            return 1

        factor_by_dim = max(1, math.ceil(max(shape) / max(settings.PREVIEW_MAX_DIM, 1)))
        voxel_count = int(np.prod(shape))
        factor_by_voxels = max(
            1,
            math.ceil((voxel_count / max(settings.PREVIEW_MAX_VOXELS, 1)) ** (1.0 / 3.0)),
        )
        return max(factor_by_dim, factor_by_voxels)

    def _build_preview_volume(
        self,
        volume: np.ndarray,
        spacing: Tuple[float, float, float],
        dtype: np.dtype,
    ) -> Tuple[Optional[np.ndarray], Optional[Tuple[float, float, float]], int]:
        """
        Build a smaller preview artifact for fast first paint in remote viewers.

        Strided sampling keeps preview generation cheap while preserving orientation.
        """
        factor = self._preview_downsample_factor(tuple(int(dim) for dim in volume.shape))
        if factor <= 1:
            return None, None, 1

        preview = np.ascontiguousarray(volume[::factor, ::factor, ::factor].astype(dtype, copy=False))
        preview_spacing = tuple(float(value) * factor for value in spacing)
        return preview, preview_spacing, factor

    def _update_ct_metadata(self, case_id: str, updates: Dict[str, Any]) -> None:
        """Merge preview-related updates into the canonical CT metadata artifact."""
        metadata_path = self._case_dir(case_id) / "ct_metadata.json"
        if not metadata_path.exists():
            return

        metadata = self._load_json(metadata_path)
        metadata.update(updates)
        self._save_json(metadata_path, metadata)

        metadata_object_key = self._ct_metadata_object_key(case_id)
        if self.object_store and metadata_path.exists():
            self.object_store.upload_bytes(
                json.dumps(metadata).encode("utf-8"),
                metadata_object_key,
                content_type="application/json",
            )

    def _save_ct_metadata_artifact(self, case_id: str, metadata: Dict[str, Any]) -> str:
        """Persist CT metadata locally and in object storage, then update the artifact manifest."""
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        metadata_path = case_path / "ct_metadata.json"
        self._save_json(metadata_path, metadata)

        metadata_object_key = self._ct_metadata_object_key(case_id)
        if self.object_store and metadata_path.exists():
            self.object_store.upload_bytes(
                json.dumps(metadata).encode("utf-8"),
                metadata_object_key,
                content_type="application/json",
            )

        if self.state_store:
            self.state_store.set_artifact(case_id, "ct_metadata", True, object_key=metadata_object_key)

        return metadata_object_key

    @staticmethod
    def _build_ct_metadata_payload(
        volume: np.ndarray,
        spacing: Tuple[float, float, float],
    ) -> Dict[str, Any]:
        """Build the canonical CT metadata payload from a full-resolution volume."""
        volume_int16 = volume.astype(np.int16, copy=False)
        return {
            "shape": list(volume_int16.shape),
            "spacing": list(spacing),
            "dtype": "int16",
            "hu_range": {
                "min": float(np.min(volume_int16)),
                "max": float(np.max(volume_int16)),
            },
            "preview_available": False,
            "preview_generation_pending": True,
            "preview_mask_available": False,
            "preview_downsample_factor": 1,
        }

    @staticmethod
    def _serialize_npy_bytes(array: np.ndarray) -> bytes:
        buffer = BytesIO()
        np.save(buffer, array, allow_pickle=False)
        return buffer.getvalue()

    def _prepare_npy_upload_path(self, case_id: str, artifact_filename: str) -> Tuple[Path, bool]:
        """
        Return a writable path for NPY artifacts.

        In distributed mode we still materialize the NPY locally so boto3 can use multipart
        file uploads, then delete the temporary file after the upload completes.
        """
        if not self._should_skip_local_volume_persist():
            case_path = self._case_dir(case_id)
            case_path.mkdir(parents=True, exist_ok=True)
            return case_path / artifact_filename, False

        temp_dir = settings.TEMP_STORAGE_ROOT / "artifact_uploads" / case_id
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir / artifact_filename, True

    @staticmethod
    def _cleanup_temp_artifact_path(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        finally:
            parent = path.parent
            try:
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass

    def _should_skip_local_volume_persist(self) -> bool:
        return bool(self.object_store and settings.should_use_r2_object_store())
    
    def case_exists(self, case_id: str) -> bool:
        """Check if a case exists."""
        if self._case_dir(case_id).exists():
            return True
        if settings.has_redis_state() and self.state_store and self.state_store.get_case_status(case_id):
            return True
        return False
        # Case Lifecycle Management    
    def create_case(self, case_id: str) -> bool:
        """
        Create a new case directory and initialize status.
        
        Returns True if created, False if already exists.
        """
        case_path = self._case_dir(case_id)
        if case_path.exists() or (settings.has_redis_state() and self.state_store and self.state_store.get_case_status(case_id)):
            return False

        status_data = {
            "status": CaseStatus.PENDING.value,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        status_data = self._ensure_retention_fields(status_data)
        if self.state_store:
            self.state_store.initialize_case(case_id)
            self.state_store.initialize_artifacts(case_id, self._empty_artifact_manifest())
        if not settings.has_redis_state():
            case_path.mkdir(parents=True, exist_ok=True)
            self._save_json(case_path / "status.json", status_data)
        self.sync_for_write(scope="state")
        
        return True
    
    def delete_case(self, case_id: str) -> bool:
        """
        Delete a case and all its artifacts.
        
        Returns True if deleted, False if not found.
        """
        import shutil
        case_path = self._case_dir(case_id)
        cache_path = settings.TEMP_STORAGE_ROOT / "cache" / case_id
        if not case_path.exists():
            if not self.state_store:
                return False
        else:
            shutil.rmtree(case_path, ignore_errors=True)
        if cache_path.exists():
            shutil.rmtree(cache_path, ignore_errors=True)
        if settings.has_redis_state() and self.state_store:
            self.state_store.delete_case(case_id)
        if self.object_store:
            self.object_store.delete_prefix(self._case_prefix(case_id))
            self.object_store.delete_prefix(self._upload_prefix(case_id))
        self.sync_for_write(scope="all")
        return True
        # Status Management    
    def update_status(
        self,
        case_id: str,
        status: str,
        message: str = None,
        current_stage: str = None,
        progress_percent: float = None,
    ):
        """Update the status of a case."""
        if settings.has_redis_state() and self.state_store:
            self.state_store.update_case_status(
                case_id,
                status,
                message=message,
                current_stage=current_stage,
                progress_percent=progress_percent,
            )
            self.sync_for_write(scope="state")
            return

        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        status_file = case_path / "status.json"

        # Load existing or create new
        if status_file.exists():
            status_data = self._load_json(status_file)
        else:
            status_data = {"created_at": datetime.utcnow().isoformat()}

        status_data = self._ensure_retention_fields(status_data)
        status_data["status"] = status
        status_data["updated_at"] = datetime.utcnow().isoformat()
        if message is not None:
            status_data["message"] = message
        if current_stage is not None:
            status_data["current_stage"] = current_stage
        if progress_percent is not None:
            status_data["progress_percent"] = progress_percent

        self._save_json(status_file, status_data)
        self.sync_for_write(scope="state")
    
    def get_status(self, case_id: str) -> str:
        """
        Get the current status of a case.
        
        Returns the status string, or "uploaded" for early state,
        or "error" if case doesn't exist.
        """
        if settings.has_redis_state() and self.state_store:
            status = self.state_store.get_case_status(case_id)
            if status:
                return status

        case_path = self._case_dir(case_id)
        status_file = case_path / "status.json"
        
        if not case_path.exists():
            return "error"  # Case doesn't exist
            
        if not status_file.exists():
            # Early state - status file not yet created
            return CaseStatus.UPLOADED.value
        
        status_data = self._load_json(status_file)
        return status_data.get("status", CaseStatus.UPLOADED.value)
    
    def get_status_info(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Get full status information for a case."""
        if settings.has_redis_state() and self.state_store:
            payload = self.state_store.get_case_status_info(case_id)
            if payload:
                return self._ensure_retention_fields(payload)
        status_file = self._case_dir(case_id) / "status.json"
        if not status_file.exists():
            return None
        return self._ensure_retention_fields(self._load_json(status_file))

    def get_artifact_path(
        self,
        case_id: str,
        artifact_name: str,
        *,
        prefer_remote: bool = False,
    ) -> Optional[Path]:
        """Resolve an artifact path without materializing the full payload in memory."""
        preferred_local_path = self._preferred_local_artifact_path(case_id, artifact_name)
        if preferred_local_path is None:
            return None

        resolved_path = self._resolve_artifact_path(
            case_id,
            artifact_name,
            preferred_local_path,
            prefer_remote=prefer_remote,
        )
        if not resolved_path.exists():
            return None
        return resolved_path

    def get_npy_artifact_stream_info(
        self,
        case_id: str,
        artifact_name: str,
        *,
        prefer_remote: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Return streaming metadata for a persisted NPY artifact."""
        artifact_path = self.get_artifact_path(case_id, artifact_name, prefer_remote=prefer_remote)
        if artifact_path is None or not artifact_path.exists():
            return None

        mmap_array: Optional[np.memmap] = None
        try:
            mmap_array = np.load(artifact_path, mmap_mode="r")
            data_offset = int(getattr(mmap_array, "offset", 0))
            content_length = max(0, artifact_path.stat().st_size - data_offset)
            return {
                "path": artifact_path,
                "shape": tuple(int(value) for value in mmap_array.shape),
                "dtype": str(np.dtype(mmap_array.dtype)),
                "data_offset": data_offset,
                "content_length": content_length,
            }
        except Exception:
            return None
        finally:
            if mmap_array is not None:
                mmap_handle = getattr(mmap_array, "_mmap", None)
                if mmap_handle is not None:
                    mmap_handle.close()
                del mmap_array

    def get_expired_case_ids(self) -> list[str]:
        """List case ids whose retention window has elapsed."""
        expired_case_ids: set[str] = set()
        now = datetime.utcnow()

        if self.root_dir.exists():
            for case_path in self.root_dir.iterdir():
                if not case_path.is_dir():
                    continue
                status_file = case_path / "status.json"
                if not status_file.exists():
                    continue
                try:
                    payload = self._ensure_retention_fields(self._load_json(status_file))
                except Exception:
                    continue
                if self._is_payload_expired(payload, now):
                    expired_case_ids.add(case_path.name)

        if self.state_store:
            for case_id, payload in self.state_store.list_case_statuses().items():
                payload = self._ensure_retention_fields(payload)
                if self._is_payload_expired(payload, now):
                    expired_case_ids.add(case_id)

        return sorted(expired_case_ids)

    def delete_expired_cases(self) -> list[str]:
        """Delete all cases whose retention window has elapsed."""
        deleted_case_ids: list[str] = []
        for case_id in self.get_expired_case_ids():
            if self.delete_case(case_id):
                deleted_case_ids.append(case_id)
        return deleted_case_ids
        # CT Volume Storage    
    def save_ct_volume(
        self, 
        case_id: str, 
        volume: np.ndarray, 
        spacing: Tuple[float, float, float],
        generate_preview: bool = True,
    ):
        """
        Save CT volume and metadata.
        
        Volume is saved as int16 to preserve HU values (-1024 to +3071 typical range).
        """
        started_at = perf_counter()
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        existing_metadata = self.load_ct_metadata(case_id) or {}
        preview_already_available = bool(existing_metadata.get("preview_available"))
        
        # Save volume as int16 (preserves full HU range)
        volume_int16 = volume.astype(np.int16, copy=False)
        volume_path, cleanup_after_upload = self._prepare_npy_upload_path(case_id, "ct_volume.npy")
        local_save_started_at = perf_counter()
        volume_object_key = self._ct_volume_object_key(case_id)
        np.save(volume_path, volume_int16, allow_pickle=False)
        local_save_duration = perf_counter() - local_save_started_at

        upload_duration = 0.0
        if self.object_store:
            upload_started_at = perf_counter()
            if volume_path.exists():
                self.object_store.upload_file(
                    volume_path,
                    volume_object_key,
                    content_type="application/octet-stream",
                )
            upload_duration = perf_counter() - upload_started_at
        if cleanup_after_upload:
            self._cleanup_temp_artifact_path(volume_path)

        metadata = self._build_ct_metadata_payload(volume_int16, spacing)
        metadata["preview_available"] = preview_already_available
        metadata["preview_generation_pending"] = not (generate_preview or preview_already_available)
        metadata["preview_mask_available"] = bool(existing_metadata.get("preview_mask_available"))
        metadata["preview_downsample_factor"] = int(existing_metadata.get("preview_downsample_factor") or 1)
        if "preview_shape" in existing_metadata:
            metadata["preview_shape"] = existing_metadata.get("preview_shape")
        if "preview_spacing" in existing_metadata:
            metadata["preview_spacing"] = existing_metadata.get("preview_spacing")
        if "mask_is_labeled" in existing_metadata:
            metadata["mask_is_labeled"] = bool(existing_metadata.get("mask_is_labeled"))

        metadata_started_at = perf_counter()
        metadata_object_key = self._save_ct_metadata_artifact(case_id, metadata)
        metadata_duration = perf_counter() - metadata_started_at
        
        print(
            f"[CaseRepository] Saved CT volume for {case_id} in {perf_counter() - started_at:.2f}s "
            f"(shape={tuple(volume.shape)}, local_save={local_save_duration:.2f}s, "
            f"upload={upload_duration:.2f}s, metadata={metadata_duration:.2f}s)"
        )

        if preview_already_available:
            status_message = "CT volume ready."
            current_stage = "uploaded"
            progress_percent = 100.0
        elif generate_preview:
            status_message = "CT volume uploaded."
            current_stage = "uploaded"
            progress_percent = 100.0
        else:
            status_message = "CT volume ready. Generating preview..."
            current_stage = "saving_volume"
            progress_percent = 85.0

        self.update_status(
            case_id,
            CaseStatus.UPLOADED.value,
            message=status_message,
            current_stage=current_stage,
            progress_percent=progress_percent,
        )
        if self.state_store:
            self.state_store.set_artifact(case_id, "ct_volume", True, object_key=volume_object_key)
            self.state_store.set_artifact(case_id, "ct_metadata", True, object_key=metadata_object_key)
            self.state_store.set_artifact(
                case_id,
                "ct_volume_preview",
                preview_already_available,
                object_key=self._ct_preview_volume_object_key(case_id) if preview_already_available else None,
            )
        self.sync_for_write(scope="artifact")

        if generate_preview:
            self.generate_ct_preview(case_id, volume=volume_int16, spacing=spacing)

    def publish_ct_preview(
        self,
        case_id: str,
        volume: np.ndarray,
        spacing: Tuple[float, float, float],
    ) -> bool:
        """Persist metadata plus a downsampled CT preview before the full volume upload finishes."""
        started_at = perf_counter()
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)

        volume_int16 = volume.astype(np.int16, copy=False)
        metadata = self._build_ct_metadata_payload(volume_int16, spacing)
        preview_volume, preview_spacing, preview_factor = self._build_preview_volume(volume_int16, spacing, np.int16)
        preview_available = preview_volume is not None and preview_spacing is not None
        preview_object_key = self._ct_preview_volume_object_key(case_id)

        metadata["preview_available"] = preview_available
        metadata["preview_generation_pending"] = False
        metadata["preview_mask_available"] = False
        metadata["preview_downsample_factor"] = preview_factor if preview_available else 1
        metadata["preview_shape"] = list(preview_volume.shape) if preview_available and preview_volume is not None else None
        metadata["preview_spacing"] = list(preview_spacing) if preview_available and preview_spacing is not None else None

        metadata_object_key = self._save_ct_metadata_artifact(case_id, metadata)

        if preview_available and preview_volume is not None:
            preview_path, cleanup_after_upload = self._prepare_npy_upload_path(case_id, "ct_preview_volume.npy")
            np.save(preview_path, preview_volume, allow_pickle=False)
            if self.object_store and preview_path.exists():
                self.object_store.upload_file(
                    preview_path,
                    preview_object_key,
                    content_type="application/octet-stream",
                )
            if cleanup_after_upload:
                self._cleanup_temp_artifact_path(preview_path)

        if self.state_store:
            self.state_store.set_artifact(case_id, "ct_metadata", True, object_key=metadata_object_key)
            self.state_store.set_artifact(
                case_id,
                "ct_volume_preview",
                preview_available,
                object_key=preview_object_key if preview_available else None,
            )

        self.sync_for_write(scope="artifact")
        print(
            f"[CaseRepository] Published CT preview for {case_id} in {perf_counter() - started_at:.2f}s "
            f"(available={preview_available})"
        )
        return preview_available

    def generate_ct_preview(
        self,
        case_id: str,
        volume: Optional[np.ndarray] = None,
        spacing: Optional[Tuple[float, float, float]] = None,
    ) -> bool:
        """Generate and persist a downsampled preview volume without blocking upload readiness."""
        started_at = perf_counter()
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)

        metadata = self.load_ct_metadata(case_id) or {}
        if volume is None:
            loaded = self.load_ct_volume(case_id)
            if loaded is None:
                return False
            volume = loaded.astype(np.int16, copy=False)
        else:
            volume = volume.astype(np.int16, copy=False)

        if spacing is None:
            spacing_values = metadata.get("spacing")
            spacing = tuple(float(value) for value in spacing_values) if spacing_values else (1.0, 1.0, 1.0)

        preview_volume, preview_spacing, preview_factor = self._build_preview_volume(volume, spacing, np.int16)
        preview_object_key = self._ct_preview_volume_object_key(case_id)
        preview_available = preview_volume is not None and preview_spacing is not None

        if preview_available and preview_volume is not None and preview_spacing is not None:
            preview_path, cleanup_after_upload = self._prepare_npy_upload_path(case_id, "ct_preview_volume.npy")
            np.save(preview_path, preview_volume, allow_pickle=False)
            if self.object_store:
                if preview_path.exists():
                    self.object_store.upload_file(
                        preview_path,
                        preview_object_key,
                        content_type="application/octet-stream",
                    )
            if cleanup_after_upload:
                self._cleanup_temp_artifact_path(preview_path)

        metadata_updates: Dict[str, Any] = {
            "preview_available": preview_available,
            "preview_generation_pending": False,
            "preview_downsample_factor": preview_factor if preview_available else 1,
        }
        if preview_available and preview_volume is not None and preview_spacing is not None:
            metadata_updates["preview_shape"] = list(preview_volume.shape)
            metadata_updates["preview_spacing"] = list(preview_spacing)
        else:
            metadata_updates["preview_shape"] = None
            metadata_updates["preview_spacing"] = None

        self._update_ct_metadata(case_id, metadata_updates)

        if self.state_store:
            self.state_store.set_artifact(
                case_id,
                "ct_volume_preview",
                preview_available,
                object_key=preview_object_key if preview_available else None,
            )
        self.sync_for_write(scope="artifact")
        self.update_status(
            case_id,
            CaseStatus.UPLOADED.value,
            message="CT volume ready.",
            current_stage="uploaded",
            progress_percent=100.0,
        )
        print(
            f"[CaseRepository] Generated CT preview for {case_id} in {perf_counter() - started_at:.2f}s "
            f"(available={preview_available})"
        )
        return preview_available

    def mark_ct_preview_unavailable(self, case_id: str) -> None:
        """Finalize preview state when preview generation is skipped or fails."""
        self._update_ct_metadata(
            case_id,
            {
                "preview_available": False,
                "preview_generation_pending": False,
                "preview_downsample_factor": 1,
                "preview_shape": None,
                "preview_spacing": None,
            },
        )
        if self.state_store:
            self.state_store.set_artifact(case_id, "ct_volume_preview", False, object_key=None)
        self.sync_for_write(scope="artifact")
    
    def load_ct_volume(self, case_id: str) -> Optional[np.ndarray]:
        """Load CT volume data."""
        path = self._resolve_artifact_path(case_id, "ct_volume", self._case_dir(case_id) / "ct_volume.npy")
        if not path.exists():
            return None
        return np.load(path)
    
    def load_ct_volume_mmap(self, case_id: str) -> Optional[np.ndarray]:
        """Load CT volume with memory mapping for efficient slice access."""
        path = self._resolve_artifact_path(case_id, "ct_volume", self._case_dir(case_id) / "ct_volume.npy")
        if not path.exists():
            return None
        return np.load(path, mmap_mode='r')

    def load_ct_preview_volume(self, case_id: str) -> Optional[np.ndarray]:
        """Load downsampled CT preview volume when available."""
        path = self._resolve_artifact_path(case_id, "ct_volume_preview", self._case_dir(case_id) / "ct_preview_volume.npy")
        if not path.exists():
            return None
        return np.load(path)
    
    def load_ct_metadata(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Load CT volume metadata."""
        path = self._case_dir(case_id) / "ct_metadata.json"
        if path.exists():
            return self._load_json(path)

        object_key = self.get_artifact_object_key(case_id, "ct_metadata")
        if self.object_store and object_key:
            try:
                payload = self.object_store.download_bytes(object_key)
                return json.loads(payload.decode("utf-8"))
            except Exception:
                pass
        return None
        # Extra Metadata (Patient Info, Study Details)    
    def save_extra_metadata(self, case_id: str, metadata: Dict[str, Any]):
        """Save additional metadata (patient info, study details, etc.)."""
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        metadata_path = case_path / "extra_metadata.json"
        self._save_json(metadata_path, metadata)
        metadata_object_key = self._extra_metadata_object_key(case_id)
        if self.object_store and metadata_path.exists():
            self.object_store.upload_file(metadata_path, metadata_object_key, content_type="application/json")
        if self.state_store:
            self.state_store.set_artifact(case_id, "extra_metadata", True, object_key=metadata_object_key)
        self.sync_for_write(scope="artifact")
    
    def load_extra_metadata(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Load additional metadata if available."""
        path = self._case_dir(case_id) / "extra_metadata.json"
        if path.exists():
            return self._load_json(path)

        object_key = self.get_artifact_object_key(case_id, "extra_metadata")
        if self.object_store and object_key:
            try:
                payload = self.object_store.download_bytes(object_key)
                return json.loads(payload.decode("utf-8"))
            except Exception:
                pass
        return None
        # Segmentation Mask Storage    
    def save_mask(self, case_id: str, mask: np.ndarray, manifest: Optional[Dict[str, Any]] = None):
        """Save segmentation mask as uint8, optionally with a segmentation manifest."""
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        mask_uint8 = mask.astype(np.uint8, copy=False)
        mask_path = case_path / "mask_volume.npy"
        np.save(mask_path, mask_uint8)
        mask_object_key = self._mask_volume_object_key(case_id)
        if self.object_store and mask_path.exists():
            self.object_store.upload_file(mask_path, mask_object_key, content_type="application/octet-stream")

        metadata = self.load_ct_metadata(case_id) or {}
        spacing = tuple(metadata.get("spacing", [1.0, 1.0, 1.0]))
        preview_mask, preview_spacing, preview_factor = self._build_preview_volume(mask_uint8, spacing, np.uint8)
        preview_available = preview_mask is not None and preview_spacing is not None
        preview_object_key = self._mask_preview_volume_object_key(case_id)
        if preview_available:
            preview_path = case_path / "mask_preview_volume.npy"
            np.save(preview_path, preview_mask)
            if self.object_store and preview_path.exists():
                self.object_store.upload_file(preview_path, preview_object_key, content_type="application/octet-stream")

        self._update_ct_metadata(
            case_id,
            {
                "preview_mask_available": preview_available,
                "preview_downsample_factor": preview_factor if preview_available else metadata.get("preview_downsample_factor", 1),
                "mask_is_labeled": bool(manifest),
            },
        )
        manifest_object_key = self._segmentation_manifest_object_key(case_id)
        if manifest:
            manifest_path = case_path / "mask_manifest.json"
            self._save_json(manifest_path, manifest)
            if self.object_store and manifest_path.exists():
                self.object_store.upload_file(manifest_path, manifest_object_key, content_type="application/json")
        if self.state_store:
            self.state_store.set_artifact(case_id, "segmentation_mask", True, object_key=mask_object_key)
            self.state_store.set_artifact(
                case_id,
                "segmentation_mask_preview",
                preview_available,
                object_key=preview_object_key if preview_available else None,
            )
            self.state_store.set_artifact(
                case_id,
                "segmentation_manifest",
                bool(manifest),
                object_key=manifest_object_key if manifest else None,
            )
        self.sync_for_write(scope="artifact")
    
    def load_mask(self, case_id: str) -> Optional[np.ndarray]:
        """Load segmentation mask."""
        path = self._resolve_artifact_path(case_id, "segmentation_mask", self._case_dir(case_id) / "mask_volume.npy")
        if not path.exists():
            return None
        return np.load(path)
    
    def load_mask_mmap(self, case_id: str) -> Optional[np.ndarray]:
        """Load segmentation mask with memory mapping for efficient slice access."""
        path = self._resolve_artifact_path(case_id, "segmentation_mask", self._case_dir(case_id) / "mask_volume.npy")
        if not path.exists():
            return None
        return np.load(path, mmap_mode='r')

    def load_mask_preview(self, case_id: str) -> Optional[np.ndarray]:
        """Load downsampled segmentation mask preview when available."""
        path = self._resolve_artifact_path(case_id, "segmentation_mask_preview", self._case_dir(case_id) / "mask_preview_volume.npy")
        if not path.exists():
            return None
        return np.load(path)

    def load_mask_manifest(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Load segmentation manifest metadata when available."""
        path = self._case_dir(case_id) / "mask_manifest.json"
        if path.exists():
            return self._load_json(path)

        object_key = self.get_artifact_object_key(case_id, "segmentation_manifest")
        if self.object_store and object_key:
            try:
                payload = self.object_store.download_bytes(object_key)
                return json.loads(payload.decode("utf-8"))
            except Exception:
                pass
        return None
    
    def mask_exists(self, case_id: str) -> bool:
        """Check if segmentation mask exists for a case."""
        if settings.has_redis_state() and self.state_store:
            artifacts = self.state_store.get_artifacts(case_id) or {}
            if "segmentation_mask" in artifacts:
                return bool(artifacts["segmentation_mask"])
        object_key = self.get_artifact_object_key(case_id, "segmentation_mask")
        if self.object_store and object_key and self.object_store.object_exists(object_key):
            return True
        return (self._case_dir(case_id) / "mask_volume.npy").exists()
        # SDF Storage    
    def save_sdf(self, case_id: str, sdf: np.ndarray):
        """Save SDF volume as float32 for space efficiency."""
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        sdf_path = case_path / "sdf_volume.npy"
        np.save(sdf_path, sdf.astype(np.float32))
        sdf_object_key = self._sdf_volume_object_key(case_id)
        if self.object_store and sdf_path.exists():
            self.object_store.upload_file(sdf_path, sdf_object_key, content_type="application/octet-stream")
        if self.state_store:
            self.state_store.set_artifact(case_id, "sdf", True, object_key=sdf_object_key)
        self.sync_for_write(scope="artifact")
    
    def load_sdf(self, case_id: str) -> Optional[np.ndarray]:
        """Load SDF volume."""
        path = self._resolve_artifact_path(case_id, "sdf", self._case_dir(case_id) / "sdf_volume.npy")
        if not path.exists():
            return None
        return np.load(path)
    
    def sdf_exists(self, case_id: str) -> bool:
        """Check if SDF exists for a case."""
        if settings.has_redis_state() and self.state_store:
            artifacts = self.state_store.get_artifacts(case_id) or {}
            if "sdf" in artifacts:
                return bool(artifacts["sdf"])
        object_key = self.get_artifact_object_key(case_id, "sdf")
        if self.object_store and object_key and self.object_store.object_exists(object_key):
            return True
        return (self._case_dir(case_id) / "sdf_volume.npy").exists()
    
    # Mesh Storage
    
    def save_mesh(self, case_id: str, mesh: trimesh.Trimesh | trimesh.Scene):
        """
        Save a mesh or multi-part mesh scene in Draco-compressed GLB format.
        
        This provides 80-90% file size reduction compared to OBJ
        and includes pre-computed normals for frontend performance.
        """
        from processing.glb_converter import GLBConverter
        
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        glb_path = case_path / "mesh.glb"
        
        # Convert mesh to Draco-compressed GLB
        success, message = GLBConverter.convert_mesh_to_glb(mesh, glb_path, apply_draco=True)
        
        if success:
            print(f"[Repository] Mesh saved as GLB: {message}")
            object_key = self._mesh_object_key(case_id)
            if self.object_store and glb_path.exists():
                self.object_store.upload_file(glb_path, object_key, content_type="model/gltf-binary")
            if self.state_store:
                self.state_store.set_artifact(case_id, "mesh", True, object_key=object_key)
            self.sync_for_write(scope="artifact")
        else:
            print(f"[Repository] GLB conversion warning: {message}")
    
    def load_mesh(self, case_id: str) -> Optional[trimesh.Trimesh | trimesh.Scene]:
        """Load mesh or multi-part mesh scene from file."""
        # Try GLB first (new format)
        glb_path = self._case_dir(case_id) / "mesh.glb"
        if glb_path.exists():
            return trimesh.load(glb_path)
        
        # Fallback to OBJ (legacy format)
        obj_path = self._case_dir(case_id) / "mesh.obj"
        if obj_path.exists():
            return trimesh.load(obj_path)
        
        return None
    
    def get_mesh_path(self, case_id: str, prefer_remote: bool = False) -> Optional[Path]:
        """
        Get path to mesh file if it exists.
        
        Returns GLB path if available, otherwise OBJ for legacy support.
        """
        glb_path = self._case_dir(case_id) / "mesh.glb"
        if prefer_remote:
            remote_glb_path = self._resolve_artifact_path(case_id, "mesh", glb_path, prefer_remote=True)
            if remote_glb_path.exists():
                return remote_glb_path

        if glb_path.exists():
            return glb_path
        
        # Fallback to OBJ for legacy cases
        obj_path = self._case_dir(case_id) / "mesh.obj"
        return obj_path if obj_path.exists() else None
    
    def mesh_exists(self, case_id: str) -> bool:
        """Check if mesh exists for a case (GLB or legacy OBJ)."""
        if settings.has_redis_state() and self.state_store:
            artifacts = self.state_store.get_artifacts(case_id) or {}
            if "mesh" in artifacts:
                return bool(artifacts["mesh"])
        object_key = self.get_artifact_object_key(case_id, "mesh")
        if self.object_store and object_key and self.object_store.object_exists(object_key):
            return True
        case_path = self._case_dir(case_id)
        return (case_path / "mesh.glb").exists() or (case_path / "mesh.obj").exists()
        # Artifact Information    
    def get_available_artifacts(self, case_id: str) -> Dict[str, bool]:
        """Get a dictionary of available artifacts for a case."""
        if settings.has_redis_state() and self.state_store:
            manifest = self.state_store.get_artifacts(case_id)
            if manifest:
                return {
                    "ct_volume": bool(manifest.get("ct_volume", False)),
                    "ct_volume_preview": bool(manifest.get("ct_volume_preview", False)),
                    "ct_metadata": bool(manifest.get("ct_metadata", False)),
                    "segmentation_mask": bool(manifest.get("segmentation_mask", False)),
                    "segmentation_mask_preview": bool(manifest.get("segmentation_mask_preview", False)),
                    "segmentation_manifest": bool(manifest.get("segmentation_manifest", False)),
                    "sdf": bool(manifest.get("sdf", False)),
                    "mesh": bool(manifest.get("mesh", False)),
                    "extra_metadata": bool(manifest.get("extra_metadata", False)),
                }

        if self.object_store:
            remote_artifacts = {
                "ct_volume": self.object_store.object_exists(self._ct_volume_object_key(case_id)),
                "ct_volume_preview": self.object_store.object_exists(self._ct_preview_volume_object_key(case_id)),
                "ct_metadata": self.object_store.object_exists(self._ct_metadata_object_key(case_id)),
                "segmentation_mask": self.object_store.object_exists(self._mask_volume_object_key(case_id)),
                "segmentation_mask_preview": self.object_store.object_exists(self._mask_preview_volume_object_key(case_id)),
                "segmentation_manifest": self.object_store.object_exists(self._segmentation_manifest_object_key(case_id)),
                "sdf": self.object_store.object_exists(self._sdf_volume_object_key(case_id)),
                "mesh": self.object_store.object_exists(self._mesh_object_key(case_id)),
                "extra_metadata": self.object_store.object_exists(self._extra_metadata_object_key(case_id)),
            }
            if any(remote_artifacts.values()):
                return remote_artifacts

        case_path = self._case_dir(case_id)
        artifacts = {
            "ct_volume": (case_path / "ct_volume.npy").exists(),
            "ct_volume_preview": (case_path / "ct_preview_volume.npy").exists(),
            "ct_metadata": (case_path / "ct_metadata.json").exists(),
            "segmentation_mask": (case_path / "mask_volume.npy").exists(),
            "segmentation_mask_preview": (case_path / "mask_preview_volume.npy").exists(),
            "segmentation_manifest": (case_path / "mask_manifest.json").exists(),
            "sdf": (case_path / "sdf_volume.npy").exists(),
            "mesh": (case_path / "mesh.glb").exists() or (case_path / "mesh.obj").exists(),
            "extra_metadata": (case_path / "extra_metadata.json").exists(),
        }
        if settings.has_redis_state() and self.state_store:
            self.state_store.initialize_artifacts(case_id, artifacts)
        return artifacts

    def is_artifact_available(self, case_id: str, artifact_name: str) -> bool:
        """Check one artifact without materializing the full artifact manifest."""
        if settings.has_redis_state() and self.state_store:
            manifest = self.state_store.get_artifacts(case_id) or {}
            if artifact_name in manifest:
                return bool(manifest.get(artifact_name))

        preferred_local_path = self._preferred_local_artifact_path(case_id, artifact_name)
        if preferred_local_path is not None and preferred_local_path.exists():
            return True

        object_key = self.get_artifact_object_key(case_id, artifact_name)
        if self.object_store and object_key:
            return self.object_store.object_exists(object_key)

        return False

    def get_artifact_object_key(self, case_id: str, artifact_name: str) -> Optional[str]:
        """Return the object key recorded in the artifact manifest."""
        if self.state_store:
            manifest = self.state_store.get_artifacts(case_id) or {}
            manifest_key = manifest.get(f"{artifact_name}_key")
            if manifest_key:
                return manifest_key
        return self._default_object_key(case_id, artifact_name)

    def update_pipeline_stage(
        self,
        case_id: str,
        stage_name: str,
        status: str,
        duration_seconds: float = None,
        message: str = None,
        output_shape: tuple = None,
    ) -> Dict[str, Any]:
        """Persist pipeline stage state when a state store is configured."""
        if not settings.has_redis_state() or not self.state_store:
            return {}
        return self.state_store.update_pipeline_stage(
            case_id,
            stage_name,
            status,
            duration_seconds=duration_seconds,
            message=message,
            output_shape=output_shape,
        )

    def get_pipeline_state(self, case_id: str) -> Dict[str, Any]:
        """Read pipeline stage state from the configured state store."""
        if not settings.has_redis_state() or not self.state_store:
            return {}
        return self.state_store.get_pipeline_state(case_id)

    def acquire_processing_lock(self, case_id: str) -> bool:
        """Acquire a processing lock for the case."""
        if not settings.has_redis_state() or not self.state_store:
            return True
        return self.state_store.acquire_processing_lock(case_id, settings.PROCESSING_LOCK_TTL_SECONDS)

    def release_processing_lock(self, case_id: str) -> None:
        """Release a processing lock for the case."""
        if settings.has_redis_state() and self.state_store:
            self.state_store.release_processing_lock(case_id)
        # Helper Methods    
    def _empty_artifact_manifest(self) -> Dict[str, bool]:
        return {
            "ct_volume": False,
            "ct_volume_preview": False,
            "ct_metadata": False,
            "segmentation_mask": False,
            "segmentation_mask_preview": False,
            "segmentation_manifest": False,
            "sdf": False,
            "mesh": False,
            "extra_metadata": False,
        }

    def _case_prefix(self, case_id: str) -> str:
        return f"cases/{case_id}/"

    def _upload_prefix(self, case_id: str) -> str:
        return f"uploads/{case_id}/"

    def _mesh_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}mesh/reconstruction.glb"

    def _ct_volume_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}ct/volume.npy"

    def _ct_preview_volume_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}ct/preview_volume.npy"

    def _ct_metadata_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}ct/metadata.json"

    def _extra_metadata_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}meta/extra_metadata.json"

    def _mask_volume_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}mask/volume.npy"

    def _mask_preview_volume_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}mask/preview_volume.npy"

    def _segmentation_manifest_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}mask/manifest.json"

    def _sdf_volume_object_key(self, case_id: str) -> str:
        return f"{self._case_prefix(case_id)}sdf/volume.npy"

    def _artifact_cache_path(self, case_id: str, artifact_name: str, filename: str) -> Path:
        return settings.TEMP_STORAGE_ROOT / "cache" / case_id / artifact_name / filename

    def _ensure_retention_fields(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if "created_at" not in payload or not payload["created_at"]:
            payload["created_at"] = datetime.utcnow().isoformat()
        if not payload.get("expires_at"):
            created_at = self._parse_iso_datetime(payload["created_at"])
            expires_at = created_at + timedelta(seconds=settings.CASE_RETENTION_SECONDS)
            payload["expires_at"] = expires_at.isoformat()
        return payload

    def _is_payload_expired(self, payload: Dict[str, Any], now: datetime) -> bool:
        expires_at = payload.get("expires_at")
        if not expires_at:
            return False
        try:
            return self._parse_iso_datetime(expires_at) <= now
        except ValueError:
            return False

    def _parse_iso_datetime(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)

    def _resolve_artifact_path(
        self,
        case_id: str,
        artifact_name: str,
        preferred_local_path: Path,
        prefer_remote: bool = False,
    ) -> Path:
        object_key = self.get_artifact_object_key(case_id, artifact_name)

        if prefer_remote and self.object_store and object_key:
            cache_path = self._artifact_cache_path(case_id, artifact_name, preferred_local_path.name)
            if cache_path.exists():
                return cache_path
            try:
                return self.object_store.download_file(object_key, cache_path)
            except Exception:
                pass

        if preferred_local_path.exists():
            return preferred_local_path

        if not self.object_store or not object_key:
            return preferred_local_path

        cache_path = self._artifact_cache_path(case_id, artifact_name, preferred_local_path.name)
        if cache_path.exists():
            return cache_path

        try:
            return self.object_store.download_file(object_key, cache_path)
        except Exception:
            return preferred_local_path

    def _default_object_key(self, case_id: str, artifact_name: str) -> Optional[str]:
        mapping = {
            "ct_volume": self._ct_volume_object_key(case_id),
            "ct_volume_preview": self._ct_preview_volume_object_key(case_id),
            "ct_metadata": self._ct_metadata_object_key(case_id),
            "extra_metadata": self._extra_metadata_object_key(case_id),
            "segmentation_mask": self._mask_volume_object_key(case_id),
            "segmentation_mask_preview": self._mask_preview_volume_object_key(case_id),
            "segmentation_manifest": self._segmentation_manifest_object_key(case_id),
            "sdf": self._sdf_volume_object_key(case_id),
            "mesh": self._mesh_object_key(case_id),
        }
        return mapping.get(artifact_name)

    def _preferred_local_artifact_path(self, case_id: str, artifact_name: str) -> Optional[Path]:
        case_path = self._case_dir(case_id)
        mapping = {
            "ct_volume": case_path / "ct_volume.npy",
            "ct_volume_preview": case_path / "ct_preview_volume.npy",
            "ct_metadata": case_path / "ct_metadata.json",
            "extra_metadata": case_path / "extra_metadata.json",
            "segmentation_mask": case_path / "mask_volume.npy",
            "segmentation_mask_preview": case_path / "mask_preview_volume.npy",
            "segmentation_manifest": case_path / "mask_manifest.json",
            "sdf": case_path / "sdf_volume.npy",
            "mesh": case_path / "mesh.glb",
        }
        return mapping.get(artifact_name)

    def _save_json(self, path: Path, data: Dict[str, Any]):
        """Save data to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    
    def _load_json(self, path: Path) -> Dict[str, Any]:
        """Load data from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
