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
        status = self.repo.get_status(case_id)
        status_info = self.repo.get_status_info(case_id) or {}
        return {
            "case_id": case_id,
            "status": status,
            "message": status_info.get("message"),
            "expires_at": status_info.get("expires_at"),
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
