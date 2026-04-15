"""
API Router — Aggregator

Combines all sub-routers into a single router mounted at /api/v1.
Previously this was a 700-line monolith; now each domain has its own file:
  - cases.py:      Upload, batch upload, status, delete
  - ct_data.py:    Volume (binary), slices (JSON), metadata
  - processing.py: Pipeline trigger, mask data, SDF info
  - mesh.py:       3D mesh retrieval
"""

from fastapi import APIRouter
from config import settings

from api.routers.cases import router as cases_router
from api.routers.ct_data import router as ct_data_router
from api.routers.processing import router as processing_router
from api.routers.mesh import router as mesh_router


router = APIRouter(prefix="/api/v1")

# Include all domain routers
router.include_router(cases_router)
router.include_router(ct_data_router)
router.include_router(processing_router)
router.include_router(mesh_router)


@router.get("/health", summary="Health check", tags=["Health"])
async def health_check():
    """Check if the API is running."""
    payload = {
        "status": "healthy",
        "version": settings.APP_VERSION,
    }
    if settings.HEALTH_DETAILS_ENABLED:
        payload.update(
            {
                "runtime_mode": settings.runtime_mode_label(),
                "distributed_runtime_mode": settings.DISTRIBUTED_RUNTIME_MODE,
                "redis_enabled": settings.should_use_redis_state(),
                "r2_enabled": settings.should_use_r2_object_store(),
            }
        )
    return payload
