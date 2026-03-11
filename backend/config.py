"""
Backend Configuration Settings

Central configuration for the CT-based Medical Imaging & AI Research Platform.
"""

from pathlib import Path
from typing import Optional
import os


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
    
    # Segmentation defaults
    DEFAULT_LUNG_THRESHOLD_LOW: float = -1000.0
    DEFAULT_LUNG_THRESHOLD_HIGH: float = -300.0
    DEFAULT_TISSUE_THRESHOLD: float = -600.0
    
    # Mesh generation
    MESH_FORMAT: str = "glb"  # Draco-compressed GLB for optimal web performance
    MESH_LEVEL_SET: float = 0.0  # Zero level set for surface extraction
    
    # Draco compression settings
    DRACO_COMPRESSION_LEVEL: int = 7
    DRACO_QUANTIZE_POSITION_BITS: int = 14
    DRACO_QUANTIZE_NORMAL_BITS: int = 10
    
    def __init__(self):
        # Ensure storage directory exists
        self.STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
