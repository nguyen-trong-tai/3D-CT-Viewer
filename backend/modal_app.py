"""
Modal Deployment Entry Point

Deploy the CT Imaging Platform backend on Modal for GPU-accelerated processing.
"""

import modal

# Create Modal app
app = modal.App("ct-imaging-platform")

# Define the container image with all dependencies
image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "fastapi",
    "uvicorn",
    "python-multipart",
    "numpy",
    "pydicom",
    "nibabel",
    "scikit-image",
    "scipy",
    "trimesh",
    "pydantic>=2.0",
)


@app.function(
    image=image,
    gpu="any",  # Request GPU for processing
    volumes={"/data": modal.Volume.from_name("ct-data", create_if_missing=True)},
    timeout=600,  # 10 minute timeout for processing
)
@modal.asgi_app()
def fastapi_app():
    """Deploy the FastAPI app on Modal."""
    # Import here to avoid issues with Modal's serialization
    import os
    os.environ["STORAGE_ROOT"] = "/data"
    
    from main import app
    return app


@app.function(
    image=image,
    gpu="any",
    volumes={"/data": modal.Volume.from_name("ct-data", create_if_missing=True)},
    timeout=1800,  # 30 min for heavy processing
)
def process_case_gpu(case_id: str):
    """
    Process a case with GPU acceleration (if available).
    
    This function can be called remotely to offload heavy processing.
    """
    import os
    os.environ["STORAGE_ROOT"] = "/data"
    
    from api.dependencies import get_pipeline_service
    
    pipeline = get_pipeline_service()
    result = pipeline.process_case(case_id)
    
    return {
        "case_id": result.case_id,
        "success": result.success,
        "total_duration_seconds": result.total_duration_seconds,
        "error_message": result.error_message,
    }


# For local testing
if __name__ == "__main__":
    # Deploy the app
    modal.deploy(app)
