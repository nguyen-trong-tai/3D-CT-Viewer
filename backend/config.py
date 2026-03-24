"""
Backend Configuration Settings

Central configuration for the CT-based Medical Imaging & AI Research Platform.
"""

from pathlib import Path
from typing import Optional
import os


def _load_dotenv_file() -> None:
    """Load environment variables from backend/.env without overriding real env vars."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv_file()


class Settings:
    """Application settings with environment variable overrides."""
    
    # Application Info
    APP_NAME: str = "CT-based Medical Imaging & AI Research Platform"
    APP_VERSION: str = "2.0.0"
    APP_DESCRIPTION: str = """
    A research-oriented platform for CT image viewing and AI experimentation.
    
    **DISCLAIMER**: This software is intended for research and educational purposes.
    It is not certified for clinical diagnosis or treatment.
    """
    
    # Storage Configuration
    # Default to local storage in workspace
    STORAGE_ROOT: Path = Path(os.getenv("STORAGE_ROOT", "d:/Workspace/viewr_ct/data"))
    TEMP_STORAGE_ROOT: Path = Path(os.getenv("TEMP_STORAGE_ROOT") or str(STORAGE_ROOT / "temp"))

    # State store configuration
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL")
    REDIS_KEY_PREFIX: str = os.getenv("REDIS_KEY_PREFIX")
    BATCH_SESSION_TTL_SECONDS: int = int(os.getenv("BATCH_SESSION_TTL_SECONDS", "3600"))
    PROCESSING_LOCK_TTL_SECONDS: int = int(os.getenv("PROCESSING_LOCK_TTL_SECONDS", "3600"))
    CASE_RETENTION_SECONDS: int = int(os.getenv("CASE_RETENTION_SECONDS", "7200"))
    RETENTION_CLEANUP_INTERVAL_SECONDS: int = int(os.getenv("RETENTION_CLEANUP_INTERVAL_SECONDS", "300"))

    # Object store configuration
    R2_TOKEN_VALUE: Optional[str] = os.getenv("R2_TOKEN_VALUE")
    R2_ACCOUNT_ID: Optional[str] = os.getenv("R2_ACCOUNT_ID")
    R2_ACCESS_KEY_ID: Optional[str] = os.getenv("R2_ACCESS_KEY_ID")
    R2_SECRET_ACCESS_KEY: Optional[str] = os.getenv("R2_SECRET_ACCESS_KEY")
    R2_BUCKET: Optional[str] = os.getenv("R2_BUCKET")
    R2_PUBLIC_BASE_URL: Optional[str] = os.getenv("R2_PUBLIC_BASE_URL")
    DISTRIBUTED_RUNTIME_MODE: str = os.getenv("DISTRIBUTED_RUNTIME_MODE", "auto").strip().lower()
    ARTIFACT_URL_TTL_SECONDS: int = int(os.getenv("ARTIFACT_URL_TTL_SECONDS", "3600"))
    MESH_URL_TTL_SECONDS: int = int(os.getenv("MESH_URL_TTL_SECONDS", "3600"))
    UPLOAD_URL_TTL_SECONDS: int = int(os.getenv("UPLOAD_URL_TTL_SECONDS", "900"))
    DIRECT_UPLOAD_CONCURRENCY: int = int(os.getenv("DIRECT_UPLOAD_CONCURRENCY", "4"))
    
    # CORS Settings
    CORS_ORIGINS: list = ["*"]  # Allow all for demo
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list = ["*"]
    CORS_ALLOW_HEADERS: list = ["*"]
    
    # Processing Settings
    # Maximum workers for parallel DICOM processing
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", os.cpu_count() or 4))
    
    # Downsampling thresholds for SDF computation
    SDF_VOXEL_THRESHOLD_LARGE: int = 100_000_000  # > 100M voxels -> factor 4
    SDF_VOXEL_THRESHOLD_MEDIUM: int = 50_000_000   # > 50M voxels -> factor 3
    SDF_VOXEL_THRESHOLD_SMALL: int = 20_000_000    # > 20M voxels -> factor 2

    # Preview artifacts for fast remote viewing
    PREVIEW_MAX_DIM: int = int(os.getenv("PREVIEW_MAX_DIM", "256"))
    PREVIEW_MAX_VOXELS: int = int(os.getenv("PREVIEW_MAX_VOXELS", "16000000"))
    
    # Segmentation defaults
    DEFAULT_LUNG_THRESHOLD_LOW: float = -1000.0
    DEFAULT_LUNG_THRESHOLD_HIGH: float = -300.0
    DEFAULT_TISSUE_THRESHOLD: float = -600.0
    
    # Mesh generation
    MESH_FORMAT: str = "glb"  # Draco-compressed GLB for optimal web performance
    MESH_LEVEL_SET: float = 0.0  # Zero level set for surface extraction
    MESH_STEP_SIZE_MEDIUM: int = int(os.getenv("MESH_STEP_SIZE_MEDIUM", "1"))
    MESH_STEP_SIZE_LARGE: int = int(os.getenv("MESH_STEP_SIZE_LARGE", "2"))
    MESH_STEP_SIZE_HUGE: int = int(os.getenv("MESH_STEP_SIZE_HUGE", "3"))
    
    # Draco compression settings
    DRACO_COMPRESSION_LEVEL: int = 7
    DRACO_QUANTIZE_POSITION_BITS: int = 14
    DRACO_QUANTIZE_NORMAL_BITS: int = 10
    
    def __init__(self):
        self.refresh_from_env()

    def refresh_from_env(self) -> None:
        """Reload env-driven settings at runtime."""
        self.STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", "d:/Workspace/viewr_ct/data"))
        self.TEMP_STORAGE_ROOT = Path(os.getenv("TEMP_STORAGE_ROOT") or str(self.STORAGE_ROOT / "temp"))

        self.REDIS_URL = os.getenv("REDIS_URL")
        self.REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX")
        self.BATCH_SESSION_TTL_SECONDS = int(os.getenv("BATCH_SESSION_TTL_SECONDS", "3600"))
        self.PROCESSING_LOCK_TTL_SECONDS = int(os.getenv("PROCESSING_LOCK_TTL_SECONDS", "3600"))
        self.CASE_RETENTION_SECONDS = int(os.getenv("CASE_RETENTION_SECONDS", "7200"))
        self.RETENTION_CLEANUP_INTERVAL_SECONDS = int(os.getenv("RETENTION_CLEANUP_INTERVAL_SECONDS", "300"))

        self.R2_TOKEN_VALUE = os.getenv("R2_TOKEN_VALUE")
        self.R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
        self.R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
        self.R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
        self.R2_BUCKET = os.getenv("R2_BUCKET")
        self.R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL")
        self.DISTRIBUTED_RUNTIME_MODE = os.getenv("DISTRIBUTED_RUNTIME_MODE", "auto").strip().lower()
        self.ARTIFACT_URL_TTL_SECONDS = int(os.getenv("ARTIFACT_URL_TTL_SECONDS", "3600"))
        self.MESH_URL_TTL_SECONDS = int(os.getenv("MESH_URL_TTL_SECONDS", "3600"))
        self.UPLOAD_URL_TTL_SECONDS = int(os.getenv("UPLOAD_URL_TTL_SECONDS", "900"))
        self.DIRECT_UPLOAD_CONCURRENCY = int(os.getenv("DIRECT_UPLOAD_CONCURRENCY", "4"))

        self.MAX_WORKERS = int(os.getenv("MAX_WORKERS", os.cpu_count() or 4))
        self.PREVIEW_MAX_DIM = int(os.getenv("PREVIEW_MAX_DIM", "256"))
        self.PREVIEW_MAX_VOXELS = int(os.getenv("PREVIEW_MAX_VOXELS", "16000000"))
        self.MESH_STEP_SIZE_MEDIUM = int(os.getenv("MESH_STEP_SIZE_MEDIUM", "1"))
        self.MESH_STEP_SIZE_LARGE = int(os.getenv("MESH_STEP_SIZE_LARGE", "2"))
        self.MESH_STEP_SIZE_HUGE = int(os.getenv("MESH_STEP_SIZE_HUGE", "3"))

        # Ensure storage directories exist after refresh.
        self.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
        self.TEMP_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

        self.validate_runtime_configuration()

    def has_redis_state(self) -> bool:
        """Whether a distributed Redis state store is configured."""
        return bool(self.REDIS_URL)

    def has_r2_object_store(self) -> bool:
        """Whether the Cloudflare R2 object store is fully configured."""
        return all(
            [
                self.R2_ACCOUNT_ID,
                self.R2_ACCESS_KEY_ID,
                self.R2_SECRET_ACCESS_KEY,
                self.R2_BUCKET,
            ]
        )

    def distributed_runtime_required(self) -> bool:
        """Whether distributed runtime backends must be available at boot."""
        return self.DISTRIBUTED_RUNTIME_MODE == "required"

    def distributed_runtime_disabled(self) -> bool:
        """Whether distributed runtime should be bypassed even if configured."""
        return self.DISTRIBUTED_RUNTIME_MODE == "disabled"

    def should_use_redis_state(self) -> bool:
        """Whether the app should actively use Redis for operational state."""
        return not self.distributed_runtime_disabled() and self.has_redis_state()

    def should_use_r2_object_store(self) -> bool:
        """Whether the app should actively use R2 for artifact storage."""
        return not self.distributed_runtime_disabled() and self.has_r2_object_store()

    def should_use_distributed_runtime(self) -> bool:
        """Whether both remote backends are enabled for distributed execution."""
        return self.should_use_redis_state() and self.should_use_r2_object_store()

    def runtime_mode_label(self) -> str:
        """Human-readable runtime mode label."""
        return "distributed" if self.should_use_distributed_runtime() else "shared_volume"

    def validate_runtime_configuration(self) -> None:
        """Validate distributed runtime flags before the app starts."""
        if self.DISTRIBUTED_RUNTIME_MODE not in {"auto", "required", "disabled"}:
            raise ValueError(
                "DISTRIBUTED_RUNTIME_MODE must be one of: auto, required, disabled"
            )

        if not self.distributed_runtime_required():
            return

        missing: list[str] = []
        if not self.REDIS_URL:
            missing.append("REDIS_URL")
        if not self.R2_ACCOUNT_ID:
            missing.append("R2_ACCOUNT_ID")
        if not self.R2_ACCESS_KEY_ID:
            missing.append("R2_ACCESS_KEY_ID")
        if not self.R2_SECRET_ACCESS_KEY:
            missing.append("R2_SECRET_ACCESS_KEY")
        if not self.R2_BUCKET:
            missing.append("R2_BUCKET")

        if missing:
            raise RuntimeError(
                "DISTRIBUTED_RUNTIME_MODE=required but the following variables are missing: "
                + ", ".join(missing)
            )


# Global settings instance
settings = Settings()
