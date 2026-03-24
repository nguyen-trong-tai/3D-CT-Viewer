"""
Modal Deployment - CT Imaging Platform
Optimized for baseline CT processing workers.
"""

import os

import modal

from config import settings


app = modal.App("ct-imaging-platform")
USE_SHARED_VOLUME = not settings.should_use_distributed_runtime()


# Volumes
data_volume = modal.Volume.from_name("ct-data", create_if_missing=True)

DATA_PATH = "/data"
SHARED_TEMP_PATH = f"{DATA_PATH}/temp"
WORKER_TEMP_PATH = "/tmp/viewr_ct"
WORKER_STORAGE_ROOT = f"{WORKER_TEMP_PATH}/cases"

WEB_VOLUMES = {}
if USE_SHARED_VOLUME:
    WEB_VOLUMES[DATA_PATH] = data_volume

PROCESS_VOLUMES = {}
if USE_SHARED_VOLUME:
    PROCESS_VOLUMES[DATA_PATH] = data_volume

UPLOAD_VOLUMES = {}
if USE_SHARED_VOLUME:
    UPLOAD_VOLUMES[DATA_PATH] = data_volume


# Image
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
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
        "redis>=5.0.0",
        "boto3>=1.34.0",
    )
    .add_local_dir(
        local_path=".",
        remote_path="/root",
        ignore=lambda p: any(
            x in str(p) for x in ["venv", ".venv", "__pycache__", ".git", ".idea", ".vscode"]
        ),
    )
)


# FastAPI app (ASGI)
@app.cls(
    image=image,
    volumes=WEB_VOLUMES,
    timeout=600,
    startup_timeout=300,
    scaledown_window=600,
    min_containers=1,
    max_containers=3,
    enable_memory_snapshot=True,
)
class FastAPIService:
    @modal.enter(snap=True)
    def load(self):
        storage_root = DATA_PATH if USE_SHARED_VOLUME else WORKER_STORAGE_ROOT
        temp_root = SHARED_TEMP_PATH if USE_SHARED_VOLUME else WORKER_TEMP_PATH
        os.environ["STORAGE_ROOT"] = storage_root
        os.environ["TEMP_STORAGE_ROOT"] = temp_root
        settings.refresh_from_env()
        print("[Container] Web runtime ready.")

    @modal.asgi_app()
    def serve(self):
        from main import app as web_app

        return web_app


# Background processing worker
@app.function(
    image=image,
    volumes=PROCESS_VOLUMES,
    timeout=1800,
    startup_timeout=300,
    retries=1,
    scaledown_window=300,
)
def process_case_modal(case_id: str):
    """
    Offload CT processing to a dedicated Modal worker.
    """
    if USE_SHARED_VOLUME and os.path.exists(DATA_PATH):
        data_volume.reload()

    storage_root = DATA_PATH if USE_SHARED_VOLUME and os.path.exists(DATA_PATH) else WORKER_STORAGE_ROOT
    os.environ["STORAGE_ROOT"] = storage_root
    os.environ["TEMP_STORAGE_ROOT"] = WORKER_TEMP_PATH
    settings.refresh_from_env()

    from api.dependencies import get_pipeline_service, reset_dependencies

    reset_dependencies()
    pipeline = get_pipeline_service()
    result = pipeline.process_case(case_id)
    if USE_SHARED_VOLUME and os.path.exists(DATA_PATH):
        data_volume.commit()

    return {
        "case_id": result.case_id,
        "success": result.success,
        "total_duration_seconds": result.total_duration_seconds,
        "error_message": result.error_message,
    }


# Background Upload Processors (Modal native)
@app.function(
    image=image,
    volumes=UPLOAD_VOLUMES,
    timeout=600,
)
def process_upload_modal(case_id: str, source_ref: str, filename: str, source_kind: str = "local"):
    """
    Process a DICOM/NIfTI upload in a separate Modal worker.
    """
    if USE_SHARED_VOLUME and os.path.exists(DATA_PATH):
        data_volume.reload()
    os.environ["STORAGE_ROOT"] = DATA_PATH if USE_SHARED_VOLUME and os.path.exists(DATA_PATH) else WORKER_STORAGE_ROOT
    os.environ["TEMP_STORAGE_ROOT"] = (
        SHARED_TEMP_PATH if USE_SHARED_VOLUME and os.path.exists(DATA_PATH) else WORKER_TEMP_PATH
    )
    settings.refresh_from_env()
    from api.dependencies import get_object_store, get_state_store, reset_dependencies
    from services.upload_service import process_single_upload_object_task, process_single_upload_task
    from storage.repository import CaseRepository

    reset_dependencies()
    repo = CaseRepository(state_store=get_state_store(), object_store=get_object_store())
    if source_kind == "object_store":
        process_single_upload_object_task(case_id, source_ref, filename, repo)
    else:
        process_single_upload_task(case_id, source_ref, filename, repo)
    if USE_SHARED_VOLUME and os.path.exists(DATA_PATH):
        data_volume.commit()


@app.function(
    image=image,
    volumes=UPLOAD_VOLUMES,
    timeout=600,
)
def process_dicom_dir_modal(case_id: str, temp_dir: str, extra_metadata: dict = None):
    """
    Process a DICOM directory upload in a separate Modal worker.
    """
    if USE_SHARED_VOLUME and os.path.exists(DATA_PATH):
        data_volume.reload()
    os.environ["STORAGE_ROOT"] = DATA_PATH if USE_SHARED_VOLUME and os.path.exists(DATA_PATH) else WORKER_STORAGE_ROOT
    os.environ["TEMP_STORAGE_ROOT"] = (
        SHARED_TEMP_PATH if USE_SHARED_VOLUME and os.path.exists(DATA_PATH) else WORKER_TEMP_PATH
    )
    settings.refresh_from_env()
    from api.dependencies import get_object_store, get_state_store, reset_dependencies
    from services.upload_service import process_dicom_directory_task
    from storage.repository import CaseRepository

    reset_dependencies()
    repo = CaseRepository(state_store=get_state_store(), object_store=get_object_store())
    process_dicom_directory_task(case_id, temp_dir, repo, extra_metadata)
    if USE_SHARED_VOLUME and os.path.exists(DATA_PATH):
        data_volume.commit()


@app.function(
    image=image,
    volumes=UPLOAD_VOLUMES,
    timeout=600,
)
def process_dicom_objects_modal(case_id: str, object_keys: list[str], extra_metadata: dict = None):
    """
    Process a DICOM upload that was staged in object storage.
    """
    if USE_SHARED_VOLUME and os.path.exists(DATA_PATH):
        data_volume.reload()
    os.environ["STORAGE_ROOT"] = DATA_PATH if USE_SHARED_VOLUME and os.path.exists(DATA_PATH) else WORKER_STORAGE_ROOT
    os.environ["TEMP_STORAGE_ROOT"] = (
        SHARED_TEMP_PATH if USE_SHARED_VOLUME and os.path.exists(DATA_PATH) else WORKER_TEMP_PATH
    )
    settings.refresh_from_env()
    from api.dependencies import get_object_store, get_state_store, reset_dependencies
    from services.upload_service import process_dicom_object_keys_task
    from storage.repository import CaseRepository

    reset_dependencies()
    repo = CaseRepository(state_store=get_state_store(), object_store=get_object_store())
    process_dicom_object_keys_task(case_id, object_keys, repo, extra_metadata)
    if USE_SHARED_VOLUME and os.path.exists(DATA_PATH):
        data_volume.commit()


if __name__ == "__main__":
    print("=" * 60)
    print("Dev:                  modal serve modal_app.py")
    print("Production:           modal deploy modal_app.py")
    print("=" * 60)
