"""
State store abstractions for operational data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class StateStore(ABC):
    """Abstract interface for operational state persistence."""

    @abstractmethod
    def initialize_case(self, case_id: str) -> None:
        """Create initial state for a case."""

    @abstractmethod
    def delete_case(self, case_id: str) -> None:
        """Delete all state associated with a case."""

    @abstractmethod
    def update_case_status(
        self,
        case_id: str,
        status: str,
        message: Optional[str] = None,
        current_stage: Optional[str] = None,
        progress_percent: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Persist overall case status."""

    @abstractmethod
    def get_case_status(self, case_id: str) -> Optional[str]:
        """Read the current overall status."""

    @abstractmethod
    def get_case_status_info(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Read the full case status payload."""

    @abstractmethod
    def list_case_statuses(self) -> Dict[str, Dict[str, Any]]:
        """List all known case status payloads keyed by case id."""

    @abstractmethod
    def update_pipeline_stage(
        self,
        case_id: str,
        stage_name: str,
        status: str,
        duration_seconds: Optional[float] = None,
        message: Optional[str] = None,
        output_shape: Optional[tuple] = None,
    ) -> Dict[str, Any]:
        """Persist a single pipeline stage update."""

    @abstractmethod
    def get_pipeline_state(self, case_id: str) -> Dict[str, Any]:
        """Read pipeline stage state."""

    @abstractmethod
    def initialize_artifacts(self, case_id: str, artifacts: Dict[str, bool]) -> None:
        """Create an artifact manifest entry."""

    @abstractmethod
    def set_artifact(
        self,
        case_id: str,
        artifact_name: str,
        available: bool,
        object_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update one artifact in the manifest."""

    @abstractmethod
    def get_artifacts(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Read artifact manifest."""

    @abstractmethod
    def create_batch_session(self, case_id: str, payload: Dict[str, Any], ttl_seconds: int) -> Dict[str, Any]:
        """Persist an upload batch session."""

    @abstractmethod
    def get_batch_session(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Read an upload batch session."""

    @abstractmethod
    def update_batch_session(
        self,
        case_id: str,
        updates: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update an upload batch session."""

    @abstractmethod
    def delete_batch_session(self, case_id: str) -> None:
        """Delete an upload batch session."""

    @abstractmethod
    def acquire_processing_lock(self, case_id: str, ttl_seconds: int) -> bool:
        """Acquire a short-lived processing lock for a case."""

    @abstractmethod
    def release_processing_lock(self, case_id: str) -> None:
        """Release the processing lock for a case."""
