"""
CT-based Medical Imaging & AI Research Platform - Backend

FastAPI application entry point.

DISCLAIMER: This software is intended for research and educational purposes.
It is not certified for clinical diagnosis or treatment.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.router import router
from config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    print(f"[Backend] Starting {settings.APP_NAME}")
    print(f"[Backend] Storage root: {settings.STORAGE_ROOT}")
    print(f"[Backend] Max workers: {settings.MAX_WORKERS}")
    yield
    # Shutdown
    print("[Backend] Shutting down...")


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
    expose_headers=["X-Volume-Shape", "X-Volume-Spacing"],  # Custom headers for binary responses
)

# Include API router
app.include_router(router)


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with system information."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "api_docs": "/docs",
        "disclaimer": "This software is intended for research and educational purposes. "
                     "It is not certified for clinical diagnosis or treatment."
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
