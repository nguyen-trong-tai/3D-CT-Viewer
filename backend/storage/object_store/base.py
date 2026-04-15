"""
Object store abstractions for persistent binary artifacts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class ObjectStore(ABC):
    """Abstract interface for binary/object artifact storage."""

    def verify_connection(self) -> None:
        """Best-effort connectivity check for startup validation."""

    @abstractmethod
    def upload_file(self, local_path: Path, object_key: str, content_type: Optional[str] = None) -> str:
        """Upload a local file to the object store."""

    def upload_bytes(self, data: bytes, object_key: str, content_type: Optional[str] = None) -> str:
        """Upload raw bytes to the object store."""
        raise NotImplementedError("This object store does not support direct byte uploads")

    @abstractmethod
    def generate_download_url(self, object_key: str, expires_in_seconds: int = 3600) -> str:
        """Generate a temporary download URL for an object."""

    @abstractmethod
    def generate_upload_url(self, object_key: str, expires_in_seconds: int = 3600) -> str:
        """Generate a temporary upload URL for an object."""

    @abstractmethod
    def download_bytes(self, object_key: str) -> bytes:
        """Download object contents as bytes."""

    def download_byte_range(self, object_key: str, start: int = 0, end: int | None = None) -> bytes:
        """Download a byte range from an object."""
        raise NotImplementedError("This object store does not support ranged reads")

    @abstractmethod
    def download_file(self, object_key: str, local_path: Path) -> Path:
        """Download an object to a local path."""

    @abstractmethod
    def object_exists(self, object_key: str) -> bool:
        """Check whether an object exists."""

    @abstractmethod
    def delete_object(self, object_key: str) -> None:
        """Delete a single object."""

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        """Delete all objects under a prefix."""
