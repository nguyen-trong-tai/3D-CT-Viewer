"""
In-memory fallback state store.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from config import settings
from models.enums import CaseStatus

from .base import StateStore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStateStore(StateStore):
    """Simple in-process state store."""

    def __init__(self):
        self._status: Dict[str, Dict[str, Any]] = {}
        self._pipeline: Dict[str, Dict[str, Any]] = {}
        self._artifacts: Dict[str, Dict[str, Any]] = {}
        self._batch_sessions: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, bool] = {}

    def initialize_case(self, case_id: str) -> None:
        now = _utc_now_iso()
        expires_at = datetime.now(timezone.utc).timestamp() + settings.CASE_RETENTION_SECONDS
        self._status[case_id] = {
            "status": CaseStatus.PENDING.value,
            "created_at": now,
            "updated_at": now,
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
            "message": None,
            "current_stage": None,
            "progress_percent": 0.0,
        }
        self._pipeline[case_id] = {
            "load_volume": {"status": "pending"},
            "segmentation": {"status": "pending"},
            "sdf": {"status": "pending"},
            "mesh": {"status": "pending"},
            "started_at": None,
            "finished_at": None,
            "error": None,
        }

    def delete_case(self, case_id: str) -> None:
        self._status.pop(case_id, None)
        self._pipeline.pop(case_id, None)
        self._artifacts.pop(case_id, None)
        self._batch_sessions.pop(case_id, None)
        self._locks.pop(case_id, None)

    def update_case_status(
        self,
        case_id: str,
        status: str,
        message: Optional[str] = None,
        current_stage: Optional[str] = None,
        progress_percent: Optional[float] = None,
    ) -> Dict[str, Any]:
        payload = deepcopy(self._status.get(case_id, {}))
        if "created_at" not in payload:
            payload["created_at"] = _utc_now_iso()
        if "expires_at" not in payload:
            expires_at = datetime.now(timezone.utc).timestamp() + settings.CASE_RETENTION_SECONDS
            payload["expires_at"] = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()
        payload["status"] = status
        payload["updated_at"] = _utc_now_iso()
        if message is not None:
            payload["message"] = message
        if current_stage is not None:
            payload["current_stage"] = current_stage
        if progress_percent is not None:
            payload["progress_percent"] = progress_percent
        self._status[case_id] = payload
        return deepcopy(payload)

    def get_case_status(self, case_id: str) -> Optional[str]:
        payload = self._status.get(case_id)
        return payload.get("status") if payload else None

    def get_case_status_info(self, case_id: str) -> Optional[Dict[str, Any]]:
        payload = self._status.get(case_id)
        return deepcopy(payload) if payload else None

    def list_case_statuses(self) -> Dict[str, Dict[str, Any]]:
        return deepcopy(self._status)

    def update_pipeline_stage(
        self,
        case_id: str,
        stage_name: str,
        status: str,
        duration_seconds: Optional[float] = None,
        message: Optional[str] = None,
        output_shape: Optional[tuple] = None,
    ) -> Dict[str, Any]:
        pipeline = deepcopy(self._pipeline.get(case_id, {}))
        if not pipeline:
            self.initialize_case(case_id)
            pipeline = deepcopy(self._pipeline.get(case_id, {}))

        if pipeline.get("started_at") is None and status == "running":
            pipeline["started_at"] = _utc_now_iso()
        if status in {"failed", "completed"}:
            pipeline["finished_at"] = _utc_now_iso()
        if status == "failed":
            pipeline["error"] = message

        stage_payload = {"status": status}
        if duration_seconds is not None:
            stage_payload["duration_seconds"] = duration_seconds
        if message:
            stage_payload["message"] = message
        if output_shape is not None:
            stage_payload["output_shape"] = list(output_shape)

        pipeline[stage_name] = stage_payload
        self._pipeline[case_id] = pipeline
        return deepcopy(pipeline)

    def get_pipeline_state(self, case_id: str) -> Dict[str, Any]:
        payload = self._pipeline.get(case_id, {})
        return deepcopy(payload)

    def initialize_artifacts(self, case_id: str, artifacts: Dict[str, bool]) -> None:
        payload = {}
        for name, available in artifacts.items():
            payload[name] = bool(available)
        self._artifacts[case_id] = payload

    def set_artifact(
        self,
        case_id: str,
        artifact_name: str,
        available: bool,
        object_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = deepcopy(self._artifacts.get(case_id, {}))
        payload[artifact_name] = bool(available)
        if object_key:
            payload[f"{artifact_name}_key"] = object_key
        self._artifacts[case_id] = payload
        return deepcopy(payload)

    def get_artifacts(self, case_id: str) -> Optional[Dict[str, Any]]:
        payload = self._artifacts.get(case_id)
        return deepcopy(payload) if payload else None

    def create_batch_session(self, case_id: str, payload: Dict[str, Any], ttl_seconds: int) -> Dict[str, Any]:
        session = deepcopy(payload)
        session["ttl_seconds"] = ttl_seconds
        self._batch_sessions[case_id] = session
        return deepcopy(session)

    def get_batch_session(self, case_id: str) -> Optional[Dict[str, Any]]:
        payload = self._batch_sessions.get(case_id)
        return deepcopy(payload) if payload else None

    def update_batch_session(
        self,
        case_id: str,
        updates: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        session = deepcopy(self._batch_sessions.get(case_id))
        if session is None:
            return None
        session.update(updates)
        if ttl_seconds is not None:
            session["ttl_seconds"] = ttl_seconds
        self._batch_sessions[case_id] = session
        return deepcopy(session)

    def delete_batch_session(self, case_id: str) -> None:
        self._batch_sessions.pop(case_id, None)

    def acquire_processing_lock(self, case_id: str, ttl_seconds: int) -> bool:
        if self._locks.get(case_id):
            return False
        self._locks[case_id] = True
        return True

    def release_processing_lock(self, case_id: str) -> None:
        self._locks.pop(case_id, None)
