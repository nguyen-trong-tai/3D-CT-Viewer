"""
CT-based Medical Imaging & AI Research Platform - Backend

FastAPI application entry point.

DISCLAIMER: This software is intended for research and educational purposes.
It is not certified for clinical diagnosis or treatment.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.dependencies import ensure_runtime_dependencies, reset_dependencies
from api.router import router
from config import settings
from services.retention_service import RetentionCleanupService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    settings.refresh_from_env()
    reset_dependencies()
    repository = ensure_runtime_dependencies()
    retention_service = RetentionCleanupService(repository)
    retention_service.start()
    app.state.retention_service = retention_service
    print(f"[Backend] Starting {settings.APP_NAME}")
    print(f"[Backend] Storage root: {settings.STORAGE_ROOT}")
    print(
        f"[Backend] Runtime mode: {settings.runtime_mode_label()} "
        f"(distributed_mode={settings.DISTRIBUTED_RUNTIME_MODE})"
    )
    print(f"[Backend] Max workers: {settings.MAX_WORKERS}")
    print(f"[Backend] Case retention: {settings.CASE_RETENTION_SECONDS}s")
    yield
    # Shutdown
    retention_service.stop()
    print("[Backend] Shutting down...")


def create_app() -> FastAPI:
    """Create the FastAPI application with environment-aware middleware."""
    settings.refresh_from_env()

    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=settings.APP_DESCRIPTION,
        lifespan=lifespan,
        docs_url=settings.docs_url(),
        redoc_url=settings.redoc_url(),
        openapi_url=settings.openapi_url(),
    )

    if settings.CORS_ORIGINS:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
            allow_methods=settings.CORS_ALLOW_METHODS,
            allow_headers=settings.CORS_ALLOW_HEADERS,
            expose_headers=["X-Volume-Shape", "X-Volume-Spacing"],
        )

    if settings.TRUSTED_HOSTS:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.TRUSTED_HOSTS,
        )

    application.include_router(router)
    return application


app = create_app()


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    if settings.SECURITY_HEADERS_ENABLED:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with system information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "api_docs": settings.docs_url(),
        "disclaimer": "This software is intended for research and educational purposes. "
                     "It is not certified for clinical diagnosis or treatment."
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Simple health check endpoint."""
    payload = {
        "status": "healthy",
    }
    if settings.HEALTH_DETAILS_ENABLED:
        payload.update(
            {
                "version": settings.APP_VERSION,
                "runtime_mode": settings.runtime_mode_label(),
                "distributed_runtime_mode": settings.DISTRIBUTED_RUNTIME_MODE,
                "redis_enabled": settings.should_use_redis_state(),
                "r2_enabled": settings.should_use_r2_object_store(),
            }
        )
    return payload


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1" if not settings.is_production_environment() else "0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
