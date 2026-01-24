"""
Storage Repository

File-based persistence layer for CT volumes, masks, meshes, and case metadata.
Implements the repository pattern for clean separation of storage concerns.
"""

import os
import json
import numpy as np
import trimesh
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from config import settings
from models.enums import CaseStatus


class CaseRepository:
    """
    Repository for managing case data and artifacts.
    
    Storage structure per case:
    {STORAGE_ROOT}/{case_id}/
        ├── status.json           # Case status and metadata
        ├── ct_volume.npy         # HU volume data (int16)
        ├── ct_metadata.json      # Volume dimensions, spacing, etc.
        ├── extra_metadata.json   # Patient/study info (optional)
        ├── mask_volume.npy       # Segmentation mask (uint8)
        ├── sdf_volume.npy        # SDF data (float32)
        └── mesh.obj              # Surface mesh (OBJ format)
    """
    
    def __init__(self, root_dir: Path = None):
        self.root_dir = root_dir or settings.STORAGE_ROOT
        self.root_dir.mkdir(parents=True, exist_ok=True)
        
    def _case_dir(self, case_id: str) -> Path:
        """Get the directory path for a specific case."""
        return self.root_dir / case_id
    
    def case_exists(self, case_id: str) -> bool:
        """Check if a case exists."""
        return self._case_dir(case_id).exists()
    
    # =========================================================================
    # Case Lifecycle Management
    # =========================================================================
    
    def create_case(self, case_id: str) -> bool:
        """
        Create a new case directory and initialize status.
        
        Returns True if created, False if already exists.
        """
        case_path = self._case_dir(case_id)
        if case_path.exists():
            return False
            
        case_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize case status
        status_data = {
            "status": CaseStatus.PENDING.value,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._save_json(case_path / "status.json", status_data)
        
        return True
    
    def delete_case(self, case_id: str) -> bool:
        """
        Delete a case and all its artifacts.
        
        Returns True if deleted, False if not found.
        """
        import shutil
        case_path = self._case_dir(case_id)
        if not case_path.exists():
            return False
        shutil.rmtree(case_path, ignore_errors=True)
        return True
    
    # =========================================================================
    # Status Management
    # =========================================================================
    
    def update_status(self, case_id: str, status: str, message: str = None):
        """Update the status of a case."""
        case_path = self._case_dir(case_id)
        status_file = case_path / "status.json"
        
        # Load existing or create new
        if status_file.exists():
            status_data = self._load_json(status_file)
        else:
            status_data = {"created_at": datetime.utcnow().isoformat()}
        
        status_data["status"] = status
        status_data["updated_at"] = datetime.utcnow().isoformat()
        if message:
            status_data["message"] = message
            
        self._save_json(status_file, status_data)
    
    def get_status(self, case_id: str) -> str:
        """
        Get the current status of a case.
        
        Returns the status string, or "uploaded" for early state,
        or "error" if case doesn't exist.
        """
        case_path = self._case_dir(case_id)
        status_file = case_path / "status.json"
        
        if not case_path.exists():
            return "error"  # Case doesn't exist
            
        if not status_file.exists():
            # Early state - status file not yet created
            return CaseStatus.UPLOADED.value
        
        status_data = self._load_json(status_file)
        return status_data.get("status", CaseStatus.UPLOADED.value)
    
    def get_status_info(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Get full status information for a case."""
        status_file = self._case_dir(case_id) / "status.json"
        if not status_file.exists():
            return None
        return self._load_json(status_file)
    
    # =========================================================================
    # CT Volume Storage
    # =========================================================================
    
    def save_ct_volume(
        self, 
        case_id: str, 
        volume: np.ndarray, 
        spacing: Tuple[float, float, float]
    ):
        """
        Save CT volume and metadata.
        
        Volume is saved as int16 to preserve HU values (-1024 to +3071 typical range).
        """
        case_path = self._case_dir(case_id)
        case_path.mkdir(parents=True, exist_ok=True)
        
        # Save volume as int16 (preserves full HU range)
        volume_int16 = volume.astype(np.int16)
        np.save(case_path / "ct_volume.npy", volume_int16)
        
        # Compute HU range
        hu_min = float(np.min(volume))
        hu_max = float(np.max(volume))
        
        # Save metadata
        metadata = {
            "shape": list(volume.shape),
            "spacing": list(spacing),
            "dtype": "int16",
            "hu_range": {"min": hu_min, "max": hu_max},
        }
        self._save_json(case_path / "ct_metadata.json", metadata)
        
        # Update status
        self.update_status(case_id, CaseStatus.UPLOADED.value)
    
    def load_ct_volume(self, case_id: str) -> Optional[np.ndarray]:
        """Load CT volume data."""
        path = self._case_dir(case_id) / "ct_volume.npy"
        if not path.exists():
            return None
        return np.load(path)
    
    def load_ct_volume_mmap(self, case_id: str) -> Optional[np.ndarray]:
        """Load CT volume with memory mapping for efficient slice access."""
        path = self._case_dir(case_id) / "ct_volume.npy"
        if not path.exists():
            return None
        return np.load(path, mmap_mode='r')
    
    def load_ct_metadata(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Load CT volume metadata."""
        path = self._case_dir(case_id) / "ct_metadata.json"
        if not path.exists():
            return None
        return self._load_json(path)
    
    # =========================================================================
    # Extra Metadata (Patient Info, Study Details)
    # =========================================================================
    
    def save_extra_metadata(self, case_id: str, metadata: Dict[str, Any]):
        """Save additional metadata (patient info, study details, etc.)."""
        case_path = self._case_dir(case_id)
        self._save_json(case_path / "extra_metadata.json", metadata)
    
    def load_extra_metadata(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Load additional metadata if available."""
        path = self._case_dir(case_id) / "extra_metadata.json"
        if not path.exists():
            return None
        return self._load_json(path)
    
    # =========================================================================
    # Segmentation Mask Storage
    # =========================================================================
    
    def save_mask(self, case_id: str, mask: np.ndarray):
        """Save segmentation mask as uint8 (0 or 1)."""
        case_path = self._case_dir(case_id)
        np.save(case_path / "mask_volume.npy", mask.astype(np.uint8))
    
    def load_mask(self, case_id: str) -> Optional[np.ndarray]:
        """Load segmentation mask."""
        path = self._case_dir(case_id) / "mask_volume.npy"
        if not path.exists():
            return None
        return np.load(path)
    
    def load_mask_mmap(self, case_id: str) -> Optional[np.ndarray]:
        """Load segmentation mask with memory mapping for efficient slice access."""
        path = self._case_dir(case_id) / "mask_volume.npy"
        if not path.exists():
            return None
        return np.load(path, mmap_mode='r')
    
    def mask_exists(self, case_id: str) -> bool:
        """Check if segmentation mask exists for a case."""
        return (self._case_dir(case_id) / "mask_volume.npy").exists()
    
    # =========================================================================
    # SDF Storage
    # =========================================================================
    
    def save_sdf(self, case_id: str, sdf: np.ndarray):
        """Save SDF volume as float32 for space efficiency."""
        case_path = self._case_dir(case_id)
        np.save(case_path / "sdf_volume.npy", sdf.astype(np.float32))
    
    def load_sdf(self, case_id: str) -> Optional[np.ndarray]:
        """Load SDF volume."""
        path = self._case_dir(case_id) / "sdf_volume.npy"
        if not path.exists():
            return None
        return np.load(path)
    
    def sdf_exists(self, case_id: str) -> bool:
        """Check if SDF exists for a case."""
        return (self._case_dir(case_id) / "sdf_volume.npy").exists()
    
    # =========================================================================
    # Mesh Storage
    # =========================================================================
    
    def save_mesh(self, case_id: str, mesh: trimesh.Trimesh):
        """Save mesh in OBJ format."""
        case_path = self._case_dir(case_id)
        mesh.export(case_path / "mesh.obj")
    
    def load_mesh(self, case_id: str) -> Optional[trimesh.Trimesh]:
        """Load mesh from file."""
        path = self._case_dir(case_id) / "mesh.obj"
        if not path.exists():
            return None
        return trimesh.load(path)
    
    def get_mesh_path(self, case_id: str) -> Optional[Path]:
        """Get path to mesh file if it exists."""
        path = self._case_dir(case_id) / "mesh.obj"
        return path if path.exists() else None
    
    def mesh_exists(self, case_id: str) -> bool:
        """Check if mesh exists for a case."""
        return (self._case_dir(case_id) / "mesh.obj").exists()
    
    # =========================================================================
    # Artifact Information
    # =========================================================================
    
    def get_available_artifacts(self, case_id: str) -> Dict[str, bool]:
        """Get a dictionary of available artifacts for a case."""
        case_path = self._case_dir(case_id)
        return {
            "ct_volume": (case_path / "ct_volume.npy").exists(),
            "ct_metadata": (case_path / "ct_metadata.json").exists(),
            "segmentation_mask": (case_path / "mask_volume.npy").exists(),
            "sdf": (case_path / "sdf_volume.npy").exists(),
            "mesh": (case_path / "mesh.obj").exists(),
            "extra_metadata": (case_path / "extra_metadata.json").exists(),
        }
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def _save_json(self, path: Path, data: Dict[str, Any]):
        """Save data to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    
    def _load_json(self, path: Path) -> Dict[str, Any]:
        """Load data from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
