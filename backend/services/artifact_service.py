"""
Artifact delivery service.
"""

from __future__ import annotations

from typing import Any, Dict

from storage.object_store.base import ObjectStore
from storage.repository import CaseRepository


class ArtifactService:
    """Resolve artifact metadata and download targets."""

    def __init__(self, repo: CaseRepository, object_store: ObjectStore | None = None):
        self.repo = repo
        self.object_store = object_store

    def get_mesh_delivery(self, case_id: str, expires_in_seconds: int = 3600) -> Dict[str, Any]:
        self.repo.sync_for_read(scope="artifact")

        if not self.repo.is_artifact_available(case_id, "mesh"):
            raise FileNotFoundError(case_id)

        mesh_path = self.repo.get_mesh_path(case_id, prefer_remote=True)
        if mesh_path is not None:
            return {"type": "file", "path": mesh_path}

        raise FileNotFoundError(case_id)

    def get_ct_metadata(self, case_id: str) -> Dict[str, Any]:
        self.repo.sync_for_read(scope="artifact")
        metadata = self.repo.load_ct_metadata(case_id)
        if not metadata:
            raise FileNotFoundError(case_id)
        return metadata

    def get_extra_metadata(self, case_id: str) -> Dict[str, Any]:
        self.repo.sync_for_read(scope="artifact")
        metadata = self.repo.load_extra_metadata(case_id)
        if not metadata:
            raise FileNotFoundError(case_id)
        return metadata

    def get_artifact_download_url(
        self,
        case_id: str,
        artifact_name: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        self.repo.sync_for_read(scope="artifact")

        if not self.repo.is_artifact_available(case_id, artifact_name):
            raise FileNotFoundError(case_id)

        object_key = self.repo.get_artifact_object_key(case_id, artifact_name)
        if not self.object_store or not object_key:
            raise FileNotFoundError(case_id)

        return self.object_store.generate_download_url(object_key, expires_in_seconds=expires_in_seconds)

    def get_npy_artifact_delivery(self, case_id: str, artifact_name: str) -> Dict[str, Any]:
        """Resolve a local or cached NPY artifact for chunked raw-byte streaming."""
        self.repo.sync_for_read(scope="artifact")

        if not self.repo.is_artifact_available(case_id, artifact_name):
            raise FileNotFoundError(case_id)

        payload = self.repo.get_npy_artifact_stream_info(case_id, artifact_name)
        if not payload:
            raise FileNotFoundError(case_id)
        return payload
