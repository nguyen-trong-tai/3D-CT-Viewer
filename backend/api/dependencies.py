"""Shared dependency wiring for FastAPI endpoints."""

from config import settings
from services.artifact_service import ArtifactService
from services.case_service import CaseService
from services.pipeline import PipelineService
from services.upload_service import UploadService
from storage.object_store.base import ObjectStore
from storage.object_store.r2 import R2ObjectStore
from storage.repository import CaseRepository
from storage.state_store.base import StateStore
from storage.state_store.memory import MemoryStateStore
from storage.state_store.redis import RedisStateStore


_state_store: StateStore = None
_object_store: ObjectStore = None
_repository: CaseRepository = None
_pipeline_service: PipelineService = None
_case_service: CaseService = None
_upload_service: UploadService = None
_artifact_service: ArtifactService = None


def _required_backend_error(backend_name: str, reason: str | None = None) -> RuntimeError:
    message = f"{backend_name} is required for DISTRIBUTED_RUNTIME_MODE=required"
    if reason:
        message = f"{message}: {reason}"
    return RuntimeError(message)


def get_state_store() -> StateStore:
    """Get the configured state store, preferring Redis with memory fallback."""
    global _state_store
    if _state_store is not None:
        return _state_store

    if settings.should_use_redis_state():
        try:
            _state_store = RedisStateStore(settings.REDIS_URL, settings.REDIS_KEY_PREFIX)
            _state_store.verify_connection()
            return _state_store
        except Exception as exc:
            if settings.distributed_runtime_required():
                raise _required_backend_error("Redis", str(exc)) from exc
            print(f"[Dependencies] Redis unavailable, falling back to MemoryStateStore: {exc}")
    elif settings.distributed_runtime_required():
        raise _required_backend_error("Redis", "REDIS_URL is missing")

    _state_store = MemoryStateStore()
    return _state_store


def get_object_store() -> ObjectStore | None:
    """Get the configured object store, preferring Cloudflare R2 when configured."""
    global _object_store
    if _object_store is not None:
        return _object_store

    if settings.should_use_r2_object_store():
        try:
            _object_store = R2ObjectStore(
                account_id=settings.R2_ACCOUNT_ID,
                bucket=settings.R2_BUCKET,
                access_key_id=settings.R2_ACCESS_KEY_ID,
                secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                public_base_url=settings.R2_PUBLIC_BASE_URL,
            )
            _object_store.verify_connection()
            return _object_store
        except Exception as exc:
            if settings.distributed_runtime_required():
                raise _required_backend_error("R2 object store", str(exc)) from exc
            print(f"[Dependencies] R2 unavailable, falling back to local-only artifacts: {exc}")
    elif settings.distributed_runtime_required():
        raise _required_backend_error(
            "R2 object store",
            "R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET are missing",
        )

    _object_store = None
    return _object_store


def get_repository() -> CaseRepository:
    """Get the shared repository instance."""
    global _repository
    if _repository is None:
        _repository = CaseRepository(
            settings.STORAGE_ROOT,
            state_store=get_state_store(),
            object_store=get_object_store(),
        )
    return _repository


def ensure_runtime_dependencies() -> CaseRepository:
    """Resolve runtime dependencies eagerly so startup fails before serving traffic."""
    settings.validate_runtime_configuration()
    get_state_store()
    get_object_store()
    return get_repository()


def get_pipeline_service() -> PipelineService:
    """Get the singleton pipeline service instance."""
    global _pipeline_service
    if _pipeline_service is None:
        _pipeline_service = PipelineService(get_repository())
    return _pipeline_service


def get_case_service() -> CaseService:
    """Get the singleton case service instance."""
    global _case_service
    if _case_service is None:
        _case_service = CaseService(get_repository())
    return _case_service


def get_upload_service() -> UploadService:
    """Get the singleton upload service instance."""
    global _upload_service
    if _upload_service is None:
        _upload_service = UploadService(get_repository(), get_state_store())
    return _upload_service


def get_artifact_service() -> ArtifactService:
    """Get the singleton artifact service instance."""
    global _artifact_service
    if _artifact_service is None:
        _artifact_service = ArtifactService(get_repository(), get_object_store())
    return _artifact_service


def reset_dependencies():
    """Reset all dependencies (for testing)."""
    global _state_store, _object_store, _repository, _pipeline_service, _case_service, _upload_service, _artifact_service
    _state_store = None
    _object_store = None
    _repository = None
    _pipeline_service = None
    _case_service = None
    _upload_service = None
    _artifact_service = None
