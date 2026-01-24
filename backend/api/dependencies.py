"""
API Dependencies

Shared dependencies for FastAPI endpoints.
"""

from functools import lru_cache
from typing import Generator

from storage.repository import CaseRepository
from services.pipeline import PipelineService
from config import settings


# Singleton instances
_repository: CaseRepository = None
_pipeline_service: PipelineService = None


def get_repository() -> CaseRepository:
    """
    Get the singleton repository instance.
    
    This is a dependency injection pattern for FastAPI.
    """
    global _repository
    if _repository is None:
        _repository = CaseRepository(settings.STORAGE_ROOT)
    return _repository


def get_pipeline_service() -> PipelineService:
    """
    Get the singleton pipeline service instance.
    """
    global _pipeline_service
    if _pipeline_service is None:
        _pipeline_service = PipelineService(get_repository())
    return _pipeline_service


def reset_dependencies():
    """
    Reset all dependencies (for testing).
    """
    global _repository, _pipeline_service
    _repository = None
    _pipeline_service = None
