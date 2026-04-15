"""
Backend Configuration Settings

Central configuration for the CT-based Medical Imaging & AI Research Platform.
"""

from pathlib import Path
from typing import Optional
import json
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


DEV_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

DEV_TRUSTED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "testserver",
]


def _normalize_app_env(value: str | None) -> str:
    normalized = (value or "development").strip().lower()
    aliases = {
        "dev": "development",
        "local": "development",
        "prod": "production",
        "stage": "staging",
    }
    return aliases.get(normalized, normalized or "development")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default or [])

    value = raw.strip()
    if not value:
        return []

    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]

    return [item.strip() for item in value.split(",") if item.strip()]


def _default_cors_origins(app_env: str) -> list[str]:
    return DEV_CORS_ORIGINS if app_env != "production" else []


def _default_trusted_hosts(app_env: str) -> list[str]:
    return DEV_TRUSTED_HOSTS if app_env != "production" else []


class Settings:
    """Application settings with environment variable overrides."""
    
    # Application Info
    APP_NAME: str = "CT-based Medical Imaging & AI Research Platform"
    APP_VERSION: str = "2.0.0"
    APP_ENV: str = _normalize_app_env(os.getenv("APP_ENV"))
    DEBUG: bool = _env_bool("DEBUG", APP_ENV != "production")
    API_DOCS_ENABLED: bool = _env_bool("API_DOCS_ENABLED", APP_ENV != "production")
    HEALTH_DETAILS_ENABLED: bool = _env_bool("HEALTH_DETAILS_ENABLED", APP_ENV != "production")
    SECURITY_HEADERS_ENABLED: bool = _env_bool("SECURITY_HEADERS_ENABLED", True)
    TRUSTED_HOSTS: list[str] = _env_list("TRUSTED_HOSTS", _default_trusted_hosts(APP_ENV))
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
    OBJECT_STORE_DOWNLOAD_CONCURRENCY: int = int(os.getenv("OBJECT_STORE_DOWNLOAD_CONCURRENCY", "16"))
    R2_MAX_POOL_CONNECTIONS: int = int(os.getenv("R2_MAX_POOL_CONNECTIONS", "12"))
    R2_TRANSFER_MAX_CONCURRENCY: int = int(os.getenv("R2_TRANSFER_MAX_CONCURRENCY", "4"))
    R2_MULTIPART_THRESHOLD_MB: int = int(os.getenv("R2_MULTIPART_THRESHOLD_MB", "16"))
    R2_MULTIPART_CHUNK_SIZE_MB: int = int(os.getenv("R2_MULTIPART_CHUNK_SIZE_MB", "16"))
    PREFER_LOCAL_MODAL_INGEST: bool = os.getenv("PREFER_LOCAL_MODAL_INGEST", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    
    # CORS Settings
    CORS_ORIGINS: list[str] = _env_list("CORS_ORIGINS", _default_cors_origins(APP_ENV))
    CORS_ALLOW_CREDENTIALS: bool = _env_bool("CORS_ALLOW_CREDENTIALS", False)
    CORS_ALLOW_METHODS: list[str] = _env_list(
        "CORS_ALLOW_METHODS",
        ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    CORS_ALLOW_HEADERS: list[str] = _env_list(
        "CORS_ALLOW_HEADERS",
        ["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
    )
    
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
        self.APP_ENV = _normalize_app_env(os.getenv("APP_ENV"))
        self.DEBUG = _env_bool("DEBUG", self.APP_ENV != "production")
        self.API_DOCS_ENABLED = _env_bool("API_DOCS_ENABLED", self.APP_ENV != "production")
        self.HEALTH_DETAILS_ENABLED = _env_bool("HEALTH_DETAILS_ENABLED", self.APP_ENV != "production")
        self.SECURITY_HEADERS_ENABLED = _env_bool("SECURITY_HEADERS_ENABLED", True)
        self.TRUSTED_HOSTS = _env_list("TRUSTED_HOSTS", _default_trusted_hosts(self.APP_ENV))
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
        self.OBJECT_STORE_DOWNLOAD_CONCURRENCY = int(os.getenv("OBJECT_STORE_DOWNLOAD_CONCURRENCY", "16"))
        self.R2_MAX_POOL_CONNECTIONS = int(os.getenv("R2_MAX_POOL_CONNECTIONS", "12"))
        self.R2_TRANSFER_MAX_CONCURRENCY = int(os.getenv("R2_TRANSFER_MAX_CONCURRENCY", "4"))
        self.R2_MULTIPART_THRESHOLD_MB = int(os.getenv("R2_MULTIPART_THRESHOLD_MB", "16"))
        self.R2_MULTIPART_CHUNK_SIZE_MB = int(os.getenv("R2_MULTIPART_CHUNK_SIZE_MB", "16"))
        self.PREFER_LOCAL_MODAL_INGEST = os.getenv("PREFER_LOCAL_MODAL_INGEST", "true").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        self.CORS_ORIGINS = _env_list("CORS_ORIGINS", _default_cors_origins(self.APP_ENV))
        self.CORS_ALLOW_CREDENTIALS = _env_bool("CORS_ALLOW_CREDENTIALS", False)
        self.CORS_ALLOW_METHODS = _env_list(
            "CORS_ALLOW_METHODS",
            ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        )
        self.CORS_ALLOW_HEADERS = _env_list(
            "CORS_ALLOW_HEADERS",
            ["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
        )

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

    def should_prefer_local_modal_ingest(self) -> bool:
        """Whether Modal web containers should process ingest locally to avoid object-store round-trips."""
        return self.should_use_distributed_runtime() and self.PREFER_LOCAL_MODAL_INGEST

    def is_production_environment(self) -> bool:
        """Whether the app is running with production defaults."""
        return self.APP_ENV == "production"

    def docs_url(self) -> str | None:
        """FastAPI docs path for the current environment."""
        return "/docs" if self.API_DOCS_ENABLED else None

    def redoc_url(self) -> str | None:
        """ReDoc path for the current environment."""
        return "/redoc" if self.API_DOCS_ENABLED else None

    def openapi_url(self) -> str | None:
        """OpenAPI schema path for the current environment."""
        return "/openapi.json" if self.API_DOCS_ENABLED else None

    def runtime_mode_label(self) -> str:
        """Human-readable runtime mode label."""
        return "distributed" if self.should_use_distributed_runtime() else "shared_volume"

    def validate_runtime_configuration(self) -> None:
        """Validate distributed runtime flags before the app starts."""
        if self.DISTRIBUTED_RUNTIME_MODE not in {"auto", "required", "disabled"}:
            raise ValueError(
                "DISTRIBUTED_RUNTIME_MODE must be one of: auto, required, disabled"
            )

        if "*" in self.CORS_ORIGINS and self.CORS_ALLOW_CREDENTIALS:
            raise RuntimeError(
                "CORS_ORIGINS cannot contain '*' when CORS_ALLOW_CREDENTIALS=true"
            )

        if self.is_production_environment() and "*" in self.CORS_ORIGINS:
            raise RuntimeError(
                "CORS_ORIGINS cannot contain '*' in production. Configure explicit trusted origins."
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
