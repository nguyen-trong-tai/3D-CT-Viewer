"""
Case-oriented service layer.
"""

from __future__ import annotations

from typing import Any, Dict

from models.enums import CaseStatus
from storage.repository import CaseRepository


class CaseService:
    """Thin service for case lifecycle and read-side status APIs."""

    def __init__(self, repo: CaseRepository):
        self.repo = repo

    def get_status(self, case_id: str) -> Dict[str, Any]:
        self.repo.sync_for_read(scope="state")
        status_info = self.repo.get_status_info(case_id) or {}
        status = status_info.get("status")
        if status is None:
            status = self.repo.get_status(case_id)
        return {
            "case_id": case_id,
            "status": status,
            "message": status_info.get("message"),
            "expires_at": status_info.get("expires_at"),
            "current_stage": status_info.get("current_stage"),
            "progress_percent": status_info.get("progress_percent"),
        }

    def get_event_snapshot(self, case_id: str) -> Dict[str, Any]:
        """Build a read model tailored for SSE and UI synchronization."""
        self.repo.sync_for_read(scope="all")
        if not self.repo.case_exists(case_id):
            raise FileNotFoundError(case_id)

        status_info = self.repo.get_status_info(case_id) or {}
        status = status_info.get("status") or self.repo.get_status(case_id)
        artifacts = self.repo.get_available_artifacts(case_id)
        pipeline_state = self.repo.get_pipeline_state(case_id)

        if pipeline_state:
            stages = {
                stage_name: {
                    "status": payload.get("status", "pending"),
                    "duration_seconds": payload.get("duration_seconds"),
                    "message": payload.get("message"),
                    "output_shape": payload.get("output_shape"),
                }
                for stage_name, payload in pipeline_state.items()
                if stage_name in {"load_volume", "segmentation", "sdf", "mesh"} and isinstance(payload, dict)
            }
        else:
            stages = self._infer_stage_state_from_artifacts(status, artifacts)

        return {
            "case_id": case_id,
            "status": {
                "status": status,
                "message": status_info.get("message"),
                "expires_at": status_info.get("expires_at"),
                "current_stage": status_info.get("current_stage"),
                "progress_percent": status_info.get("progress_percent"),
            },
            "artifacts": artifacts,
            "stages": stages,
        }

    def list_artifacts(self, case_id: str) -> Dict[str, Any]:
        self.repo.sync_for_read(scope="artifact")
        if not self.repo.case_exists(case_id):
            raise FileNotFoundError(case_id)
        return {
            "case_id": case_id,
            "artifacts": self.repo.get_available_artifacts(case_id),
        }

    def delete_case(self, case_id: str) -> bool:
        if not self.repo.case_exists(case_id):
            return False
        return self.repo.delete_case(case_id)

    def can_start_processing(self, case_id: str) -> str:
        status = self.repo.get_status(case_id)
        if status == CaseStatus.ERROR.value and not self.repo.case_exists(case_id):
            return "missing"
        if status == CaseStatus.PROCESSING.value:
            return "processing"
        return "ok"

    @staticmethod
    def _infer_stage_state_from_artifacts(status: str, artifacts: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        load_volume_ready = bool(artifacts.get("ct_volume") or artifacts.get("ct_volume_preview"))
        stage_state: Dict[str, Dict[str, Any]] = {
            "load_volume": {"status": "completed" if load_volume_ready else "pending"},
            "segmentation": {"status": "pending"},
            "sdf": {"status": "pending"},
            "mesh": {"status": "pending"},
        }

        if artifacts.get("segmentation_mask"):
            stage_state["segmentation"]["status"] = "completed"
        elif status == CaseStatus.PROCESSING.value:
            stage_state["segmentation"]["status"] = "running"

        if artifacts.get("sdf"):
            stage_state["sdf"]["status"] = "completed"
        elif status == CaseStatus.PROCESSING.value and stage_state["segmentation"]["status"] == "completed":
            stage_state["sdf"]["status"] = "running"

        if artifacts.get("mesh"):
            stage_state["mesh"]["status"] = "completed"
        elif status == CaseStatus.PROCESSING.value and stage_state["sdf"]["status"] == "completed":
            stage_state["mesh"]["status"] = "running"

        if status == CaseStatus.ERROR.value:
            for payload in stage_state.values():
                if payload["status"] == "running":
                    payload["status"] = "failed"

        if status == CaseStatus.READY.value:
            for payload in stage_state.values():
                payload["status"] = "completed"

        return stage_state
