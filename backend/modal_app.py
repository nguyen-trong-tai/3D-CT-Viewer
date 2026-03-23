"""
Modal Deployment — CT Imaging Platform
Optimized for TotalSegmentator GPU inference

Changelog vs version cũ:
  - scaledown_window thay container_idle_timeout (deprecated)
  - @app.cls + @modal.enter để load model 1 lần per container
  - enable_memory_snapshot để tăng tốc cold start
  - startup_timeout tách biệt với execution timeout
  - retries=1 cho GPU job
  - gpu list để tránh unavailable GPU
  - max_containers để tránh OOM
"""

import modal
import os

app = modal.App("ct-imaging-platform")

# ── Volumes ───────────────────────────────────────────────────────────────────
weights_volume = modal.Volume.from_name("totalseg-weights", create_if_missing=True)
data_volume    = modal.Volume.from_name("ct-data",          create_if_missing=True)

WEIGHTS_PATH = "/weights"
DATA_PATH    = "/data"

# ── Image ─────────────────────────────────────────────────────────────────────
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
        "TotalSegmentator>=2.10.0",
    )
    .add_local_dir(
        local_path=".",
        remote_path="/root",
        ignore=lambda p: any(
            x in str(p)
            for x in ["venv", ".venv", "__pycache__", ".git", ".idea", ".vscode"]
        ),
    )
)

# ── FastAPI app (ASGI) ────────────────────────────────────────────────────────
@app.cls(
    image=image,
    gpu="A10G",             
    volumes={
        DATA_PATH:    data_volume,
        WEIGHTS_PATH: weights_volume,
    },
    timeout=600,                     
    startup_timeout=300,             
    scaledown_window=300,            
    min_containers=0,                
    max_containers=3,                
    enable_memory_snapshot=True,     
)
class FastAPIService:

    @modal.enter(snap=True)
    def load(self):
        os.environ["STORAGE_ROOT"]  = DATA_PATH
        os.environ["TOTALSEG_HOME_DIR"] = WEIGHTS_PATH

        from processing.segmentation import _warmup_task
        #_warmup_task("total")
        _warmup_task("lung_nodules")   # Nếu dùng task này

        print("[Container] Models in VRAM — ready.")

        # Pre-import nặng để tránh import delay trên first request
        import nibabel          # noqa
        import numpy            # noqa
        import totalsegmentator # noqa
        print("[Container] Warm up complete.")

    @modal.asgi_app()
    def serve(self):
        from main import app as web_app
        return web_app


# ── Heavy GPU job (background processing) ────────────────────────────────────
@app.function(
    image=image,
    gpu="A10G",       
    volumes={
        DATA_PATH:    data_volume,
        WEIGHTS_PATH: weights_volume,
    },
    timeout=1800,                    # 30 phút cho large CT volume
    startup_timeout=300,
    retries=1,                       # Retry 1 lần nếu GPU job fail (OOM, preemption...)
    scaledown_window=60,             # Job xong là down ngay — không cần giữ warm
)
def process_case_gpu(case_id: str):
    """
    Offload heavy CT processing lên GPU riêng.
    Gọi từ FastAPI: result = process_case_gpu.remote(case_id)
    """
    data_volume.reload()
    os.environ["STORAGE_ROOT"]  = DATA_PATH
    os.environ["TOTALSEG_HOME_DIR"] = WEIGHTS_PATH

    from api.dependencies import get_pipeline_service
    pipeline = get_pipeline_service()
    result   = pipeline.process_case(case_id)
    data_volume.commit()

    return {
        "case_id":                result.case_id,
        "success":                result.success,
        "total_duration_seconds": result.total_duration_seconds,
        "error_message":          result.error_message,
    }


# ── Background Upload Processors (Modal native) ──────────────────────────────
@app.function(
    image=image,
    volumes={DATA_PATH: data_volume},
    timeout=600,
)
def process_upload_modal(case_id: str, tmp_path: str, filename: str):
    """
    Hàm Modal native để xử lý DICOM/NIfTI zip upload ở chế độ nền.
    Tránh tình trạng web container ngủ đông (freeze) gây chết BackgroundTasks.
    """
    data_volume.reload()
    os.environ["STORAGE_ROOT"] = DATA_PATH
    from storage.repository import CaseRepository
    from api.routers.cases import process_single_upload_task
    
    repo = CaseRepository()
    process_single_upload_task(case_id, tmp_path, filename, repo)
    data_volume.commit()


@app.function(
    image=image,
    volumes={DATA_PATH: data_volume},
    timeout=600,
)
def process_dicom_dir_modal(case_id: str, temp_dir: str, extra_metadata: dict = None):
    """
    Hàm Modal native để xử lý DICOM directory upload ở chế độ nền.
    """
    data_volume.reload()
    os.environ["STORAGE_ROOT"] = DATA_PATH
    from storage.repository import CaseRepository
    from api.routers.cases import process_dicom_directory_task
    
    repo = CaseRepository()
    process_dicom_directory_task(case_id, temp_dir, repo, extra_metadata)
    data_volume.commit()


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("Setup (chạy 1 lần):  modal run modal_app.py::download_weights")
    print("Dev:                  modal serve modal_app.py")
    print("Production:           modal deploy modal_app.py")
    print("=" * 60)